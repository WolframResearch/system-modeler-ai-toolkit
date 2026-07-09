#!/usr/bin/env python3
"""
Operating-point / steady-state report for ANY Modelica simulation .mat.

Domain-neutral — works for thermal, hydraulic, mechanical, electrical, control,
... models. It answers "did the model reach a steady operating point, and what is
it?", which is a generic question whenever you simulate to settle a system:

  * STEADY STATE: for every state x (detected via der(x) in the result), the value
    and derivative at the chosen time, plus a settling ratio |der_now| / peak|der|.
    States whose derivative has NOT decayed are flagged as still drifting — i.e.
    the run hasn't reached equilibrium (or the system oscillates / is unstable).
  * VALUES: the settled values of the states (or whatever you pass to --vars), so
    the operating point itself is in front of you (settled temperatures, pressures,
    voltages, positions, ...).
  * DOMAIN ADD-ONS that fire only when applicable. Currently: bipolar-transistor
    region (ACTIVE / SATURATED / CUTOFF) for any device exposing X.Vbe / X.Vbc.

By default it evaluates the last sample. Use --at T to pick another time.

Usage:
    python op_report.py <mat_file>
    python op_report.py <mat_file> --at 50           # thermal model settling at t=50
    python op_report.py <mat_file> --vars tank.T pump.dp valve.opening
    python op_report.py <mat_file> --settle-tol 0.05 # looser "settled" threshold
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _env import reexec_under_managed_venv
    reexec_under_managed_venv(["DyMat", "numpy"])
except Exception:
    pass

try:
    import DyMat
    import numpy as np
    from matresult import series, value_at, state_names
except ImportError:
    _py = "python" if sys.platform == "win32" else "python3"
    print("ERROR: DyMat and numpy are required. Provision them with:\n"
          "  %s \"%s/bootstrap_env.py\"" % (_py, os.path.dirname(os.path.abspath(__file__))),
          file=sys.stderr)
    sys.exit(1)

import blockdebug as bd  # stdlib-only; used here for the UTF-8 console helper


# --------------------------------------------------------------------------
# Domain add-ons: detectors that only fire when their variables are present.
# Each returns a list of report lines (or [] if not applicable).
# --------------------------------------------------------------------------
def bjt_report(d, names, tval, von):
    bjts = sorted({m.group(1) for n in names
                   for m in [re.match(r"(.+)\.Vbe$", n)] if m and (m.group(1) + ".Vbc") in names})
    if not bjts:
        return []
    def region(vbe, vbc):
        on_be, on_bc = vbe > von, vbc > von
        if on_be and not on_bc: return "ACTIVE"
        if on_be and on_bc:     return "SATURATED"
        if not on_be and not on_bc: return "CUTOFF"
        return "REVERSE"
    lines = ["Bipolar transistors (region from Vbe/Vbc):",
             "  %-10s %8s %8s %8s %11s   %s" % ("device", "Vbe", "Vbc", "Vce", "Ic", "region"),
             "  " + "-" * 60]
    n_bad = 0
    for q in bjts:
        vbe = value_at(d, q + ".Vbe", tval); vbc = value_at(d, q + ".Vbc", tval)
        vc = value_at(d, q + ".c.v", tval);  ve = value_at(d, q + ".e.v", tval)
        ic = value_at(d, q + ".c.i", tval)
        vce = (vc - ve) if (vc is not None and ve is not None) else float("nan")
        reg = region(vbe, vbc)
        if reg != "ACTIVE": n_bad += 1
        lines.append("  %-10s %8.4f %8.4f %8.4f %11s   %s%s"
                     % (q, vbe, vbc, vce, ("%.3g" % ic) if ic is not None else "-", reg,
                        "  <--" if reg in ("SATURATED", "CUTOFF") else ""))
    if n_bad:
        lines.append("  NOTE: %d of %d transistors are NOT active — likely a bias problem."
                     % (n_bad, len(bjts)))
    return lines


DOMAIN_DETECTORS = [bjt_report]


def _nonneg_int(text):
    """argparse type: a non-negative int (a negative --top would slice from the end)."""
    val = int(text)
    if val < 0:
        raise argparse.ArgumentTypeError("must be >= 0, got %s" % text)
    return val


def main():
    ap = argparse.ArgumentParser(description="Operating-point / steady-state report from a .mat")
    ap.add_argument("mat_file")
    ap.add_argument("--at", type=float, help="Time to evaluate (default: last sample)")
    ap.add_argument("--vars", nargs="*", help="Variables to print at the chosen time (default: the states)")
    ap.add_argument("--settle-tol", type=float, default=0.02,
                    help="A state counts as settled if |der_now| < tol*peak|der| (default 0.02)")
    ap.add_argument("--top", type=_nonneg_int, default=10, help="How many least-settled states to list")
    ap.add_argument("--von", type=float, default=0.4, help="BJT on-voltage threshold (add-on)")
    args = ap.parse_args()
    bd.enable_utf8_console()

    if not os.path.isfile(args.mat_file):
        print("ERROR: .mat not found: %s" % args.mat_file, file=sys.stderr)
        return 2

    d = DyMat.DyMatFile(args.mat_file)
    names = set(d.names())
    any_var = next((n for n in d.names() if not n.startswith("$")), None)
    if any_var is None:
        print("(no usable variables in the result — empty or all-internal .mat)")
        return 1
    t = np.asarray(d.abscissa(any_var)[0])
    tval = t[-1] if args.at is None else t[int(np.argmin(np.abs(t - args.at)))]
    print("Operating point at t = %.6g s\n" % tval)

    # --- generic steady-state assessment over all states (x with der(x)) ------
    states = state_names(d)
    settled = []
    for x in states:
        der = series(d, "der(%s)" % x)
        peak = float(np.max(np.abs(der))) if der.size else 0.0
        # A non-finite derivative means the state diverged; treat it as maximally
        # NOT settled (inf ratio) rather than letting `NaN or 0.0` -> NaN slip past
        # the `ratio > tol` test and be reported as settled.
        dn = value_at(d, "der(%s)" % x, tval)
        der_now = abs(dn) if (dn is not None and np.isfinite(dn)) else float("inf")
        ratio = der_now / peak if peak > 0 else 0.0
        settled.append({"x": x, "val": value_at(d, x, tval),
                        "der_now": der_now, "peak": peak, "ratio": ratio})

    if states:
        not_settled = [s for s in settled if s["ratio"] > args.settle_tol and s["peak"] > 0]
        print("Steady state: %d of %d states settled (|der| < %g x peak)."
              % (len(states) - len(not_settled), len(states), args.settle_tol))
        if not_settled:
            not_settled.sort(key=lambda s: -s["ratio"])
            print("  Still changing (run may be too short, or the system oscillates / is unstable):")
            print("    %-28s %12s %12s  %6s" % ("state", "value", "d/dt", "rate%"))
            for s in not_settled[:args.top]:
                print("    %-28s %12.5g %12.5g  %5.0f%%"
                      % (s["x"], s["val"], s["der_now"], 100 * s["ratio"]))
            if len(not_settled) > args.top:
                print("    ... and %d more" % (len(not_settled) - args.top))
        print()
    else:
        print("(no state variables with der(...) found — purely algebraic result)\n")

    # --- values at the operating point ----------------------------------------
    to_print = args.vars if args.vars else states
    missing = [nm for nm in (args.vars or []) if nm not in names]
    if to_print:
        print("Values:" if args.vars else "Settled state values:")
        for nm in to_print:
            v = value_at(d, nm, tval)
            print("  %-32s = %s" % (nm, ("%.6g" % v) if v is not None else "(not in .mat)"))
        print()

    # --- optional domain add-ons ----------------------------------------------
    for detector in DOMAIN_DETECTORS:
        lines = detector(d, names, tval, args.von)
        if lines:
            print("\n".join(lines))

    # A requested --vars name absent from the result is a non-zero exit so a caller
    # doesn't read a typo'd/unstored variable as a successful lookup.
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
