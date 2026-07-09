"""Propose a starting figures spec from a list of simulation-result variable names.

A starting point only — the caller refines it (drop noise, split plots by unit, set legends).
Without unit info, all chosen variables share one y-axis.
"""

from __future__ import annotations

import re

_NOISE = re.compile(
    r"(^time$|^\$|\.start$|^der\(|^initial|^terminal|^sample|"
    r"\.fixed$|\.nominal$|\.min$|\.max$|\.unit$)")


def suggest_spec(variables: list, max_curves: int = 8, title: str = "Simulation results",
                 protected: set | None = None) -> tuple:
    """Return ``(spec, notes)`` — a figures-spec dict and a list of remarks (e.g. truncation).

    ``protected`` names (from the ``.sim`` file) are dropped: a stored figure that
    references a protected variable renders blank in System Modeler.
    """
    protected = protected or set()
    dropped = sorted(v for v in variables if v in protected and not _NOISE.search(v))
    cands = sorted((v for v in variables if not _NOISE.search(v) and v not in protected),
                   key=lambda v: (v.count("."), len(v), v))
    notes = []
    if dropped:
        notes.append("excluded %d protected variable(s) (not plottable in a stored figure): %s"
                     % (len(dropped), ", ".join(dropped)))
    if not cands:
        return {"figures": []}, notes + ["no plottable variables found after filtering"]
    if len(cands) > max_curves:
        notes.append("showing first %d of %d candidate variables; refine the spec to pick the "
                     "ones you care about" % (max_curves, len(cands)))
    curves = [{"x": "time", "y": v, "legend": v} for v in cands[:max_curves]]
    spec = {"figures": [{
        "title": title, "identifier": "results", "preferred": True,
        "plots": [{"title": title, "x": {"label": "time"}, "curves": curves}],
    }]}
    return spec, notes
