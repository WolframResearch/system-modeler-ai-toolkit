"""Recognise compiler failures in a kernel run and give each a stable signature.

A compiler failure is a fault in System Modeler itself rather than in the model:
an internal error, generated code that does not compile, a simulator internal
error, or a kernel crash. Ordinary model errors (type, lookup, balance, ...) are
not compiler failures and are never classified as one.

The signature identifies the failure across edits of the model: numbers are
masked, locations and paths are dropped, and `head` keeps only the part that
names the failing compiler step, so two runs that hit the same fault still
match after a component or variable has been removed or renamed.
"""
import json
import re
from dataclasses import dataclass

INTERNAL = "internal"
CODEGEN_COMPILE = "codegen_compile"
SIM_INTERNAL = "sim_internal"
CRASH = "crash"

_CPP_COMPILATION_ERROR_ID = "22"
_SIM_INTERNAL_EXIT_CODES = {3: "crash", 101: "internal error", 106: "stack overflow", 255: "crash"}
_NOT_COMPILER_FAULTS = ("Unknown library",)
_KERNEL_FAULT_EXIT_CODES = {50, 51}
_FATAL_EXCEPTION = re.compile(r"Fatal error: exception (.+)")


@dataclass(frozen=True)
class Failure:
    kind: str
    head: str
    signature: str
    message: str

    def matches(self, other, strict=False):
        if other is None or other.kind != self.kind:
            return False
        return other.signature == self.signature if strict else other.head == self.head

    def to_dict(self):
        return {"kind": self.kind, "head": self.head, "signature": self.signature,
                "message": self.message}


def load_test_record(out_json_path):
    """The first test record of a <mode>.out.json, or None when there is none."""
    try:
        with open(out_json_path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    for entry in data if isinstance(data, list) else [data]:
        if isinstance(entry, dict) and "status" in entry:
            return entry
    return None


def _plain(text):
    text = re.sub(r"\\\[`([^`]*)`\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\\;`|\\\(|\\", "", text)
    return text


def _mask(text):
    text = _plain(text)
    text = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][^\\/\s:'\"`]+)+\.(?:mo|mos|cpp|h|ml)\b", "<path>", text)
    text = re.sub(r"\d+(?:\.\d+)?(?:e[+-]?\d+)?", "N", text)
    return re.sub(r"\s+", " ", text).strip()


def _head(message):
    first = _plain(message).strip().splitlines()[0] if message.strip() else ""
    fatal_file = re.match(r"Fatal failure: File: ([^,]+)", first)
    if fatal_file:
        return "Fatal failure: File: " + fatal_file.group(1)
    step = re.match(r'"?([A-Za-z_][\w.]*(?:\.\(fun\))?)"?:(.*)', first)
    if step and "." in step.group(1):
        prose = re.split(r"[:(`'\"{\[]", step.group(2), maxsplit=1)[0]
        return (step.group(1) + ": " + _mask(prose)).strip(": ")
    return _mask(first)[:160]


_COMPILER_ERROR = re.compile(r"(?:^|[\s:)])(?:fatal )?error(?: (C\d+))?: (.*)")


def _compiler_errors(log):
    """``(code, text)`` of each compiler error line; ``code`` is the MSVC error code or ''."""
    errors = []
    for line in log.splitlines():
        m = _COMPILER_ERROR.search(line)
        if m:
            errors.append((m.group(1) or "", m.group(2).strip()))
    return errors


def _failure(kind, message, head=None):
    return Failure(kind, head if head is not None else _head(message), _mask(message), message.strip())


def _codegen_failure(log):
    errors = _compiler_errors(log)
    if not errors:
        return _failure(CODEGEN_COMPILE, _plain(log).strip().split("\n", 1)[0])
    text = "\n".join((code + ": " if code else "") + msg for code, msg in errors)
    code, msg = errors[0]
    head = (code + ": " if code else "") + re.sub(r"'[^']*'", "'…'", _mask(msg))
    return _failure(CODEGEN_COMPILE, text, head)


def _exit_failure(kind, message):
    return _failure(kind, message, message)


def classify(record, output="", returncode=0):
    """The compiler failure shown by one run, or None.

    `record` is the test record from the run's out.json (None when the kernel
    produced none), `output` the kernel's combined stdout/stderr, `returncode`
    its exit status."""
    if record is None:
        fatal = _FATAL_EXCEPTION.search(output or "")
        if fatal:
            return _failure(CRASH, fatal.group(1))
        if returncode in _KERNEL_FAULT_EXIT_CODES:
            return _exit_failure(CRASH, "kernel stopped with an internal error (exit code %d)" % returncode)
        if returncode is not None and (returncode < 0 or returncode > 255):
            return _exit_failure(CRASH, "kernel crashed (exit status %d)" % returncode)
        return None

    messages = record.get("messages") or {}
    for item in messages.get("internal_errors") or []:
        text = (item or {}).get("message") or ""
        if text and not any(marker in text for marker in _NOT_COMPILER_FAULTS):
            return _failure(INTERNAL, text)

    for item in (messages.get("errors") or []) + (record.get("status", {}).get("errors") or []):
        if isinstance(item, dict) and item.get("id") == _CPP_COMPILATION_ERROR_ID:
            return _codegen_failure(item.get("message") or "")

    code = record.get("simulation_exit_code")
    if code in _SIM_INTERNAL_EXIT_CODES:
        return _exit_failure(SIM_INTERNAL, "simulator %s (exit code %d)" % (_SIM_INTERNAL_EXIT_CODES[code], code))
    return None


def classify_run(out_json_path, output="", returncode=0):
    return classify(load_test_record(out_json_path) if out_json_path else None, output, returncode)
