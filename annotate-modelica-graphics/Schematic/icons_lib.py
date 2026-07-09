"""Map a class *role* to a ready-made ``Modelica.Icons.*`` base class.

For category classes (packages, runnable examples, records, functions) the cleanest,
most idiomatic icon is simply ``extends Modelica.Icons.<X>;`` — it renders exactly like
the rest of the Modelica Standard Library and needs no generated graphics.
"""

from __future__ import annotations  # `str | None` annotations on Python < 3.10

# role -> Modelica.Icons base class
_STANDARD = {
    "package": "Modelica.Icons.Package",
    "example": "Modelica.Icons.Example",
    "record": "Modelica.Icons.Record",
    "function": "Modelica.Icons.Function",
}


def standard_icon_for(role: str) -> str | None:
    """Return the fully-qualified ``Modelica.Icons.*`` base for a role, or None."""
    return _STANDARD.get(role)


def is_icons_base(base_class: str) -> bool:
    """True if a base class is one of the Modelica.Icons.* graphical bases."""
    return "Icons." in base_class
