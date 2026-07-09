"""Classify each parsed class and decide what graphics it should receive."""

from __future__ import annotations

from dataclasses import dataclass

from . import icons_lib
from .parser import ClassSpan


@dataclass
class Plan:
    category: str            # package | record | function | type | connector | composite | leaf | thin_extends
    is_example: bool         # runnable example (has experiment annotation)
    standard_icon: str | None    # Modelica.Icons.* base to extend, or None
    wants_diagram: bool      # lay out component instances + route connections
    wants_custom_icon: bool  # draw a custom Icon(graphics) + place connectors on its edges
    reason: str = ""

    @property
    def is_noop(self) -> bool:
        return not (self.standard_icon or self.wants_diagram or self.wants_custom_icon)


def classify(cls: ClassSpan) -> Plan:
    kind = cls.kind
    has_instances = bool(cls.instances)
    has_connects = bool(cls.connects)
    has_connectors = bool(cls.connectors)
    is_composite = has_instances or has_connects
    is_example = cls.has_experiment

    # --- Category classes: a standard Icons.* base is the right, idiomatic icon -----
    if kind == "package":
        return Plan("package", False, _std("package", cls), False, False,
                    "package -> Modelica.Icons.Package")
    if kind == "record":
        return Plan("record", False, _std("record", cls), False, False,
                    "record -> Modelica.Icons.Record")
    if kind == "function":
        return Plan("function", False, _std("function", cls), False, False,
                    "function -> Modelica.Icons.Function")
    if kind == "type":
        return Plan("type", False, None, False, False, "type: left as-is")
    if kind == "connector":
        # A connector carries its own symbol (a domain-colored square). Give one to any
        # in-file connector that lacks an icon; an unrecognized domain gets a neutral square
        # the caller should replace with an authored glyph.
        already = cls.has_icon or any(icons_lib.is_icons_base(b) for b in cls.extends)
        if already:
            return Plan("connector", False, None, False, False, "connector: icon already present")
        return Plan("connector", False, None, False, True, "connector -> domain-colored icon")

    # Does the class already carry a graphical icon (own Icon annotation or an Icons.* base)?
    already_icon = cls.has_icon or any(icons_lib.is_icons_base(b) for b in cls.extends)

    # --- model / block / class -------------------------------------------------------
    # A thin variant that only `extends` a base inherits the base's graphics/equations.
    if cls.extends and not is_composite and not has_connectors and not already_icon:
        return Plan("thin_extends", is_example, None, False, False,
                    "thin extends: inherits base graphics")

    standard = None
    wants_custom = False
    wants_diagram = is_composite

    if is_example and not already_icon:
        # Runnable example: the play-button icon is the convention; its internals are
        # shown by the diagram layer.
        standard = icons_lib.standard_icon_for("example")
        reason = "runnable example -> Modelica.Icons.Example" + (" + diagram" if wants_diagram else "")
    elif has_connectors and not already_icon:
        # A reusable component or sub-circuit with a public interface: draw a symbol so
        # the connectors sit on the icon boundary (used when instantiated elsewhere).
        wants_custom = True
        reason = ("composite building block" if is_composite else "leaf component") + \
                 " -> custom icon" + (" + diagram" if wants_diagram else "")
    elif is_composite:
        reason = "composite -> diagram" + (" (icon already present)" if already_icon else " only")
    else:
        reason = "icon already present" if already_icon else "no graphics needed"

    cat = "composite" if is_composite else ("leaf" if has_connectors else "other")
    return Plan(cat, is_example, standard, wants_diagram, wants_custom, reason)


def _std(role: str, cls: ClassSpan) -> str | None:
    """Standard icon for a category class, unless it already has one / already extends Icons.*"""
    if cls.has_icon:
        return None
    if any(icons_lib.is_icons_base(b) for b in cls.extends):
        return None
    return icons_lib.standard_icon_for(role)
