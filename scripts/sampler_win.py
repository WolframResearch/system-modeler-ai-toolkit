"""
Windows sampling backend for profile_sim.py.

Runs the built simulation, walks the call stack of its busiest thread with
dbghelp, and resolves each address to a function name through the debug symbols
that the diagnose build leaves next to the executable. Imported only on Windows;
the launcher gates the platform.
"""

import ctypes
import os
import time
from collections import Counter
from ctypes import wintypes

import sampler_common

THREAD_ACCESS = 0x0002 | 0x0008 | 0x0040
CONTEXT_AMD64_FULL = 0x00100000 | 0x1 | 0x2 | 0x8   # AMD64 | CONTROL|INTEGER|FP
CONTEXT_SIZE = 1232
CONTEXT_FLAGS_OFFSET = 0x30
RSP_OFFSET = 0x98
RBP_OFFSET = 0xA0
RIP_OFFSET = 0xF8
TH32CS_SNAPTHREAD = 0x00000004
SYM_OPTIONS = 0x00000002 | 0x00000100          # undecorated names, line numbers
SYMBOL_INFO_SIZE = 88
MAX_SYM_NAME = 1024
IMAGE_FILE_MACHINE_AMD64 = 0x8664
ADDR_MODE_FLAT = 3
MAX_FRAMES = 64

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenThread.restype = wintypes.HANDLE
kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.SuspendThread.restype = wintypes.DWORD
kernel32.SuspendThread.argtypes = [wintypes.HANDLE]
kernel32.ResumeThread.restype = wintypes.DWORD
kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
kernel32.GetThreadContext.restype = wintypes.BOOL
kernel32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.GetThreadTimes.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

dbghelp.SymSetOptions.restype = wintypes.DWORD
dbghelp.SymSetOptions.argtypes = [wintypes.DWORD]
dbghelp.SymInitialize.restype = wintypes.BOOL
dbghelp.SymInitialize.argtypes = [wintypes.HANDLE, wintypes.LPCSTR, wintypes.BOOL]
dbghelp.SymCleanup.restype = wintypes.BOOL
dbghelp.SymCleanup.argtypes = [wintypes.HANDLE]
dbghelp.SymFromAddr.restype = wintypes.BOOL
dbghelp.SymFromAddr.argtypes = [wintypes.HANDLE, ctypes.c_ulonglong,
                                ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_void_p]


class ADDRESS64(ctypes.Structure):
    _fields_ = [("Offset", ctypes.c_ulonglong),
                ("Segment", wintypes.WORD),
                ("Mode", ctypes.c_int)]


class STACKFRAME64(ctypes.Structure):
    _fields_ = [("AddrPC", ADDRESS64),
                ("AddrReturn", ADDRESS64),
                ("AddrFrame", ADDRESS64),
                ("AddrStack", ADDRESS64),
                ("AddrBStore", ADDRESS64),
                ("FuncTableEntry", ctypes.c_void_p),
                ("Params", ctypes.c_ulonglong * 4),
                ("Far", wintypes.BOOL),
                ("Virtual", wintypes.BOOL),
                ("Reserved", ctypes.c_ulonglong * 3),
                ("KdHelp", ctypes.c_byte * 120)]      # KDHELP64, opaque to us


try:
    dbghelp.SymFunctionTableAccess64.restype = ctypes.c_void_p
    dbghelp.SymFunctionTableAccess64.argtypes = [wintypes.HANDLE, ctypes.c_ulonglong]
    dbghelp.SymGetModuleBase64.restype = ctypes.c_ulonglong
    dbghelp.SymGetModuleBase64.argtypes = [wintypes.HANDLE, ctypes.c_ulonglong]
    dbghelp.StackWalk64.restype = wintypes.BOOL
    dbghelp.StackWalk64.argtypes = [wintypes.DWORD, wintypes.HANDLE, wintypes.HANDLE,
                                    ctypes.POINTER(STACKFRAME64), ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p]
    # StackWalk64 takes these as plain callback pointers.
    _FUNCTION_TABLE_ACCESS = ctypes.cast(dbghelp.SymFunctionTableAccess64,
                                         ctypes.c_void_p)
    _GET_MODULE_BASE = ctypes.cast(dbghelp.SymGetModuleBase64, ctypes.c_void_p)
    CAN_WALK_STACKS = True
except AttributeError:
    # A dbghelp too old to walk stacks: sample the instruction pointer instead,
    # which charges a sample to the block whose own code it landed in. The report
    # says which of the two it got.
    CAN_WALK_STACKS = False


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


def _ft(f):
    return (f.dwHighDateTime << 32) | f.dwLowDateTime


def _thread_ids(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return []
    ids = []
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = kernel32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            ids.append(entry.th32ThreadID)
        ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return ids


def _cpu_time(handle):
    c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    if not kernel32.GetThreadTimes(handle, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(k), ctypes.byref(u)):
        return 0
    return _ft(k) + _ft(u)


def _aligned_context():
    raw = ctypes.create_string_buffer(CONTEXT_SIZE + 16)
    addr = (ctypes.addressof(raw) + 15) & ~15
    return raw, addr


def _busiest_thread(pid):
    best, best_time = None, -1
    for tid in _thread_ids(pid):
        h = kernel32.OpenThread(THREAD_ACCESS, False, tid)
        if not h:
            continue
        t = _cpu_time(h)
        if t > best_time:
            if best:
                kernel32.CloseHandle(best)
            best, best_time = h, t
        else:
            kernel32.CloseHandle(h)
    return best


def _walk(proc_handle, thread, ctx):
    """The suspended thread's call stack, outermost frame first.

    StackWalk64 reads the target's stack and unwind data through the process
    handle, so it must run while the thread is still suspended and after
    SymInitialize has loaded the modules."""
    frame = STACKFRAME64()
    frame.AddrPC.Offset = ctypes.c_ulonglong.from_address(ctx + RIP_OFFSET).value
    frame.AddrPC.Mode = ADDR_MODE_FLAT
    frame.AddrStack.Offset = ctypes.c_ulonglong.from_address(ctx + RSP_OFFSET).value
    frame.AddrStack.Mode = ADDR_MODE_FLAT
    frame.AddrFrame.Offset = ctypes.c_ulonglong.from_address(ctx + RBP_OFFSET).value
    frame.AddrFrame.Mode = ADDR_MODE_FLAT

    addresses = []
    while len(addresses) < MAX_FRAMES:
        if not dbghelp.StackWalk64(IMAGE_FILE_MACHINE_AMD64, proc_handle, thread,
                                   ctypes.byref(frame), ctypes.c_void_p(ctx),
                                   None, _FUNCTION_TABLE_ACCESS, _GET_MODULE_BASE,
                                   None):
            break
        pc = frame.AddrPC.Offset
        if not pc:
            break
        addresses.append(pc)
    addresses.reverse()
    return tuple(addresses)


def _sym_init(proc_handle, search_path):
    dbghelp.SymSetOptions(SYM_OPTIONS)
    return bool(dbghelp.SymInitialize(proc_handle, search_path.encode("mbcs"), True))


def _sym_names(proc_handle, addresses):
    buf = ctypes.create_string_buffer(SYMBOL_INFO_SIZE + MAX_SYM_NAME)
    disp = ctypes.c_ulonglong(0)
    names = {}
    for a in addresses:
        ctypes.memset(buf, 0, len(buf))
        ctypes.memmove(buf, ctypes.byref(ctypes.c_ulong(SYMBOL_INFO_SIZE)), 4)
        ctypes.memmove(ctypes.byref(buf, 80),
                       ctypes.byref(ctypes.c_ulong(MAX_SYM_NAME)), 4)
        if dbghelp.SymFromAddr(proc_handle, ctypes.c_ulonglong(a),
                               ctypes.byref(disp), buf):
            name = ctypes.string_at(ctypes.addressof(buf) + 84).decode("mbcs", "replace")
            names[a] = (sampler_common.normalize(name) if name
                        else "0x%x" % a)
        else:
            names[a] = "0x%x" % a
    return names


def sample(exe, sim, hz, seconds, result=False):
    proc, log = sampler_common.launch(exe, sim, result)
    handle = kernel32.OpenProcess(0x0410, False, proc.pid)   # QUERY_INFORMATION|VM_READ

    raw, ctx = _aligned_context()
    hits = Counter()
    interval = max(0.001, 1.0 / max(hz, 1))
    started = time.time()
    thread = None
    symbols_loaded = False
    try:
        while proc.poll() is None and time.time() - started < seconds:
            if thread is None:
                thread = _busiest_thread(proc.pid)
            if thread:
                if kernel32.SuspendThread(thread) != 0xFFFFFFFF:
                    ctypes.memset(ctx, 0, CONTEXT_SIZE)
                    ctypes.memmove(ctx + CONTEXT_FLAGS_OFFSET,
                                   ctypes.byref(ctypes.c_ulong(CONTEXT_AMD64_FULL)), 4)
                    if kernel32.GetThreadContext(thread, ctypes.c_void_p(ctx)):
                        pc = ctypes.c_ulonglong.from_address(ctx + RIP_OFFSET).value
                        stack = (_walk(handle, thread, ctx)
                                 if symbols_loaded and CAN_WALK_STACKS else ())
                        hits[stack or (pc,)] += 1
                    kernel32.ResumeThread(thread)
                else:
                    kernel32.CloseHandle(thread)
                    thread = None
            # Symbols are read out of the live process, and SymInitialize gets one
            # chance: invade it only once the run has executed, so the loader has
            # mapped the modules the frames resolve through.
            if not symbols_loaded and hits:
                symbols_loaded = _sym_init(handle, os.path.dirname(exe))
            time.sleep(interval)
        wall = time.time() - started
        addresses = {a for stack in hits for a in stack}
        names = _sym_names(handle, addresses) if symbols_loaded else {}
        ended_early = proc.poll() is not None
    finally:
        if symbols_loaded:
            dbghelp.SymCleanup(handle)
        if thread:
            kernel32.CloseHandle(thread)
        sampler_common.stop(proc)
        kernel32.CloseHandle(handle)

    counts = Counter()
    for stack, n in hits.items():
        counts[tuple(names.get(a, "0x%x" % a) for a in stack)] += n
    return counts, wall, (ended_early, sampler_common.tail_log(log, "mbcs"))
