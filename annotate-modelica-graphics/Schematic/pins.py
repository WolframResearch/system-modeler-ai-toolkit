"""Connector pin positions of component classes, in the class's +-100 icon frame.

A pin is ``(x, y, kind)``: the centre of the connector's icon placement, and a one-letter
kind — ``i``/``o`` for a causal signal input/output; ``e``, ``t`` or ``f`` for an electrical,
thermal or fluid connector; ``r``, ``l`` or ``m`` for a rotational, translational or other
mechanical one; ``""`` otherwise. Standard-library
classes are looked up in ``msl_pins.json`` (read off the Modelica Standard Library 4.1.0
source); classes defined in the model file are read from their own declarations.
"""

from __future__ import annotations

import json
import math
import os
import re

from .parser import import_candidates

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_PAIR = r"\{\s*(%s)\s*,\s*(%s)\s*\}" % (_NUM, _NUM)
_EXTENT_RE = re.compile(r"\bextent\s*=\s*\{\s*%s\s*,\s*%s\s*\}" % (_PAIR, _PAIR))
_ORIGIN_RE = re.compile(r"\borigin\s*=\s*" + _PAIR)
_ROTATION_RE = re.compile(r"\brotation\s*=\s*(%s)" % _NUM)

_table: dict | None = None


def _call_body(text: str, name: str) -> str | None:
    """Argument text of the first ``name(...)`` call that is not part of a longer word."""
    for m in re.finditer(r"(?<![\w.])%s\s*\(" % name, text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return text[m.end():i]
            i += 1
    return None


def placement_point(decl: str) -> tuple | None:
    """Icon-frame centre of a connector from its declaration's ``Placement`` annotation.

    The icon placement is ``iconTransformation`` when present, else ``transformation``.
    """
    placement = _call_body(decl, "Placement")
    if placement is None:
        return None
    tr = _call_body(placement, "iconTransformation")
    if tr is None:
        tr = _call_body(placement, "transformation")
    if tr is None:
        return None
    ext = _EXTENT_RE.search(tr)
    if not ext:
        return None
    x1, y1, x2, y2 = (float(v) for v in ext.groups())
    org = _ORIGIN_RE.search(tr)
    ox, oy = (float(v) for v in org.groups()) if org else (0.0, 0.0)
    rot = _ROTATION_RE.search(tr)
    t = math.radians(float(rot.group(1))) if rot else 0.0
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    return (round(ox + cx * math.cos(t) - cy * math.sin(t)),
            round(oy + cx * math.sin(t) + cy * math.cos(t)))


def kind_of(type_name: str) -> str:
    """Pin kind from a connector's type name."""
    leaf = type_name.split(".")[-1]
    if leaf.endswith("Input"):
        return "i"
    if leaf.endswith("Output"):
        return "o"
    if ".HeatTransfer." in type_name or leaf.startswith(("HeatPort", "ThermalPort")):
        return "t"
    if ".Electrical." in type_name or leaf in ("Pin", "PositivePin", "NegativePin"):
        return "e"
    if ".Mechanics." in type_name or leaf.startswith(("Flange", "Frame", "Support")):
        return "r" if ".Rotational." in type_name else "l" if ".Translational." in type_name else "m"
    if ".Fluid." in type_name or "FluidPort" in leaf:
        return "f"
    return ""


def _msl() -> dict:
    global _table
    if _table is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "msl_pins.json")
        with open(path, "r", encoding="utf-8") as f:
            _table = json.load(f)
    return _table


def lookup(type_name: str) -> dict | None:
    """``{connector: (x, y, kind)}`` for a standard-library class, or None.

    A name that is not a full ``Modelica.`` path (an imported short name) is matched by its
    trailing segments; when several classes share them, only the pins they all agree on
    are returned.
    """
    table = _msl()
    if type_name in table:
        return {k: tuple(v) for k, v in table[type_name].items()}
    if type_name.startswith("Modelica."):
        return None
    suffix = "." + type_name
    hits = [v for k, v in table.items() if k.endswith(suffix)]
    if not hits:
        return None
    common = {}
    for port, pin in hits[0].items():
        if all(h.get(port) == pin for h in hits[1:]):
            common[port] = tuple(pin)
    return common or None


def type_of(inst) -> str:
    """An instance's class as a full path where ``qualify`` could resolve it."""
    return getattr(inst, "qualified_type", "") or inst.type_name


def qualify(classes: list) -> list:
    """Resolve each instance's type through the imports and short class definitions in
    scope, and return ``(class, instance, type)`` for each one whose pins are unknown."""
    by_name = {c.name: c for c in classes}
    unknown = []
    for cls in classes:
        for inst in cls.instances:
            full = _qualified(cls, classes, by_name, inst.type_name, 0)
            inst.qualified_type = full
            if full.split(".")[-1] not in by_name and lookup(full) is None:
                unknown.append((cls, inst, full))
    return unknown


def _qualified(cls, classes, by_name, name: str, depth: int) -> str:
    local = by_name.get(name.split(".")[-1])
    if local is not None and "." not in name:
        if local.is_short and local.short_base and depth < 8:
            return _qualified(local, classes, by_name, local.short_base, depth + 1)
        return name
    if name.startswith("Modelica."):
        return name
    known = [c for c in import_candidates(cls, classes, name) if c in _msl()]
    return known[0] if known else name


def side(px: float, py: float) -> str | None:
    """Icon edge ('L'/'R'/'T'/'B') a pin at ``(px, py)`` sits on, or None at the centre."""
    if px == 0 and py == 0:
        return None
    if abs(px) >= abs(py):
        return "L" if px < 0 else "R"
    return "B" if py < 0 else "T"


_EDGE_PT = {"L": (-100, 0), "R": (100, 0), "T": (0, 100), "B": (0, -100)}


def _guess(type_name: str, port: str) -> tuple:
    """Pin of a class found in no table, guessed from the connector name."""
    leaf = type_name.split(".")[-1].lower()
    p = port.lower()
    if "ground" in leaf:
        return 0, 100, ""
    if p in ("p", "pin_p", "plus", "anode", "n", "pin_n", "minus", "cathode"):
        x = -100 if p in ("p", "pin_p", "plus", "anode") else 100
        return x, 0, "e"
    if p in ("port_a", "inlet", "fluidport_a"):
        return -100, 0, ""
    if p in ("port_b", "outlet", "fluidport_b"):
        return 100, 0, ""
    if p == "flange_a":
        return -100, 0, "m"
    if p in ("flange_b", "flange"):
        return 100, 0, "m"
    if p == "support":
        return 0, -100, "m"
    if p.startswith("ports"):
        return 0, -100, ""
    if p in ("heatport", "port_h"):
        return 0, 100, "t"
    if p == "y" or p.startswith("out"):
        return 100, 0, "o" if p == "y" else ""
    if p.startswith("u") or p.startswith("in"):
        return -100, 0, "i" if re.fullmatch(r"u\d*", p) else ""
    edge = {"b": "L", "base": "L", "c": "T", "collector": "T", "e": "B", "emitter": "B",
            "vpos": "T", "vcc": "T", "vdd": "T", "vp": "T", "vsup": "T", "supply": "T",
            "vneg": "B", "vee": "B", "vss": "B", "vn": "B"}.get(p, "L")
    return _EDGE_PT[edge] + ("",)


def resolve(type_name: str, port: str, local: dict | None = None) -> tuple:
    """``(x, y, kind)`` of one connector of an instance's class.

    ``local`` maps the leaf name of each class defined in the model file to its pins.
    """
    port = port.split("[")[0].split(".")[0]
    own = (local or {}).get(type_name.split(".")[-1])
    if own and port in own:
        return own[port]
    table = lookup(type_name)
    if table and port in table:
        return table[port]
    return _guess(type_name, port)
