"""Connector-aware orthogonal (Manhattan) routing of connection lines.

Each connection terminates at the actual connector *pin* anchor — the instance origin plus
the connector's offset on its icon boundary — and leaves that pin perpendicular to the edge
it sits on. The result is a line that is orthogonal end-to-end, with no diagonal stub from
an off-centre pin back to a component's origin (which is what System Modeler would otherwise
draw when a connection's endpoints are given at component centres).

Pin offsets come from two sources:
  * the model's own leaf/sub-circuit icons (transistors, OTAs, …), whose connector edges we
    generate ourselves and pass in via ``layout['type_ports']``; and
  * a small heuristic table for standard-library components (resistors, capacitors, sources,
    ground, blocks) whose icons we do not parse.

Where an endpoint genuinely cannot be resolved we fall back to a harmless zero-length stub,
exactly as before — never a diagonal.
"""

from __future__ import annotations

from . import colors
from .parser import ClassSpan, Connect

GRID = 2
BOX = 10   # half-extent of an instance Placement box (extent={{-10,-10},{10,10}})

_EDGE_PT = {"L": (-100, 0), "R": (100, 0), "T": (0, 100), "B": (0, -100)}


def _round(v: float) -> int:
    return int(round(v / GRID)) * GRID


def _lib_edge(type_name: str, port: str) -> str:
    """Heuristic icon edge ('L'/'R'/'T'/'B') for a standard-library component's connector."""
    leaf = type_name.split(".")[-1].lower()
    p = port.lower()
    if "ground" in leaf:
        return "T"                                   # ground's single pin sits on top
    if leaf in ("signalvoltage", "signalcurrent") and p in ("v", "i"):
        return "T"                                   # control input on a signal source
    if p in ("p", "pin_p", "plus", "anode"):
        return "L"                                   # electrical OnePort: + on the left
    if p in ("n", "pin_n", "minus", "cathode"):
        return "R"                                   # electrical OnePort: - on the right
    if p in ("port_a", "inlet", "fluidport_a"):
        return "L"                                   # fluid / generic inlet
    if p in ("port_b", "outlet", "fluidport_b"):
        return "R"                                   # fluid / generic outlet
    if p.startswith("ports"):
        return "B"                                   # vessel port array
    if p in ("heatport", "port_h"):
        return "T"                                   # thermal heat port
    if p == "y" or p.startswith("out"):
        return "R"                                   # block / signal output
    if p.startswith("u") or p.startswith("in"):
        return "L"                                   # block / signal input
    if p in ("b", "base"):
        return "L"
    if p in ("c", "collector"):
        return "T"
    if p in ("e", "emitter"):
        return "B"
    if p in ("vpos", "vcc", "vdd", "vp", "vsup", "supply"):
        return "T"
    if p in ("vneg", "vee", "vss", "vn"):
        return "B"
    return "L"


def _rot(px: int, py: int, rot: int) -> tuple:
    rot = rot % 360
    if rot == 90:
        return (-py, px)
    if rot == 180:
        return (-px, -py)
    if rot == 270:
        return (py, -px)
    return (px, py)


def _port_offset(type_name: str, port: str, type_ports) -> tuple:
    """Connector offset in the ±100 icon frame for one instance's port."""
    edges = type_ports.get(type_name.split(".")[-1]) if type_ports else None
    if edges and port in edges:
        return edges[port]
    return _EDGE_PT[_lib_edge(type_name, port)]


def _anchor(inst: str, port: str, layout: dict):
    """Return (point, leave-orientation) for one connect endpoint, or (None, None).

    Orientation is 'H' if the line should leave the pin horizontally (pin on a left/right
    edge), 'V' if vertically (top/bottom edge), or None when unknown.
    """
    connectors = layout.get("connectors", {})
    instances = layout.get("instances", {})
    # A class-level connector endpoint (it carries no sub-port) placed on the diagram border.
    if not port and inst in connectors:
        x, y = connectors[inst]
        return (_round(x), _round(y)), ("H" if abs(x) >= abs(y) else "V")
    if inst in instances:
        ox, oy, rot = instances[inst]
        ttype = layout.get("inst_types", {}).get(inst, "")
        px, py = _port_offset(ttype, port, layout.get("type_ports"))
        px, py = _rot(px, py, rot)
        # Land the endpoint exactly on the drawn connector pin (no rounding away from it),
        # so System Modeler draws no diagonal bridge from the pin to the line.
        ax = int(round(ox + px * BOX / 100.0))
        ay = int(round(oy + py * BOX / 100.0))
        orient = "H" if (px != 0 and abs(px) >= abs(py)) else ("V" if py != 0 else None)
        return (ax, ay), orient
    if inst in connectors:                           # connector referenced with a stray port
        x, y = connectors[inst]
        return (_round(x), _round(y)), ("H" if abs(x) >= abs(y) else "V")
    return None, None


def _route(a: tuple, b: tuple, da, db) -> list:
    """Orthogonal polyline from a to b, leaving a along ``da`` and arriving b along ``db``."""
    (ax, ay), (bx, by) = a, b
    if (ax, ay) == (bx, by):
        return [a, b]
    if ax == bx or ay == by:
        return [a, b]                                # already a single orthogonal segment
    if da == "H" and db == "V":
        return [a, (bx, ay), b]
    if da == "V" and db == "H":
        return [a, (ax, by), b]
    if da == "V" and db == "V":
        my = _round((ay + by) / 2.0)
        return [a, (ax, my), (bx, my), b]
    if da == "H" and db == "H":
        mx = _round((ax + bx) / 2.0)
        return [a, (mx, ay), (mx, by), b]
    # Exactly one side known: honour it (the other end just meets the elbow).
    if da == "H" or db == "H":
        return [a, (bx, ay), b] if da == "H" else [a, (ax, by), b]
    if da == "V" or db == "V":
        return [a, (ax, by), b] if da == "V" else [a, (bx, ay), b]
    # Neither known: tidy Z through a vertical mid-channel (the original behaviour).
    mx = _round((ax + bx) / 2.0)
    return [a, (mx, ay), (mx, by), b]


def _points_str(pts: list) -> str:
    return "{" + ",".join("{%d,%d}" % (x, y) for (x, y) in pts) + "}"


def line_for(cn: Connect, cls: ClassSpan, layout: dict) -> str:
    """Return the ``Line(...)`` annotation body for one connect, or a minimal stub."""
    a, da = _anchor(cn.from_inst, cn.from_port, layout)
    b, db = _anchor(cn.to_inst, cn.to_port, layout)
    rgb = _color_for(cn, cls)
    if a is None or b is None:
        # endpoint not placed (e.g. an inherited class connector) — emit a harmless stub
        return "Line(points={{0,0},{0,0}}, color=%s)" % colors.fmt(rgb)
    if a == b:
        # the two pins coincide (e.g. diode-connected to itself): a small visible loop
        x, y = a
        pts = [(x, y), (x + 25, y), (x + 25, y + 20), (x, y + 20)]
    else:
        pts = _route(a, b, da, db)
    return "Line(points=%s, color=%s, thickness=0.5)" % (_points_str(pts), colors.fmt(rgb))


def _color_for(cn: Connect, cls: ClassSpan) -> tuple:
    # Prefer the declared connector type of a class-level connector endpoint.
    conn_types = {c.name: c.type_name for c in cls.connectors}
    for end in (cn.from_inst, cn.to_inst):
        if end in conn_types:
            return colors.color_for_type(conn_types[end])
    # else infer from the port leaf name (.y/.u -> signal, .p/.n/.v/.i -> electrical)
    for path in (cn.from_path, cn.to_path):
        rgb = colors.color_for_port(path)
        if rgb != colors.DEFAULT:
            return rgb
    return colors.DEFAULT
