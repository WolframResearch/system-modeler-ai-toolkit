"""annotate-control-panel — write Wolfram System Modeler control-panel (Explore) annotations
into a .mo model.

Adds ``annotation(__Wolfram(ControlPanels(Panel(...))))`` so a model carries the interactive
control panels that Simulation Center's Explore view shows — sliders, checkboxes, input fields
and popup menus bound to parameters/start values, plus the plots to display. Pure Python
(stdlib only); WSMKernelX is used only afterwards as a validation gate.
"""

from .parser import parse, parse_file, ClassSpan  # noqa: F401
