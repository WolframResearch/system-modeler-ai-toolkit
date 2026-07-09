"""
Shared helpers for reading WSMKernelX diagnostic artifacts (block-debug JSON,
generated header, simulation res.log, test out.json).

Standard-library only (``json`` / ``re``), so every diagnostic script can import
it without the managed venv. This is the single home for the JSON loading,
section labelling, solver-system discovery, Jacobian classification, header and
res.log parsing that ``report_blocks.py`` and the ``check_*`` / ``trace_variable``
scripts would otherwise each re-implement.
"""

import json
import re
import sys


def enable_utf8_console():
    """Best-effort: switch stdout/stderr to UTF-8 so the non-ASCII glyphs the
    reports print (⚠, em dashes) don't crash on a legacy Windows console. A no-op
    where the runtime doesn't support reconfigure (Python < 3.7) or a stream lacks
    it (already-redirected pipes are typically fine)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# Section keys in a blockdebug.json and their human labels.
SECTION_LABELS = {
    "init": "Initialization",
    "ode": "Integration (ODE)",
    "output": "Output",
    "clocked": "Clocked",
}


def section_label(section):
    """Human label for a blockdebug section key (falls back to the key)."""
    return SECTION_LABELS.get(section, section)


def load(path):
    """Load a JSON artifact (blockdebug.json / out.json) with explicit UTF-8.

    'utf-8-sig' tolerates the BOM the kernel may emit. An unreadable or
    malformed/truncated file exits with a clear message instead of leaking a raw
    traceback through every consumer script."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except OSError as exc:
        sys.exit("ERROR: cannot read %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        sys.exit("ERROR: %s is not valid JSON (%s).\n"
                 "The file is likely truncated or from a failed kernel run — "
                 "re-run the diagnose step to regenerate it." % (path, exc))


def block_var_names(block):
    """The names of the variables a block solves."""
    return [v["name"] for v in block.get("variables", [])]


def get_system_type(block):
    """Extract the system-type from a block's nested 'systems' structure.

    Returns 'unknown' when the block carries no system node (e.g. a plain
    explicitly-solved assignment)."""
    try:
        return block["systems"]["tree"]["system"]["system-type"]
    except (KeyError, TypeError):
        try:
            return block["systems"]["super-type"]
        except (KeyError, TypeError):
            return "unknown"


def find_solver_systems(obj, results=None):
    """Recursively collect every solver-system node — one carrying a Jacobian or a
    torn-size — anywhere under ``obj``. Returns normalized dicts in document order,
    so callers can read the fields they need without re-walking the tree."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        if "system-type" in obj and ("Jacobian" in obj or "torn-size" in obj):
            results.append({
                "system-id": obj.get("system-id"),
                "system-type": obj.get("system-type"),
                "variability": obj.get("variability"),
                "value-domain": obj.get("value-domain"),
                "Jacobian": obj.get("Jacobian"),
                "torn-size": obj.get("torn-size"),
                "variables": obj.get("variables", []),
            })
        for v in obj.values():
            find_solver_systems(v, results)
    elif isinstance(obj, list):
        for item in obj:
            find_solver_systems(item, results)
    return results


def classify_jacobian(jac_value):
    """Classify a Jacobian field value.

    ``None`` means the solver builds the Jacobian numerically (finite differences);
    a string names the analytic form. The explicit "nonlinear" case is checked
    BEFORE "linear" on purpose: a substring test would match "linear" inside
    "nonlinear" and mislabel a nonlinear Jacobian as linear."""
    if jac_value is None:
        return "numeric"
    if jac_value == "nonlinear":
        return "analytic-nonlinear"
    if jac_value in ("linear", "linear variable"):
        return "analytic-linear"
    return "analytic (%s)" % jac_value


def is_numeric_jacobian(jac_value):
    """A Jacobian is numeric (finite-difference) exactly when the field is absent."""
    return jac_value is None


def nontrivial_incidences(equation):
    """[(variable, solvability), ...] for the equation's incidences whose
    solvability is anything other than the trivial 'solvable'."""
    return [(i.get("variable"), i.get("solvability"))
            for i in equation.get("incidences", [])
            if i.get("solvability", "solvable") != "solvable"]


_HEADER_RE = re.compile(r"\s*#define\s+(\w+)\s+(0[xX][0-9A-Fa-f]+|\d+)\s*(?:/\*\s*(.*?)\s*\*/)?")


def parse_header(header_path):
    """Parse the generated header's ``#define NAME value [/* comment */]`` lines.

    Returns ``{name: (int_value, comment)}`` (comment is "" when absent)."""
    defines = {}
    with open(header_path, encoding="utf-8") as fh:
        for line in fh:
            m = _HEADER_RE.match(line)
            if m:
                v = m.group(2)
                num = int(v, 16) if v[:2].lower() == "0x" else int(v, 10)
                defines[m.group(1)] = (num, m.group(3) or "")
    return defines


# Pattern -> (regex, cast) for the runtime stats we surface from a res.log.
_RESLOG_PATTERNS = {
    "integration_time": (r"Integration took ([\d.]+) seconds", float),
    "init_time": (r"Initialization took ([\d.]+) seconds", float),
    "function_evals": (r"function evaluations:\s*(\d+)", int),
    "events": (r"Total number of events:\s*(\d+)", int),
    "step_events": (r"step events.*?:\s*(\d+)", int),
    "homotopy_steps": (r"Homotopy initialization finished in (\d+) steps", int),
}


def parse_reslog(reslog_path):
    """Parse runtime statistics from a simulation res.log into a flat dict.

    Only keys actually present in the log appear in the result.

    errors='replace': the simulator's console output may be locale-encoded, and
    a stray byte must not abort the whole report."""
    with open(reslog_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    stats = {}
    for key, (pattern, cast) in _RESLOG_PATTERNS.items():
        m = re.search(pattern, text)
        if m:
            stats[key] = cast(m.group(1))
    return stats
