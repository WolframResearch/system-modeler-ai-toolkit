#!/usr/bin/env python3
"""
Provision (or report) the managed Python environment the plotting/analysis
scripts need: DyMat, matplotlib, numpy, scipy.

The plot/analysis scripts bootstrap this automatically, so you rarely need to
run it by hand. It is useful to pre-warm the venv, or to learn which
interpreter the scripts will use.

Usage:
    python bootstrap_env.py                 # create/reuse the venv, install deps, print its python
    python bootstrap_env.py --print-python  # just print the venv python path (creating it if needed)
    python bootstrap_env.py numpy DyMat     # ensure a custom set of packages

The venv location defaults to a per-user cache dir and can be overridden with
$WSM_SKILLS_VENV.
"""

import argparse
import sys

from _env import ensure_managed_venv, venv_python, _default_venv_dir

DEFAULT_PACKAGES = ["DyMat", "matplotlib", "numpy", "scipy"]


def main():
    ap = argparse.ArgumentParser(description="Provision the managed venv for the System Modeler skills")
    ap.add_argument("packages", nargs="*", help="Module names to ensure (default: DyMat matplotlib numpy scipy)")
    ap.add_argument("--print-python", action="store_true",
                    help="Only print the path to the managed venv's python (create it if missing)")
    args = ap.parse_args()

    modules = args.packages or DEFAULT_PACKAGES

    if args.print_python:
        # Create the venv if missing but skip the (slow) install check.
        import os
        venv_dir = _default_venv_dir()
        py = venv_python(venv_dir)
        if not os.path.isfile(py):
            py = ensure_managed_venv(modules)
        print(py)
        return 0

    py = ensure_managed_venv(modules)
    print(py)
    return 0


if __name__ == "__main__":
    sys.exit(main())
