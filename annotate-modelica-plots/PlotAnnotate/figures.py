"""Render a figures spec (parsed JSON) into standardized Modelica ``figures = {...}`` text.

Shape: ``figures`` -> ``Figure`` -> ``Plot`` -> ``Curve`` / ``Axis`` (see SKILL.md), plus the
System Modeler plot markers: ``Figure.markers`` -> ``__Wolfram_markers`` on the Figure and a
``__Wolfram_markerAppearances`` entry on every Plot that shows the marker. Only fields
that are set are emitted. ``Curve.x``/``.y`` are restricted by the spec to result-references — a
scalar variable, ``time``, or ``der(v, n)`` — which :func:`validate_spec` enforces. Render
functions assume a spec that has already passed :func:`validate_spec`.
"""

from __future__ import annotations

import math
import re

_IDENT = r"(?:'[^']*'|[A-Za-z_]\w*)"
_SUBS = r"(?:\[[^\]]*\])?"
_CREF = r"\.?" + _IDENT + _SUBS + r"(?:\." + _IDENT + _SUBS + r")*"
_CREF_RE = re.compile(r"^" + _CREF + r"$")
_DER_RE = re.compile(r"^der\(\s*(?P<arg>" + _CREF + r"|time)\s*(?:,\s*\d+\s*)?\)$")


class SpecError(ValueError):
    """A figures spec is structurally invalid or violates a Modelica spec rule."""


def base_variable(ref: str) -> str:
    """The underlying variable of a result-reference (strip ``der(...)`` and subscripts)."""
    m = _DER_RE.match(ref.strip())
    ref = m.group("arg").strip() if m else ref.strip()
    if ref == "time":
        return "time"
    return re.sub(r"\[[^\]]*\]", "", ref).lstrip(".")


def validate_result_ref(ref: str) -> None:
    if not isinstance(ref, str) or not ref.strip():
        raise SpecError("curve x/y must be a non-empty result-reference string")
    r = ref.strip()
    if r == "time" or _CREF_RE.match(r) or _DER_RE.match(r):
        return
    raise SpecError("%r is not a valid result-reference (expected a scalar variable, 'time', "
                    "or der(var[, n]))" % ref)


def _mstr(s) -> str:
    """A Modelica string literal; ``%`` markup is left untouched."""
    s = "" if s is None else str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mnum(x) -> str:
    if isinstance(x, bool):
        raise SpecError("expected a number, got a boolean")
    # nan/inf (including overflow like 1e309) are not valid Modelica literals and
    # would make the annotated model fail to flatten; reject them at spec time.
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        v = float(x)  # validate string
    if not math.isfinite(v):
        raise SpecError("axis bound must be a finite number, got %r" % (x,))
    return repr(float(x)) if isinstance(x, (int, float)) else str(x).strip()


def _render_scale(scale) -> str:
    if scale == "Linear":
        return "Linear()"
    if scale == "Log":
        return "Log()"
    if isinstance(scale, dict) and "Log" in scale:
        return "Log(base = %d)" % int(scale["Log"])
    raise SpecError("invalid axis scale %r (use 'Linear', 'Log', or {'Log': base})" % scale)


def _render_axis(axis: dict) -> str:
    parts = []
    if axis.get("min") is not None:
        parts.append("min = %s" % _mnum(axis["min"]))
    if axis.get("max") is not None:
        parts.append("max = %s" % _mnum(axis["max"]))
    if axis.get("unit") is not None:
        parts.append("unit = %s" % _mstr(axis["unit"]))
    if axis.get("label") is not None:
        parts.append("label = %s" % _mstr(axis["label"]))
    if axis.get("scale") is not None:
        parts.append("scale = %s" % _render_scale(axis["scale"]))
    return "Axis(%s)" % ", ".join(parts)


def _render_curve(curve: dict) -> str:
    parts = ["x = %s" % curve.get("x", "time").strip(), "y = %s" % curve["y"].strip()]
    if curve.get("legend") is not None:
        parts.append("legend = %s" % _mstr(curve["legend"]))
    if curve.get("zOrder"):
        parts.append("zOrder = %d" % int(curve["zOrder"]))
    return "Curve(%s)" % ", ".join(parts)


_VALIGN = ("Top", "Center", "Bottom")
_HALIGN = ("Left", "Center", "Right")


def _render_label_position(lp: dict) -> str:
    parts = []
    for key in ("xOffsetCanvas", "yOffsetCanvas"):
        if lp.get(key) is not None:
            parts.append("%s = %s" % (key, _mnum(lp[key])))
    if lp.get("verticalAlignment") is not None:
        parts.append("verticalAlignment = VerticalAlignment.%s" % lp["verticalAlignment"])
    if lp.get("horizontalAlignment") is not None:
        parts.append("horizontalAlignment = HorizontalAlignment.%s" % lp["horizontalAlignment"])
    return "LabelPosition(%s)" % ", ".join(parts)


def _render_marker(marker: dict) -> str:
    axis = "x" if marker.get("x") is not None else "y"
    pos = ["%s = %s" % (axis, _mnum(marker[axis]))]
    if marker.get(axis + "Unit"):
        pos.append("%sUnit = %s" % (axis, _mstr(marker[axis + "Unit"])))
    parts = ["identifier = %s" % _mstr(marker["identifier"]),
             "position = MarkerPosition(%s)" % ", ".join(pos)]
    if marker.get("yAxis") == "right":
        parts.append('yAxis = "right"')
    if marker.get("label"):
        parts.append("label = %s" % _mstr(marker["label"]))
    return "Marker(%s)" % ", ".join(parts)


def _render_appearance(marker: dict) -> str:
    parts = ["marker = %s" % _mstr(marker["identifier"])]
    if marker.get("labelPosition"):
        parts.append("labelPosition = %s" % _render_label_position(marker["labelPosition"]))
    return "MarkerAppearance(%s)" % ", ".join(parts)


def _marker_shows_in(marker: dict, plot: dict, index: int) -> bool:
    """A marker appears in every plot of its figure unless ``plots`` names identifiers/indices."""
    wanted = marker.get("plots")
    if wanted is None:
        return True
    return index in wanted or (plot.get("identifier") or "") in wanted


def _render_plot(plot: dict, index: int, markers: list, indent: str) -> str:
    inner = indent + "  "
    parts = []
    if plot.get("identifier"):
        parts.append("identifier = %s" % _mstr(plot["identifier"]))
    if plot.get("title") is not None:
        parts.append("title = %s" % _mstr(plot["title"]))
    curves = (",\n" + inner + "    ").join(_render_curve(c) for c in plot["curves"])
    parts.append("curves = {\n%s    %s}" % (inner, curves))
    if plot.get("x") is not None:
        parts.append("x = %s" % _render_axis(plot["x"]))
    if plot.get("y") is not None:
        parts.append("y = %s" % _render_axis(plot["y"]))
    shown = [m for m in markers if _marker_shows_in(m, plot, index)]
    if shown:
        apps = (",\n" + inner + "    ").join(_render_appearance(m) for m in shown)
        parts.append("__Wolfram_markerAppearances = {\n%s    %s}" % (inner, apps))
    return "Plot(\n%s%s)" % (inner, (",\n" + inner).join(parts))


def _render_figure(fig: dict, indent: str) -> str:
    inner = indent + "  "
    parts = []
    if fig.get("identifier"):
        parts.append("identifier = %s" % _mstr(fig["identifier"]))
    if fig.get("title") is not None:
        parts.append("title = %s" % _mstr(fig["title"]))
    if fig.get("group"):
        parts.append("group = %s" % _mstr(fig["group"]))
    if fig.get("preferred"):
        parts.append("preferred = true")
    markers = fig.get("markers") or []
    plots = (",\n" + inner + "  ").join(_render_plot(p, i, markers, inner + "  ")
                                       for i, p in enumerate(fig["plots"]))
    parts.append("plots = {\n%s  %s}" % (inner, plots))
    if fig.get("caption"):
        parts.append("caption = %s" % _mstr(fig["caption"]))
    if markers:
        marks = (",\n" + inner + "  ").join(_render_marker(m) for m in markers)
        parts.append("__Wolfram_markers = {\n%s  %s}" % (inner, marks))
    return "Figure(\n%s%s)" % (inner, (",\n" + inner).join(parts))


def render_figures_array(figures: list, indent: str = "    ") -> str:
    """Render the ``{Figure(...), ...}`` array (without the ``figures = `` prefix)."""
    body = (",\n" + indent).join(_render_figure(f, indent) for f in figures)
    return "{\n%s%s}" % (indent, body)


def _check_number(value, what: str) -> None:
    try:
        _mnum(value)
    except (SpecError, ValueError, TypeError):
        raise SpecError("%s must be a finite number, got %r" % (what, value))


def _validate_marker(m: dict, mid: str, fid: str, plot_ids: set, nplots: int) -> list:
    warnings = []
    where = "marker %r in figure %r" % (mid, fid)
    has_x, has_y = m.get("x") is not None, m.get("y") is not None
    if has_x == has_y:
        raise SpecError("%s needs exactly one position: 'x' (a vertical line at a time) or 'y' "
                        "(a horizontal line at a level)%s"
                        % (where, "; System Modeler does not draw a marker with both" if has_x
                           else ""))
    axis = "x" if has_x else "y"
    _check_number(m[axis], "%s: %s" % (where, axis))
    if has_y and not m.get("yUnit"):
        warnings.append("%s has no yUnit; its level is then read in whatever unit the plot's y "
                        "axis shows" % where)
    if m.get("yAxis") not in (None, "left", "right"):
        raise SpecError("%s: yAxis must be 'left' or 'right'" % where)
    lp = m.get("labelPosition")
    if lp is not None:
        if not isinstance(lp, dict):
            raise SpecError("%s: labelPosition must be an object" % where)
        if lp.get("verticalAlignment") not in (None,) + _VALIGN:
            raise SpecError("%s: verticalAlignment must be one of %s" % (where, ", ".join(_VALIGN)))
        if lp.get("horizontalAlignment") not in (None,) + _HALIGN:
            raise SpecError("%s: horizontalAlignment must be one of %s"
                            % (where, ", ".join(_HALIGN)))
        for key in ("xOffsetCanvas", "yOffsetCanvas"):
            if lp.get(key) is not None:
                _check_number(lp[key], "%s: %s" % (where, key))
        unused = "xOffsetCanvas" if has_x else "yOffsetCanvas"
        if lp.get(unused) is not None:
            warnings.append("%s: %s is ignored on a %s marker; use %s to place the label along "
                            "the line" % (where, unused, "vertical" if has_x else "horizontal",
                                          "yOffsetCanvas" if has_x else "xOffsetCanvas"))
    wanted = m.get("plots")
    if wanted is not None:
        if not isinstance(wanted, list) or not wanted:
            raise SpecError("%s: 'plots' must be a non-empty list of plot identifiers or 0-based "
                            "indices (omit it to show the marker in every plot)" % where)
        for w in wanted:
            known = (isinstance(w, int) and not isinstance(w, bool) and 0 <= w < nplots) or \
                    (isinstance(w, str) and w in plot_ids)
            if not known:
                raise SpecError("%s references unknown plot %r" % (where, w))
    if not m.get("label"):
        warnings.append("%s has no label; it draws as a bare line" % where)
    return warnings


def _is_xy(plot: dict) -> bool:
    return any(str(c.get("x", "time")).strip() != "time" for c in plot.get("curves") or [])


def _xy_marker_warnings(fig: dict, fid: str) -> list:
    warnings = []
    for m in fig.get("markers") or []:
        if m.get("x") is None or (m.get("xUnit") or "s") != "s":
            continue
        for i, plot in enumerate(fig["plots"]):
            if _is_xy(plot) and _marker_shows_in(m, plot, i):
                warnings.append("marker %r in figure %r is a vertical line on X vs. Y plot %r: "
                                "System Modeler reads x = %s in the x variable's unit, not as a "
                                "time; give xUnit in that unit" % (m["identifier"], fid,
                                                                   plot.get("identifier") or i,
                                                                   m["x"]))
    return warnings


def _validate_markers(fig: dict, fid: str, plot_ids: set) -> list:
    """Check a figure's markers and fill in missing identifiers (``m1``, ``m2``, ...) in place."""
    markers = fig.get("markers") or []
    if not isinstance(markers, list):
        raise SpecError("figure %r: 'markers' must be a list" % fid)
    if any(not isinstance(m, dict) for m in markers):
        raise SpecError("figure %r: every marker must be an object" % fid)
    taken = {str(m["identifier"]) for m in markers if m.get("identifier")}
    n = 0
    for m in markers:
        if not m.get("identifier"):
            n += 1
            while "m%d" % n in taken:
                n += 1
            m["identifier"] = "m%d" % n
    warnings, seen = [], set()
    for m in markers:
        mid = str(m["identifier"])
        if mid in seen:
            raise SpecError("duplicate Marker identifier %r in figure %r" % (mid, fid))
        seen.add(mid)
        warnings.extend(_validate_marker(m, mid, fid, plot_ids, len(fig["plots"])))
    return warnings + _xy_marker_warnings(fig, fid)


def validate_spec(spec: dict, known_vars: set | None = None,
                  protected_vars: set | None = None) -> list:
    """Validate a figures spec. Returns non-fatal warnings; raises :class:`SpecError` on hard
    errors (bad result-refs, duplicate identifiers, missing plots/curves, bad markers). Fills in
    default marker identifiers in place.

    ``protected_vars`` (from the ``.sim`` file) trigger a warning per curve that references one:
    such a curve renders blank in System Modeler even though the model still flattens."""
    figures = spec.get("figures")
    if not isinstance(figures, list) or not figures:
        raise SpecError("spec must have a non-empty 'figures' list")
    warnings = []
    fig_ids = set()
    for fig in figures:
        fid = fig.get("identifier") or ""
        if fid and fid in fig_ids:
            raise SpecError("duplicate Figure identifier %r" % fid)
        fig_ids.add(fid)
        plots = fig.get("plots") or []
        if not plots:
            raise SpecError("figure %r has no plots" % (fid or "<unnamed>"))
        plot_ids = set()
        for plot in plots:
            pid = plot.get("identifier") or ""
            if pid and pid in plot_ids:
                raise SpecError("duplicate Plot identifier %r in figure %r" % (pid, fid))
            plot_ids.add(pid)
            curves = plot.get("curves") or []
            if not curves:
                raise SpecError("a plot in figure %r has no curves" % (fid or "<unnamed>"))
            for c in curves:
                if "y" not in c:
                    raise SpecError("each curve must have a 'y' result-reference")
                for ref in (c.get("x", "time"), c["y"]):
                    validate_result_ref(ref)
                    bv = base_variable(ref)
                    if known_vars is not None and bv != "time" and bv not in known_vars:
                        warnings.append("curve references %r, not found in the simulation "
                                        "result" % ref)
                    if protected_vars and bv in protected_vars:
                        warnings.append("curve references protected variable %r — it will render "
                                        "blank in System Modeler; plot a public variable instead"
                                        % ref)
            x_refs = {str(c.get("x", "time")).strip() for c in curves}
            if "time" in x_refs and _is_xy(plot):
                warnings.append("a plot in figure %r mixes time-based and X-vs-Y curves — all "
                                "curves share the plot's x axis; split them into separate plots"
                                % (fid or "<unnamed>"))
        warnings.extend(_validate_markers(fig, fid, plot_ids))
    return warnings
