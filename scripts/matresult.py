"""
Shared DyMat/numpy helpers for the scripts that read simulation ``.mat`` results
(``mat_summary.py``, ``op_report.py``, ``check_sanity.py``, ``plot_mat.py``).

Import this only AFTER the managed-venv bootstrap has run, because it imports
DyMat and numpy at module load. It centralizes loading, series extraction, the
"value at time T" sampling, the internal-name filter, and state detection that
those scripts would otherwise each re-implement.
"""

import DyMat
import numpy as np


def load(mat_path):
    """Open a Modelica result .mat with DyMat."""
    return DyMat.DyMatFile(mat_path)


def is_internal(name):
    """True for solver/tool bookkeeping variables that should not be reported
    ($-prefixed, derivative aliases, or dotted-private ``._`` names)."""
    return name.startswith("$") or name.startswith("der(") or "._" in name


def series(d, name):
    """The variable's trajectory as a float ndarray."""
    return np.asarray(d.data(name), dtype=float)


def value_at(d, name, tval):
    """Value of ``name`` at time ``tval`` using the variable's OWN abscissa, so
    constants (stored against a length-2 time vector) sample correctly too.
    Returns None if the variable is absent from the result."""
    if name not in d.names():
        return None
    arr = series(d, name)
    if arr.size == 1:
        return float(arr[0])
    ab = np.asarray(d.abscissa(name)[0])
    j = min(int(np.argmin(np.abs(ab - tval))), arr.size - 1)
    return float(arr[j])


def state_names(d):
    """The model's continuous states: every ``x`` for which ``der(x)`` also
    appears in the result (excluding internal bookkeeping names)."""
    names = set(d.names())
    return sorted(x for x in names
                  if ("der(%s)" % x) in names and not is_internal(x))
