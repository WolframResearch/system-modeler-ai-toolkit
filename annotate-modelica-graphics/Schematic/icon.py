"""Generate custom ``Icon`` graphics and connector edge placements for leaf
components and sub-circuit building blocks that have no standard ``Modelica.Icons.*``
equivalent.

Recognized device kinds get a hand-drawn glyph (transistor, amplifier, tank, pump, valve,
pipe, heat capacitor). Anything else falls back to a generic labeled block — and the caller
can override that block with an LLM-authored glyph (see ``build_icon(custom=...)``), so an
unknown domain can still be drawn from primitives based on the model's description.
"""

from __future__ import annotations

from . import colors
from .parser import ClassSpan, Connector


# ---------------------------------------------------------------------------
# Connector edge assignment
# ---------------------------------------------------------------------------

def _role_edge(conn: Connector) -> str | None:
    """Heuristic edge ('L','R','T','B') for a connector from its type/name, or None."""
    t = conn.type_name
    if "Input" in t.split(".")[-1]:
        return "L"
    if "Output" in t.split(".")[-1]:
        return "R"
    n = conn.name.lower()
    if n in ("b", "base"):
        return "L"
    if n in ("c", "collector", "coll"):
        return "T"
    if n in ("e", "emitter", "emit"):
        return "B"
    # fluid / generic physical ports
    if n in ("port_a", "inlet", "fluidport_a"):
        return "L"
    if n in ("port_b", "outlet", "fluidport_b"):
        return "R"
    if n.startswith("ports"):
        return "B"
    if n in ("heatport", "port_h"):
        return "T"
    if n == "top":
        return "T"
    if n == "bottom":
        return "B"
    if n.startswith("in") or n in ("p", "plus", "anode", "u", "u1", "u2"):
        return "L"
    if n.startswith("out") or n in ("y",):
        return "R"
    if n in ("vpos", "vcc", "vdd", "vp", "vsup", "vplus", "supply", "vs"):
        return "T"
    if n in ("vneg", "vee", "vss", "vn", "vminus", "gnd", "ground"):
        return "B"
    if n in ("n", "minus", "cathode"):
        return "R"
    return None


# device-name -> {connector-name: edge} overrides, applied before _role_edge.
_DEVICE_EDGE_OVERRIDES = {
    "npn": {"b": "L", "c": "T", "e": "B"},
    "pnp": {"b": "L", "c": "T", "e": "B"},
    "tank": {"port_a": "B", "port_b": "B", "ports": "B",
             "inlet": "T", "outlet": "B", "bottom": "B", "top": "T"},
    "pump": {"port_a": "L", "inlet": "L", "port_b": "R", "outlet": "R"},
    "valve": {"port_a": "L", "inlet": "L", "port_b": "R", "outlet": "R"},
    "pipe": {"port_a": "L", "inlet": "L", "port_b": "R", "outlet": "R"},
}

_VALID_EDGES = ("L", "R", "T", "B")


def _device_kind(cls: ClassSpan) -> str:
    s = (cls.name + " " + cls.kind + " " + (cls.description or "")).lower()
    if "pnp" in s:
        return "pnp"
    if "npn" in s or "bjt" in s or "transistor" in s:
        return "npn"
    if "ota" in s or "opamp" in s or "op_amp" in s or "amplif" in s:
        return "amp"
    if "tank" in s or "vessel" in s or "reservoir" in s:
        return "tank"
    if "pump" in s:
        return "pump"
    if "valve" in s:
        return "valve"
    if "pipe" in s or "duct" in s:
        return "pipe"
    if "heatcapacitor" in s or "heat capacitor" in s or "thermal mass" in s or "heatcap" in s:
        return "heatcap"
    return "block"


def assign_connector_edges(connectors: list, device: str, overrides: dict | None = None) -> dict:
    """Return name -> (px, py) boundary point for each connector.

    ``overrides`` (name -> 'L'/'R'/'T'/'B') wins over every heuristic — used to honor an
    explicitly authored glyph's port placement.
    """
    dev_over = _DEVICE_EDGE_OVERRIDES.get(device, {})
    edges = {}
    for c in connectors:
        e = None
        if overrides and overrides.get(c.name) in _VALID_EDGES:
            e = overrides[c.name]
        if e is None:
            e = dev_over.get(c.name.lower())
        if e is None:
            e = _role_edge(c)
        edges[c.name] = e

    # round-robin fill for any unassigned, balancing edge counts
    order = ["L", "R", "T", "B"]
    unassigned = [c.name for c in connectors if edges[c.name] is None]
    counts = {ed: sum(1 for v in edges.values() if v == ed) for ed in order}
    for nm in unassigned:
        ed = min(order, key=lambda x: counts[x])
        edges[nm] = ed
        counts[ed] += 1

    # distribute along each edge
    by_edge = {ed: [c.name for c in connectors if edges[c.name] == ed] for ed in order}
    points = {}
    for ed, names in by_edge.items():
        k = len(names)
        for i, nm in enumerate(names):
            t = -60 + 120 * (i + 1) / (k + 1)
            if ed == "L":
                points[nm] = (-100, _round(t))
            elif ed == "R":
                points[nm] = (100, _round(t))
            elif ed == "T":
                points[nm] = (_round(t), 100)
            else:
                points[nm] = (_round(t), -100)
    return points


def _round(v: float) -> int:
    return int(round(v / 10.0)) * 10


def connector_placement(px: int, py: int) -> str:
    """Placement annotation anchoring a connector to the icon (and diagram) boundary."""
    ext = "extent={{%d,%d},{%d,%d}}" % (px - 10, py - 10, px + 10, py + 10)
    return ("Placement(transformation(%s), iconTransformation(%s))" % (ext, ext))


# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------

_ELEC = colors.fmt(colors.ELECTRICAL)
_FLUID = colors.fmt(colors.FLUID)
_THERMAL = colors.fmt(colors.THERMAL)


def _name_text() -> str:
    return ('Text(extent={{-100,105},{100,145}}, textString="%name", '
            'textColor={0,0,255})')


def _glyph_block() -> list:
    return [
        ("Rectangle(extent={{-70,-70},{70,70}}, lineColor={0,0,0}, "
         "fillColor={245,245,245}, fillPattern=FillPattern.Solid, radius=10)"),
        ('Text(extent={{-60,-25},{60,25}}, textString="%class", textColor={0,0,0})'),
    ]


def _glyph_transistor(npn: bool) -> list:
    # base on left (-100,0), collector top (40,100), emitter bottom (40,-100)
    g = [
        "Line(points={{-90,0},{-30,0}}, color=%s)" % _ELEC,
        "Line(points={{-30,45},{-30,-45}}, color=%s, thickness=0.6)" % _ELEC,
        "Line(points={{-30,25},{40,55}}, color=%s)" % _ELEC,
        "Line(points={{40,55},{40,90}}, color=%s)" % _ELEC,
        "Line(points={{-30,-25},{40,-55}}, color=%s)" % _ELEC,
        "Line(points={{40,-55},{40,-90}}, color=%s)" % _ELEC,
    ]
    # emitter arrowhead: NPN points outward (toward emitter pin), PNP inward (toward base)
    if npn:
        arrow = ("Polygon(points={{40,-55},{22,-44},{30,-30},{40,-55}}, "
                 "lineColor=%s, fillColor=%s, fillPattern=FillPattern.Solid)" % (_ELEC, _ELEC))
    else:
        arrow = ("Polygon(points={{-30,-25},{-12,-36},{-20,-50},{-30,-25}}, "
                 "lineColor=%s, fillColor=%s, fillPattern=FillPattern.Solid)" % (_ELEC, _ELEC))
    g.append(arrow)
    return g


def _glyph_amp() -> list:
    return [
        ("Polygon(points={{-60,70},{-60,-70},{70,0},{-60,70}}, lineColor={0,0,0}, "
         "fillColor={245,245,245}, fillPattern=FillPattern.Solid)"),
        ('Text(extent={{-45,15},{-15,45}}, textString="+", textColor={0,0,0})'),
        ('Text(extent={{-45,-45},{-15,-15}}, textString="-", textColor={0,0,0})'),
    ]


def _glyph_tank() -> list:
    # open vessel: left wall, floor, right wall (no lid) + a liquid fill at the bottom.
    return [
        "Line(points={{-60,80},{-60,-80},{60,-80},{60,80}}, color={0,0,0}, thickness=0.5)",
        ("Rectangle(extent={{-58,-78},{58,-10}}, lineColor=%s, fillColor={120,190,255}, "
         "fillPattern=FillPattern.Solid)" % _FLUID),
    ]


def _glyph_pump() -> list:
    # centrifugal pump: circle with an impeller triangle pointing to the outlet.
    return [
        ("Ellipse(extent={{-60,-60},{60,60}}, lineColor={0,0,0}, fillColor={245,245,245}, "
         "fillPattern=FillPattern.Solid)"),
        ("Polygon(points={{-25,35},{-25,-35},{45,0},{-25,35}}, lineColor=%s, fillColor=%s, "
         "fillPattern=FillPattern.Solid)" % (_FLUID, _FLUID)),
    ]


def _glyph_valve() -> list:
    # bowtie / butterfly valve symbol.
    return [
        ("Polygon(points={{-60,45},{-60,-45},{0,0},{-60,45}}, lineColor={0,0,0}, "
         "fillColor={245,245,245}, fillPattern=FillPattern.Solid)"),
        ("Polygon(points={{60,45},{60,-45},{0,0},{60,45}}, lineColor={0,0,0}, "
         "fillColor={245,245,245}, fillPattern=FillPattern.Solid)"),
    ]


def _glyph_pipe() -> list:
    return [
        ("Rectangle(extent={{-90,-22},{90,22}}, lineColor={0,0,0}, fillColor={230,230,230}, "
         "fillPattern=FillPattern.Solid)"),
    ]


def _glyph_heatcap() -> list:
    return [
        ("Rectangle(extent={{-60,-50},{60,50}}, lineColor=%s, fillColor={255,213,170}, "
         "fillPattern=FillPattern.Solid, radius=8)" % _THERMAL),
        ('Text(extent={{-50,-20},{50,20}}, textString="%class", textColor=%s)' % _THERMAL),
    ]


def _glyph_connector(cls: ClassSpan) -> list:
    """A connector's own symbol: a full-frame square filled in its domain color."""
    rgb = colors.color_for_type(cls.name)
    c = colors.fmt(rgb)
    return [("Rectangle(extent={{-100,-100},{100,100}}, lineColor=%s, fillColor=%s, "
             "fillPattern=FillPattern.Solid)" % (c, c))]


_GLYPHS = {
    "npn": lambda: _glyph_transistor(npn=True),
    "pnp": lambda: _glyph_transistor(npn=False),
    "amp": _glyph_amp,
    "tank": _glyph_tank,
    "pump": _glyph_pump,
    "valve": _glyph_valve,
    "pipe": _glyph_pipe,
    "heatcap": _glyph_heatcap,
}


def _glyph_for(device: str) -> list:
    fn = _GLYPHS.get(device)
    return fn() if fn else _glyph_block()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_icon(cls: ClassSpan, no_glyphs: bool = False, custom: dict | None = None) -> tuple:
    """Return (icon_graphics_block, {connector_name: (px, py)}).

    ``icon_graphics_block`` is the ``Icon(coordinateSystem(...), graphics={...})`` text
    (without the surrounding ``annotation(...)``); inject.py merges/wraps it. The points are
    the connector anchor positions on the icon boundary (used for ``iconTransformation``).

    ``custom`` is an optional LLM-authored glyph for this class:
        ``{"graphics": [<primitive str>, ...],
           "ports": {<connector>: "L"|"R"|"T"|"B"},   # optional
           "name_text": bool}``                       # optional, default True
    When present its primitives replace the generic block, so an unrecognized domain can still
    be drawn meaningfully from the model's description.
    """
    if custom and custom.get("graphics"):
        device = "custom"
        graphics = list(custom["graphics"])
        overrides = custom.get("ports")
        if custom.get("name_text", True):
            graphics = [_name_text()] + graphics
    elif cls.kind == "connector":
        device = "connector"
        graphics = [_name_text()] + _glyph_connector(cls)
        overrides = None
    else:
        device = "block" if no_glyphs else _device_kind(cls)
        graphics = [_name_text()] + _glyph_for(device)
        overrides = None

    points = assign_connector_edges(cls.connectors, device, overrides)

    icon = ("Icon(coordinateSystem(preserveAspectRatio=true, "
            "extent={{-100,-100},{100,100}}), graphics={\n        "
            + ",\n        ".join(graphics) + "})")
    return icon, points
