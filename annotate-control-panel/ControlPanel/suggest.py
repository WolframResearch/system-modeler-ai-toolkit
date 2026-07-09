"""Propose a starting control-panel spec from a class's parameters.

A starting point only — the caller curates it (drop parameters that shouldn't be exposed, set
sensible slider ranges and labels, group into panels, link figures). Control type is chosen from
each parameter's declared type; slider ranges are a guess around the default.
"""

from __future__ import annotations


def _slider_range(default) -> tuple:
    """A first-guess ``(min, max)`` around a numeric default; the caller should refine it."""
    if default is None:
        return 0.0, 1.0
    if default > 0:
        return 0.0, round(default * 2, 12)
    if default < 0:
        return round(default * 2, 12), 0.0
    return -1.0, 1.0


def _control_for(param) -> dict:
    kind = param.base_kind
    label = param.description or None
    if kind == "boolean":
        return {"type": "checkbox", "variable": param.name, "label": label}
    if kind == "numeric":
        lo, hi = _slider_range(param.default_number)
        c = {"type": "slider", "variable": param.name, "label": label, "min": lo, "max": hi}
        if param.default_number is None:
            c["type"] = "inputField"
            c.pop("min"); c.pop("max")
        return c
    # string / enumeration / unresolved: an input field is always safe (switch a known
    # enumeration to a popupMenu with items by hand).
    return {"type": "inputField", "variable": param.name, "label": label}


def suggest_spec(params: list, max_controls: int = 12, title: str = "Controls",
                 identifier: str = "controls") -> tuple:
    """Return ``(spec, notes)`` — a control-panel-spec dict and a list of remarks."""
    notes = []
    if not params:
        return {"panels": []}, ["no parameters found to expose as controls"]
    chosen = params
    if len(params) > max_controls:
        notes.append("showing first %d of %d parameters; curate the spec to expose the ones you "
                     "want to control" % (max_controls, len(params)))
        chosen = params[:max_controls]
    controls = []
    for p in chosen:
        c = _control_for(p)
        if c.get("label") is None:
            c.pop("label")
        controls.append(c)
    notes.append("slider ranges are first guesses around each default — adjust min/max to the "
                 "range you want to explore")
    spec = {"panels": [{"identifier": identifier, "title": title, "controls": controls}]}
    return spec, notes
