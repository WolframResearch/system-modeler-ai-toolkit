"""
Plot variables from a Modelica simulation .mat file.

Reads the .mat with DyMat and plots one time-series subplot per variable in a
single combined figure (or one file per variable with --separate).

Usage:
    python plot_mat.py <mat_file> <var1> [var2 ...] [options]

Options:
    --outdir DIR     Output directory for the PNG (default: same as mat_file)
    --name NAME      Base name for the output file (default: the .mat stem)
    --title STR      Figure title (default: the .mat stem)
    --ncols N        Columns in the combined grid (default: 2)
    --separate       Write one PNG per variable instead of one combined figure
    --list           Print the .mat's variable names and exit (no plot)

Examples:
    python plot_mat.py results/Model.mat tank1.h pump.mdot PID.y
    python plot_mat.py results/Model.mat tank1.h --outdir plots/ --title "Tank level"
    python plot_mat.py results/Model.mat --list
"""

import os
import sys
import argparse

# Variable names printed below (--list) may contain non-ASCII; force UTF-8 so
# output doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Ensure DyMat + matplotlib are available; if not, re-exec under a managed venv.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _env import reexec_under_managed_venv
    reexec_under_managed_venv(["DyMat", "matplotlib"])
except Exception:
    pass  # bootstrap helper unavailable; fall back to the plain import below

try:
    import DyMat
except ImportError:
    _py = "python" if sys.platform == "win32" else "python3"
    print("ERROR: DyMat is required. Provision it into the managed venv with:\n"
          "  %s \"%s/bootstrap_env.py\"\n"
          "(avoid a bare system pip — it fails on PEP 668 interpreters)."
          % (_py, os.path.dirname(os.path.abspath(__file__))), file=sys.stderr)
    sys.exit(1)


def load_mat(mat_path):
    """Load a .mat file with DyMat. Returns the DyMatFile object."""
    return DyMat.DyMatFile(mat_path)


def get_series(d, vname):
    """Return (time, values) for a variable, or (None, None) if absent."""
    if vname not in d.names():
        return None, None
    return d.abscissa(vname)[0], d.data(vname)


# Path separators plus the remaining Windows-illegal filename characters; all of
# them are legal inside Modelica quoted identifiers (e.g. 'v"1"' or 'a|b').
_UNSAFE_FILENAME_CHARS = './\\<>:"|?*'


def sanitize_filename(vname):
    """Make a variable name safe to use as a filename on any platform."""
    return "".join("_" if c in _UNSAFE_FILENAME_CHARS else c for c in vname)


def plot_separate(d, variables, name, title, outdir):
    """One PNG per variable. Returns list of written paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []
    used = set()
    for vname in variables:
        t, y = get_series(d, vname)
        if t is None:
            print(f"WARN: {vname} not found in .mat", file=sys.stderr)
            continue
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(t, y, "b-", linewidth=1.5)
        ax.set_xlabel("Time [s]")
        ax.set_ylabel(vname)
        ax.set_title(f"{title} — {vname}")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        base = f"{name}_{sanitize_filename(vname)}"
        # de-collide: two variables may sanitize to the same name
        stem, n = base, 2
        while stem in used:
            stem = f"{base}_{n}"
            n += 1
        used.add(stem)
        out_path = os.path.join(outdir, f"{stem}.png")
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        paths.append(out_path)
    return paths


def plot_combined(d, variables, name, title, outdir, ncols):
    """Single combined figure, one subplot per found variable. Returns path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    found = []
    for vname in variables:
        t, y = get_series(d, vname)
        if t is None:
            print(f"WARN: {vname} not found in .mat", file=sys.stderr)
            continue
        found.append((vname, t, y))

    if not found:
        return None

    n = len(found)
    ncols = max(1, min(ncols, n))
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 3.2 * nrows), squeeze=False)
    fig.suptitle(title, fontsize=13, y=1.005)

    for idx, (vname, t, y) in enumerate(found):
        ax = axes[idx // ncols][idx % ncols]
        ax.plot(t, y, "b-", linewidth=1.3)
        ax.set_title(vname, fontsize=9)
        ax.set_xlabel("Time [s]", fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

    # blank any unused cells in the grid
    for idx in range(n, nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")

    plt.tight_layout()
    out_path = os.path.join(outdir, f"{name}_plot.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Plot variables from a Modelica .mat file")
    ap.add_argument("mat_file", help="Path to simulation .mat file")
    ap.add_argument("variables", nargs="*", help="Variable names to plot")
    ap.add_argument("--outdir", help="Output directory (default: same as mat_file)")
    ap.add_argument("--name", help="Base name for the output PNG (default: .mat stem)")
    ap.add_argument("--title", help="Figure title (default: .mat stem)")
    ap.add_argument("--ncols", type=int, default=2, help="Columns in the combined grid (default: 2)")
    ap.add_argument("--separate", action="store_true", help="One PNG per variable instead of combined")
    ap.add_argument("--list", action="store_true", help="Print the .mat's variable names and exit")
    args = ap.parse_args()

    if not os.path.isfile(args.mat_file):
        print(f"ERROR: .mat file not found: {args.mat_file}", file=sys.stderr)
        return 2

    d = load_mat(args.mat_file)

    if args.list:
        for nm in sorted(d.names()):
            print(nm)
        print(f"\n{len(d.names())} variables", file=sys.stderr)
        return 0

    if not args.variables:
        print("ERROR: give at least one variable to plot (or use --list to see what's available).",
              file=sys.stderr)
        return 2

    stem = os.path.splitext(os.path.basename(args.mat_file))[0]
    # --name becomes part of the output filename, so sanitize it the same way as
    # variable names: a value with path separators or other unsafe chars must not
    # escape outdir or produce an invalid filename.
    name = sanitize_filename(args.name) if args.name else stem
    title = args.title or stem
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.dirname(os.path.abspath(args.mat_file))
    os.makedirs(outdir, exist_ok=True)

    print(f"Loading .mat: {args.mat_file}  ({len(d.names())} variables)")

    # A requested variable absent from the .mat is a non-zero exit even if others
    # plotted, so a caller doesn't read a typo'd/unstored name as a full success.
    missing = [v for v in args.variables if v not in d.names()]

    if args.separate:
        paths = plot_separate(d, args.variables, name, title, outdir)
        for p in paths:
            print(f"  Plot: {p}")
        if not paths:
            return 1
        return 1 if missing else 0
    else:
        path = plot_combined(d, args.variables, name, title, outdir, args.ncols)
        if not path:
            print("ERROR: none of the requested variables were found in the .mat.", file=sys.stderr)
            return 1
        print(f"Plot: {path}")
        return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
