#!/usr/bin/env python3
"""
Post-simulation sanity check for a Modelica .mat result file.

A model can compile, validate, and simulate with *zero* errors and still be
physically wrong — a mis-biased circuit whose output never moves, a controller
stuck at a saturation limit, a state that quietly went NaN partway through.
None of that shows up as a tool error. This script scans the result trajectories
for the generic red flags that usually mean "the model ran but the answer is
suspect", so the agent can flag them instead of reporting a silent success.

Checks per variable (over the settled tail of the run by default):
  * NaN / Inf anywhere in the trajectory
  * variable is effectively CONSTANT (never moves) when you might expect it to
  * variable is PINNED at a flat value for the whole tail (railing / saturation)
  * an output-like signal has NEAR-ZERO activity (peak-to-peak ~ 0)

This is heuristic and deliberately conservative: it reports *candidates* to look
at, not verdicts. Use it as a prompt to inspect operating points, not as a gate.

Usage:
    python check_sanity.py <mat_file>
    python check_sanity.py <mat_file> --vars Vout Q2.c.v --settle-frac 0.5
    python check_sanity.py <mat_file> --json
"""

import argparse
import os
import sys

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
    from matresult import is_internal as _is_internal
except ImportError:
    _py = "python" if sys.platform == "win32" else "python3"
    print("ERROR: DyMat and numpy are required. Provision them with:\n"
          "  %s \"%s/bootstrap_env.py\""
          % (_py, os.path.dirname(os.path.abspath(__file__))), file=sys.stderr)
    sys.exit(1)

import blockdebug as bd  # stdlib-only; used here for the UTF-8 console helper


# Variable-name fragments that suggest "this is an interesting signal that
# should normally do something" (used only to raise the priority of a finding).
_OUTPUTISH = ("out", "y", ".v", ".i", "speed", "torque", "force", "pos", "level",
              "temperature", "pressure", "current", "voltage")


def analyze(mat_path, only_vars=None, settle_frac=0.4, flat_tol=1e-9,
            rel_tol=1e-6, settle_ratio=0.02):
    d = DyMat.DyMatFile(mat_path)
    available = set(d.names())
    names = only_vars if only_vars else [n for n in d.names() if not _is_internal(n)]
    # Requested-but-absent names are reported so a typo or unstored variable isn't
    # silently skipped (only meaningful when the caller restricted with --vars).
    missing = [n for n in only_vars if n not in available] if only_vars else []

    findings = {"nan_inf": [], "constant": [], "settled": []}
    n_checked = 0

    for name in names:
        if name not in d.names():
            continue
        try:
            y = np.asarray(d.data(name), dtype=float)
        except Exception:
            continue
        if y.size < 3:
            continue
        n_checked += 1

        if not np.all(np.isfinite(y)):
            first = int(np.argmax(~np.isfinite(y)))
            findings["nan_inf"].append({"var": name, "first_index": first})
            continue

        # clamp so the tail keeps at least the last sample even for tiny fractions
        tail = y[min(int(len(y) * (1.0 - settle_frac)), len(y) - 1):]
        full_pp = float(np.max(y) - np.min(y))
        tail_pp = float(np.max(tail) - np.min(tail))
        scale = max(abs(float(np.mean(y))), 1.0)
        outputish = any(frag in name.lower() for frag in _OUTPUTISH)

        # whole-run constant: the variable never moved at all
        if full_pp <= max(flat_tol, rel_tol * scale):
            findings["constant"].append({"var": name, "value": float(y[0]),
                                         "outputish": outputish})
            continue

        # settled/flatlined: it swung during the transient, then went nearly flat
        # (tail activity < settle_ratio of the full range). Often a steady state,
        # but for an actively driven node it can mean saturation or mis-bias.
        if full_pp > max(flat_tol, rel_tol * scale) and tail_pp < settle_ratio * full_pp:
            findings["settled"].append({"var": name, "value": float(tail[-1]),
                                        "full_pp": full_pp, "tail_pp": tail_pp,
                                        "outputish": outputish})

    return d, n_checked, findings, missing


def _settle_frac(text):
    """argparse type for --settle-frac: a fraction in (0, 1] (0 would leave an
    empty tail slice and crash the tail statistics)."""
    val = float(text)
    if not 0.0 < val <= 1.0:
        raise argparse.ArgumentTypeError("must be in (0, 1], got %s" % text)
    return val


def main():
    ap = argparse.ArgumentParser(description="Post-simulation sanity check on a .mat result")
    ap.add_argument("mat_file", help="Path to simulation .mat file")
    ap.add_argument("--vars", nargs="*", help="Restrict to these variables")
    ap.add_argument("--settle-frac", type=_settle_frac, default=0.4,
                    help="Fraction of the run (from the end) treated as 'settled', in (0, 1] (default 0.4)")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()
    bd.enable_utf8_console()

    if not os.path.isfile(args.mat_file):
        print("ERROR: .mat file not found: %s" % args.mat_file, file=sys.stderr)
        return 2

    _, n_checked, f, missing = analyze(args.mat_file, args.vars, args.settle_frac)

    total = sum(len(v) for v in f.values())

    if args.json:
        print(json.dumps({"checked": n_checked, "flags": total,
                          "missing": missing, "findings": f}, indent=2))
        return 1 if (total or missing) else 0

    print("Sanity check: %d variables scanned." % n_checked)
    if missing:
        print("\n  ⚠ %d requested variable(s) not found in the result "
              "(typo, or not stored — check names with plot_mat.py --list):" % len(missing))
        for name in missing:
            print("      %s" % name)
    if not total:
        if not missing:
            print("  OK — no NaN/Inf, no unexpectedly constant or flatlined signals.")
        return 1 if missing else 0

    if f["nan_inf"]:
        print("\n  ⚠ NaN/Inf (simulation diverged):")
        for x in f["nan_inf"]:
            print("      %-40s first non-finite at sample %d" % (x["var"], x["first_index"]))
    if f["constant"]:
        print("\n  ⚠ Variables that never move (dead node / not driven / structural issue):")
        for x in f["constant"][:25]:
            star = " *" if x["outputish"] else ""
            print("      %-40s constant at %.4g%s" % (x["var"], x["value"], star))
        if len(f["constant"]) > 25:
            print("      ... and %d more" % (len(f["constant"]) - 25))
    if f["settled"]:
        # Surface output-like settled nodes first — those are the suspicious ones.
        f["settled"].sort(key=lambda x: (not x["outputish"], -x["full_pp"]))
        print("\n  ⚠ Signals that swung then flatlined (steady state if expected; "
              "saturation / mis-bias if you expected continued activity):")
        for x in f["settled"][:25]:
            star = " *" if x["outputish"] else ""
            print("      %-40s -> %.4g  (transient pp=%.3g, tail pp=%.3g)%s"
                  % (x["var"], x["value"], x["full_pp"], x["tail_pp"], star))
        if len(f["settled"]) > 25:
            print("      ... and %d more" % (len(f["settled"]) - 25))

    print("\n  Lines marked * are output-like nodes. These are heuristics — inspect the "
          "flagged variables' operating points before trusting the run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
