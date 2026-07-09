"""Read parameter metadata from a WSM ``.sim`` file (the XML init file written next to the
result ``.mat`` when a model is built/simulated).

The ``.sim`` is the authoritative, *flattened* view of what can be controlled: every parameter
and start value appears as ``<variable name="..." initType="..." value="..." .../>``. A
parameter with ``initType="exact"`` is runtime-tunable (its value can be changed and applied);
other init types are computed, and constant-folded structural parameters are absent entirely.
The kernel is not needed here — this is a plain XML read.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET


def sim_path_for(mat_path: str) -> str | None:
    """The ``.sim`` file that pairs with ``mat_path`` (same stem), or None if absent."""
    cand = os.path.splitext(mat_path)[0] + ".sim"
    return cand if os.path.isfile(cand) else None


def read_sim(sim_path: str) -> dict:
    """Parse a ``.sim`` file into ``{name: {'initType', 'value', 'variability'}}``.

    Raises on a missing or malformed file so the caller notices rather than silently treating
    the model as having no controllable variables."""
    root = ET.parse(sim_path).getroot()
    out = {}
    for v in root.iter("variable"):
        name = v.get("name")
        if not name:
            continue
        out[name] = {
            "initType": v.get("initType") or "",
            "value": v.get("value"),
            "variability": v.get("variability") or "",
        }
    return out


def names(sim: dict) -> set:
    """All variable/parameter names present in the parsed ``.sim``."""
    return set(sim)


def tunable_names(sim: dict) -> set:
    """Names whose value the runtime will honor (``initType == "exact"``)."""
    return {n for n, m in sim.items() if m.get("initType") == "exact"}
