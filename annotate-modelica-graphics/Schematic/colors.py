"""Domain colors for connectors and connection lines (matches MSL conventions)."""

ELECTRICAL = (0, 0, 255)
SIGNAL = (0, 0, 127)
MECHANICAL = (0, 127, 0)
HYDRAULIC = (0, 170, 255)
FLUID = (0, 127, 255)
THERMAL = (191, 0, 0)
MAGNETIC = (255, 128, 0)
LOGIC = (127, 0, 127)
DEFAULT = (0, 0, 0)

# Reverse map for human-readable reporting (e.g. in --analyze).
_DOMAIN_NAMES = {
    ELECTRICAL: "electrical", SIGNAL: "signal", MECHANICAL: "mechanical",
    HYDRAULIC: "hydraulic", FLUID: "fluid", THERMAL: "thermal",
    MAGNETIC: "magnetic", LOGIC: "digital", DEFAULT: "unknown",
}


def name_for(rgb: tuple) -> str:
    return _DOMAIN_NAMES.get(rgb, "unknown")


def color_for_type(type_name: str) -> tuple:
    """RGB for a connector type name, covering the Modelica Standard Library domains.

    Matching is by substring so it recognizes custom names too (``MyHeatPort`` -> thermal,
    ``ShaftFlange`` -> mechanical). A bare ``…Port`` with no domain hint is deliberately left
    DEFAULT (unknown) so the caller is prompted to author a domain-specific symbol for it.
    """
    t = type_name
    last = t.split(".")[-1]
    if any(k in t for k in ("RealInput", "RealOutput", "BooleanInput", "BooleanOutput",
                            "IntegerInput", "IntegerOutput", "Blocks.Interfaces",
                            "StateGraph", "Clocked")):
        return SIGNAL
    if any(k in t for k in ("Digital", "Logic")):
        return LOGIC
    if "Magnetic" in t:
        return MAGNETIC
    if any(k in t for k in ("Thermal", "HeatTransfer", "HeatPort")):
        return THERMAL
    if any(k in t for k in ("Electrical", "SpacePhasor")) or last.endswith(("Pin", "Plug")):
        return ELECTRICAL
    if any(k in t for k in ("Mechanic", "Rotational", "Translational", "MultiBody",
                            "Flange", "Frame")):
        return MECHANICAL
    if "Hydraulic" in t:
        return HYDRAULIC
    if any(k in t for k in ("Fluid", "FlowPort")):
        return FLUID
    return DEFAULT


def color_for_port(port: str) -> tuple:
    """Best-effort RGB from a port name, used when the endpoint type is unknown."""
    p = port.split(".")[-1].lower()
    if p in ("y", "u", "u1", "u2"):
        return SIGNAL
    if p in ("p", "n", "v", "i", "pin", "vpos", "vneg"):
        return ELECTRICAL
    if "flange" in p:
        return MECHANICAL
    if "heatport" in p or p in ("port_h", "q_flow"):
        return THERMAL
    if p.startswith("port") or p in ("inlet", "outlet", "ports"):
        return FLUID
    return DEFAULT


def fmt(rgb: tuple) -> str:
    return "{%d,%d,%d}" % (rgb[0], rgb[1], rgb[2])
