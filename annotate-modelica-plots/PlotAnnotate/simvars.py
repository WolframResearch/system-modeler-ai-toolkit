"""Read variable metadata from a WSM ``.sim`` file (the XML init file written next
to the result ``.mat`` when a model is built/simulated).

Only one fact is needed here: which result variables are **protected**. System
Modeler stores protected variables in the ``.mat`` (``StoreProtected`` defaults
to true), so they appear in ``plot_mat.py --list`` and would otherwise be
suggested as curves — but a stored ``figures`` annotation that references a
protected variable renders blank, because the figure viewer resolves curves
against the public result tree only. The ``.mat`` itself carries no protected
flag; the ``.sim`` does, as ``<variable ... protected="true" .../>``.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET


def sim_path_for(mat_path: str) -> str | None:
    """The ``.sim`` file that pairs with ``mat_path`` (same stem), or None if absent."""
    cand = os.path.splitext(mat_path)[0] + ".sim"
    return cand if os.path.isfile(cand) else None


def protected_names(sim_path: str) -> set:
    """Parse a ``.sim`` file and return the set of protected variable names.

    Returns an empty set if the file has no protected variables. Raises on a
    missing or malformed file so the caller notices rather than silently
    treating every variable as public.
    """
    root = ET.parse(sim_path).getroot()
    return {v.get("name") for v in root.iter("variable")
            if v.get("protected") == "true" and v.get("name")}
