"""
Linux sampling backend for profile_sim.py.

Runs the built simulation under `perf record` with call graphs and counts the
sampled stacks, so the report can charge a sample to the equation block whose
generated function encloses it, not only to the leaf it happened to land in.

Unwinding uses DWARF rather than frame pointers: the generated code is compiled
optimized, so frame pointers cannot be relied on to walk past the leaf, while the
debug info the diagnose build keeps beside the executable is what DWARF needs.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections import Counter

import sampler_common

# "  55f1a2b3c4d5 residualFunc_21+0x44 (/tmp/_wsm_diagnose_temp/Slow.exe)"
_LINE_RE = re.compile(r"^\s*(?P<ip>[0-9a-fA-F]+)\s+(?P<sym>.*?)\s*$")
_DSO_RE = re.compile(r"\s*\([^()]*\)\s*$")
_OFFSET_RE = re.compile(r"\+0x[0-9a-fA-F]+$")


def _normalize(sym, ip):
    sym = _OFFSET_RE.sub("", _DSO_RE.sub("", sym)).strip()
    if not sym or sym == "[unknown]":
        return "0x%s" % (ip.lstrip("0").lower() or "0")
    return sampler_common.normalize(sym)


def parse_script(text):
    """Samples per call stack, from `perf script -F ip,sym` output.

    perf prints one indented frame per line, innermost first, and separates
    samples with a blank line. Keys come back outermost-frame first, matching the
    other backends."""
    counts = Counter()
    frames = []
    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("#"):
            continue
        if not line.strip():
            if frames:
                counts[tuple(reversed(frames))] += 1
                frames = []
            continue
        m = _LINE_RE.match(line)
        if m:
            frames.append(_normalize(m.group("sym"), m.group("ip")))
    return counts


def sample(exe, sim, hz, seconds, result=False):
    perf = os.environ.get("WSM_PROFILER") or shutil.which("perf") or "perf"
    workdir = tempfile.mkdtemp(prefix="wsm_profile_")
    data = os.path.join(workdir, "perf.data")
    proc, log = sampler_common.launch(exe, sim, result)
    started = time.time()
    try:
        # `-- sleep N` gives perf a dummy workload to time the recording by; perf
        # still profiles the -p target. SIGINT makes it flush early when the
        # simulation finishes before the budget.
        recorder = subprocess.Popen(
            [perf, "record", "--call-graph", "dwarf", "-F", str(max(1, int(hz))),
             "-p", str(proc.pid), "-o", data, "--", "sleep", "%g" % seconds],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        wall, ended_early = sampler_common.wait_for_sampler(
            recorder, proc, started, seconds,
            on_target_exit=lambda: recorder.send_signal(signal.SIGINT))
        recorder_err = (recorder.stderr.read() or b"").decode("utf-8", "replace")
    finally:
        sampler_common.stop(proc)

    counts = Counter()
    if os.path.isfile(data):
        script = subprocess.run([perf, "script", "-i", data, "-F", "ip,sym"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        counts = parse_script(script.stdout.decode("utf-8", "replace"))
    shutil.rmtree(workdir, ignore_errors=True)
    if not counts and recorder_err.strip():
        print("perf: " + recorder_err.strip().splitlines()[-1])
    return counts, wall, (ended_early, sampler_common.tail_log(log))
