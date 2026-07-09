"""Schematic — add Modelica graphical annotations (Icon + Diagram) to text models.

This package parses a textual ``.mo`` file, classifies each class, and injects
``extends Modelica.Icons.*`` / ``Icon`` / ``Placement`` / ``Line`` annotations so the
model renders as a clean, laid-out schematic in Wolfram System Modeler.

It is a self-contained source-level transform: all parsing, geometry and injection
happen on the text. WSMKernelX is only used (by the SKILL workflow, not this package)
as a post-edit safety gate to confirm the file still flattens.
"""

__all__ = [
    "parser",
    "classify",
    "icons_lib",
    "colors",
    "icon",
    "layout",
    "routing",
    "inject",
]
