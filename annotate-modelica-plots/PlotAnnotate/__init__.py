"""annotate-modelica-plots — write standardized result-plot annotations into a .mo model.

Adds ``annotation(Documentation(figures = {Figure(...)}))`` so a model's simulation plots are
stored in the source and reopen in Wolfram System Modeler. Pure Python (stdlib only); WSMKernelX
is used only afterwards as a validation gate.
"""

from .parser import parse, parse_file, ClassSpan  # noqa: F401
