"""Domain colors for connectors and connection lines (matches MSL conventions)."""

from __future__ import annotations

ELECTRICAL = (0, 0, 255)
SIGNAL = (0, 0, 127)
ROTATIONAL = (0, 0, 0)
TRANSLATIONAL = (0, 127, 0)
MULTIBODY = (95, 95, 95)
HYDRAULIC = (0, 170, 255)
FLUID = (0, 127, 255)
THERMAL = (191, 0, 0)
MAGNETIC = (255, 128, 0)
LOGIC = (127, 0, 127)
DEFAULT = (0, 0, 0)

_RGB = {
    "electrical": ELECTRICAL, "signal": SIGNAL, "rotational": ROTATIONAL,
    "translational": TRANSLATIONAL, "multibody": MULTIBODY, "hydraulic": HYDRAULIC,
    "fluid": FLUID, "thermal": THERMAL, "magnetic": MAGNETIC, "digital": LOGIC,
    "unknown": DEFAULT,
}


def _mechanical_domain(type_name: str) -> str:
    last = type_name.split(".")[-1]
    if "Translational" in type_name:
        return "translational"
    if "Flange" in last or "Rotational" in type_name:
        return "rotational"
    if "MultiBody" in type_name or last.startswith("Frame"):
        return "multibody"
    return "rotational"


def domain_for_type(type_name: str) -> str:
    """Domain of a connector type name, covering the Modelica Standard Library domains.

    Matching is by substring so it recognizes custom names too (``MyHeatPort`` -> thermal,
    ``ShaftFlange`` -> rotational). A bare ``…Port`` with no domain hint is deliberately left
    ``unknown`` so the caller is prompted to author a domain-specific symbol for it.
    """
    t = type_name
    last = t.split(".")[-1]
    if any(k in t for k in ("RealInput", "RealOutput", "BooleanInput", "BooleanOutput",
                            "IntegerInput", "IntegerOutput", "Blocks.Interfaces",
                            "StateGraph", "Clocked")):
        return "signal"
    if any(k in t for k in ("Digital", "Logic")):
        return "digital"
    if "Magnetic" in t:
        return "magnetic"
    if any(k in t for k in ("Thermal", "HeatTransfer", "HeatPort")):
        return "thermal"
    if any(k in t for k in ("Electrical", "SpacePhasor")) or last.endswith(("Pin", "Plug")):
        return "electrical"
    if any(k in t for k in ("Mechanic", "Rotational", "Translational", "MultiBody",
                            "Flange", "Frame")):
        return _mechanical_domain(t)
    if "Hydraulic" in t:
        return "hydraulic"
    if any(k in t for k in ("Fluid", "FlowPort")):
        return "fluid"
    return "unknown"


def color_for_type(type_name: str) -> tuple:
    return _RGB[domain_for_type(type_name)]


_KIND_RGB = {"i": SIGNAL, "o": SIGNAL, "e": ELECTRICAL, "t": THERMAL, "f": FLUID,
             "r": ROTATIONAL, "l": TRANSLATIONAL}


def color_for_pin(kind: str, port: str, owner_type: str = "") -> tuple | None:
    """RGB for a pin of kind ``kind`` (as ``pins.resolve`` reports it) on a component of
    type ``owner_type``, or None when neither says."""
    if kind in _KIND_RGB:
        return _KIND_RGB[kind]
    rgb = color_for_port(port, owner_type)
    if rgb is None and kind == "m":
        return TRANSLATIONAL if "Translational" in owner_type else ROTATIONAL
    return rgb


def color_for_port(port: str, owner_type: str = "") -> tuple | None:
    """Best-effort RGB from a port name and the type of the component that owns it, used
    when the connector's own type is unknown. None when neither gives a domain."""
    p = port.split(".")[-1].lower()
    if p in ("y", "u", "u1", "u2"):
        return SIGNAL
    if p in ("p", "n", "v", "i", "pin", "vpos", "vneg"):
        return ELECTRICAL
    if p.startswith("frame"):
        return MULTIBODY
    if "flange" in p or p == "support":
        return TRANSLATIONAL if "Translational" in owner_type else ROTATIONAL
    if "heatport" in p or p in ("port_h", "q_flow"):
        return THERMAL
    if p.startswith("port") or p in ("inlet", "outlet", "ports"):
        return FLUID
    return None


def fmt(rgb: tuple) -> str:
    return "{%d,%d,%d}" % (rgb[0], rgb[1], rgb[2])
