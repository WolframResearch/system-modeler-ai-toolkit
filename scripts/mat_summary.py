#!/usr/bin/env python3
"""
Compact numeric summary of variables in a Modelica .mat result.

The inner loop of simulation work is "run the model, then read a few numbers off
the result" (settled values, swing, ranges). Doing that with ad-hoc DyMat
one-liners is verbose; this gives one terse line per variable instead.

For each variable: min, max, mean, peak-to-peak, and the final (settled) value.
With --at T it also reports the value at time T (each variable indexed on its own
abscissa, so constants/parameters work too).

Usage:
    python mat_summary.py <mat_file> [var1 var2 ...]
    python mat_summary.py <mat_file> Vout Q4L.c.v --at 0.09
    python mat_summary.py <mat_file> --list          # just list variable names
    python mat_summary.py <mat_file> --json Vout BP

With no variables given, summarizes the model's state variables (those with a
der(x)); pass names (or --all) for others.
"""

import argparse
import os
import re
import sys

# Variable names printed below may contain non-ASCII; force UTF-8 so output
# doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _env import reexec_under_managed_venv
    reexec_under_managed_venv(["DyMat", "numpy"])
except Exception:
    pass

import json

try:
    import DyMat
    import numpy as np
    from matresult import series, value_at, state_names, is_internal
except ImportError:
    _py = "python" if sys.platform == "win32" else "python3"
    print("ERROR: DyMat and numpy are required. Provision them with:\n"
          "  %s \"%s/bootstrap_env.py\"" % (_py, os.path.dirname(os.path.abspath(__file__))),
          file=sys.stderr)
    sys.exit(1)


def summarize(d, name, tval=None):
    arr = series(d, name)
    if arr.size == 0:
        return {"var": name, "empty": True}
    s = {"var": name, "min": float(np.nanmin(arr)), "max": float(np.nanmax(arr)),
         "mean": float(np.nanmean(arr)), "pp": float(np.nanmax(arr) - np.nanmin(arr)),
         "final": float(arr[-1])}
    if not np.all(np.isfinite(arr)):
        s["nonfinite"] = True
    if tval is not None:
        s["at"] = value_at(d, name, tval)
    return s


def main():
    ap = argparse.ArgumentParser(description="Compact variable summary of a Modelica .mat")
    ap.add_argument("mat_file")
    ap.add_argument("variables", nargs="*", help="Variables to summarize (default: the states)")
    ap.add_argument("--at", type=float, help="Also report the value at this time")
    ap.add_argument("--all", action="store_true", help="Summarize all non-internal variables")
    ap.add_argument("--list", action="store_true", help="List variable names and exit")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    args = ap.parse_args()

    if not os.path.isfile(args.mat_file):
        print("ERROR: .mat not found: %s" % args.mat_file, file=sys.stderr)
        return 2

    d = DyMat.DyMatFile(args.mat_file)
    names = d.names()

    if args.list:
        for n in sorted(names):
            print(n)
        return 0

    if args.variables:
        targets = [v for v in args.variables if v in names]
        missing = [v for v in args.variables if v not in names]
    elif args.all:
        targets = sorted(n for n in names if not (n.startswith("$") or n.startswith("der(")))
        missing = []
    else:  # default: state variables (those with a der(x))
        targets = state_names(d)
        missing = []
        if not targets:
            targets = sorted(n for n in names if not is_internal(n))[:20]

    rows = [summarize(d, v, args.at) for v in targets]

    if args.json:
        print(json.dumps({"file": args.mat_file, "missing": missing, "vars": rows}, indent=2))
        return 1 if missing else 0

    if not rows:
        print("(no variables matched)")
        return 1
    hdr = "%-28s %12s %12s %12s %12s %12s" % ("variable", "min", "max", "mean", "pp", "final")
    if args.at is not None:
        hdr += " %12s" % ("@%.4g" % args.at)
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if r.get("empty"):
            print("%-28s %s" % (r["var"], "(no samples in .mat)"))
            continue
        line = "%-28s %12.5g %12.5g %12.5g %12.5g %12.5g" % (
            r["var"], r["min"], r["max"], r["mean"], r["pp"], r["final"])
        if args.at is not None:
            at = r.get("at")
            line += " %12.5g" % at if at is not None else " %12s" % "-"
        if r.get("nonfinite"):
            line += "  <-- NaN/Inf"
        print(line)
    if missing:
        print("(not in .mat: %s)" % ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
