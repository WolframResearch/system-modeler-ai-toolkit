"""Render a control-panel spec (parsed JSON) into a Wolfram ``__Wolfram(ControlPanels(...))``
vendor annotation, and validate the spec.

Shape: ``panels`` -> ``Panel`` -> ``controls`` (one of InputField / Checkbox / Slider /
PopupMenu) + ``figures`` (see SKILL.md). The grammar mirrors System Modeler's own serializer:
``variable`` is an unquoted component reference; ``label`` is a quoted string emitted only when
present; slider ``min``/``max`` and popup ``value`` are unquoted (a String value carries its own
quotes); ``showInputField`` is emitted only when false; ``scale`` only when logarithmic.
Render functions assume a spec that has already passed :func:`validate_spec`.
"""

from __future__ import annotations

import math
import re

_IDENT = r"(?:'[^']*'|[A-Za-z_]\w*)"
_SUBS = r"(?:\[[^\]]*\])?"
_CREF = r"\.?" + _IDENT + _SUBS + r"(?:\." + _IDENT + _SUBS + r")*"
_CREF_RE = re.compile(r"^" + _CREF + r"$")

_CONTROL_TYPES = ("inputField", "checkbox", "slider", "popupMenu")


class SpecError(ValueError):
    """A control-panel spec is structurally invalid or violates a Modelica spec rule."""


def _mstr(s) -> str:
    """A Modelica string literal; ``%`` markup is left untouched."""
    s = "" if s is None else str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mnum(x) -> str:
    """A finite numeric literal, emitted unquoted. Rejects nan/inf (not valid Modelica)."""
    if isinstance(x, bool):
        raise SpecError("expected a number, got a boolean")
    v = float(x)  # also validates a numeric string
    if not math.isfinite(v):
        raise SpecError("slider bound must be a finite number, got %r" % (x,))
    return repr(float(x)) if isinstance(x, (int, float)) else str(x).strip()


def _check_cref(ref) -> None:
    if not isinstance(ref, str) or not _CREF_RE.match(ref.strip()):
        raise SpecError("control 'variable' must be a component reference (e.g. Kp or "
                        "controller.gain[1]), got %r" % (ref,))


def _render_label(ctrl: dict, parts: list) -> None:
    if "label" in ctrl and ctrl["label"] is not None:
        parts.append("label = %s" % _mstr(ctrl["label"]))


def _render_input_field(ctrl: dict) -> str:
    parts = ["variable = %s" % ctrl["variable"].strip()]
    _render_label(ctrl, parts)
    return "InputField(%s)" % ", ".join(parts)


def _render_checkbox(ctrl: dict) -> str:
    parts = ["variable = %s" % ctrl["variable"].strip()]
    _render_label(ctrl, parts)
    return "Checkbox(%s)" % ", ".join(parts)


def _render_slider(ctrl: dict) -> str:
    parts = ["variable = %s" % ctrl["variable"].strip()]
    _render_label(ctrl, parts)
    parts.append("min = %s" % _mnum(ctrl["min"]))
    parts.append("max = %s" % _mnum(ctrl["max"]))
    if ctrl.get("showInputField") is False:
        parts.append("showInputField = false")
    if ctrl.get("scale") == "Log":
        parts.append("scale = Log()")
    return "Slider(%s)" % ", ".join(parts)


def _render_item(item: dict) -> str:
    parts = ["value = %s" % str(item["value"]).strip()]
    if item.get("label") is not None:
        parts.append("label = %s" % _mstr(item["label"]))
    return "Item(%s)" % ", ".join(parts)


def _render_popup_menu(ctrl: dict, indent: str) -> str:
    parts = ["variable = %s" % ctrl["variable"].strip()]
    _render_label(ctrl, parts)
    items = ctrl.get("items") or []
    if items:
        inner = (",\n" + indent + "    ").join(_render_item(it) for it in items)
        parts.append("items = {\n%s    %s}" % (indent, inner))
    return "PopupMenu(%s)" % ", ".join(parts)


def _render_control(ctrl: dict, indent: str) -> str:
    kind = ctrl["type"]
    if kind == "inputField":
        return _render_input_field(ctrl)
    if kind == "checkbox":
        return _render_checkbox(ctrl)
    if kind == "slider":
        return _render_slider(ctrl)
    if kind == "popupMenu":
        return _render_popup_menu(ctrl, indent)
    raise SpecError("unknown control type %r (use one of %s)" % (kind, ", ".join(_CONTROL_TYPES)))


def _render_panel(panel: dict, indent: str) -> str:
    inner = indent + "  "
    parts = ["identifier = %s" % _mstr(panel["identifier"]),
             "title = %s" % _mstr(panel["title"])]
    controls = panel.get("controls") or []
    if controls:
        elems = (",\n" + inner + "  ").join(_render_control(c, inner + "  ") for c in controls)
        parts.append("elements = {\n%s  %s}" % (inner, elems))
    figures = panel.get("figures") or []
    if figures:
        parts.append("figures = {%s}" % ", ".join(_mstr(f) for f in figures))
    return "Panel(\n%s%s)" % (inner, (",\n" + inner).join(parts))


def render_control_panels(panels: list, indent: str = "    ") -> str:
    """Render the full ``__Wolfram(ControlPanels(Panel(...), ...))`` annotation element."""
    body = (",\n" + indent).join(_render_panel(p, indent) for p in panels)
    return "__Wolfram(ControlPanels(\n%s%s))" % (indent, body)


def validate_spec(spec: dict, known_vars: set | None = None,
                  tunable_vars: set | None = None,
                  var_types: dict | None = None,
                  known_figures: set | None = None) -> list:
    """Validate a control-panel spec. Returns non-fatal warnings; raises :class:`SpecError` on
    hard errors (bad control types, missing variable, duplicate identifiers, bad slider bounds).

    Optional context (from source discovery or a ``.sim`` file) turns mismatches into warnings:
    ``known_vars`` flags a reference the model doesn't have; ``tunable_vars`` flags a variable
    that is structural (constant-folded, not changeable without a rebuild); ``var_types`` flags a
    control type that doesn't fit the variable's declared type; ``known_figures`` flags a
    ``figures`` id with no matching stored Figure."""
    panels = spec.get("panels")
    if not isinstance(panels, list) or not panels:
        raise SpecError("spec must have a non-empty 'panels' list")
    warnings = []
    panel_ids = set()
    for panel in panels:
        pid = panel.get("identifier")
        if not pid or not isinstance(pid, str):
            raise SpecError("each panel needs a non-empty string 'identifier'")
        if pid in panel_ids:
            raise SpecError("duplicate Panel identifier %r" % pid)
        panel_ids.add(pid)
        if not panel.get("title") or not isinstance(panel["title"], str):
            raise SpecError("panel %r needs a non-empty string 'title'" % pid)

        for ctrl in (panel.get("controls") or []):
            kind = ctrl.get("type")
            if kind not in _CONTROL_TYPES:
                raise SpecError("panel %r: control 'type' must be one of %s, got %r"
                                % (pid, ", ".join(_CONTROL_TYPES), kind))
            _check_cref(ctrl.get("variable"))
            var = ctrl["variable"].strip()
            if kind == "slider":
                if ctrl.get("min") is None or ctrl.get("max") is None:
                    raise SpecError("panel %r: slider on %r needs numeric 'min' and 'max'"
                                    % (pid, var))
                lo, hi = float(_mnum(ctrl["min"])), float(_mnum(ctrl["max"]))
                if lo >= hi:
                    warnings.append("slider on %r has min >= max (%s >= %s)" % (var, lo, hi))
            if kind == "popupMenu":
                for it in (ctrl.get("items") or []):
                    if it.get("value") is None or str(it.get("value")).strip() == "":
                        raise SpecError("panel %r: a PopupMenu Item on %r has no 'value'"
                                        % (pid, var))

            if known_vars is not None and var not in known_vars:
                warnings.append("control references %r, which is not among the model's "
                                "parameters/variables (check the name, or it may be a "
                                "constant-folded structural parameter)" % var)
            elif tunable_vars is not None and var not in tunable_vars:
                warnings.append("%r is present but not runtime-tunable (initType != exact); "
                                "changing it from a control panel requires a rebuild/re-simulate"
                                % var)
            if var_types and var in var_types:
                _warn_type_fit(kind, var, var_types[var], warnings)

        if known_figures is not None:
            for fid in (panel.get("figures") or []):
                if fid not in known_figures:
                    warnings.append("panel %r lists figure %r, but the model has no stored Figure "
                                    "with that identifier (add it with annotate-modelica-plots)"
                                    % (pid, fid))
    return warnings


def _warn_type_fit(kind: str, var: str, vtype: str, warnings: list) -> None:
    """Append a warning when a control type does not fit the variable's declared base type."""
    t = (vtype or "").split(".")[-1]
    is_bool = t == "Boolean"
    is_numeric = t in ("Real", "Integer") or vtype in ("Real", "Integer") \
        or _looks_numeric(vtype)
    if kind == "checkbox" and not is_bool:
        warnings.append("checkbox on %r, but its type %r is not Boolean" % (var, vtype))
    if kind == "slider" and not is_numeric:
        warnings.append("slider on %r, but its type %r is not Real/Integer" % (var, vtype))


def _looks_numeric(vtype: str) -> bool:
    """Heuristic: an SI/unit type (e.g. Modelica.Units.SI.Mass) is a Real subtype."""
    return any(p in (vtype or "") for p in ("Units.SI", "SIunits", "Units.NonSI"))
