"""Render a figures spec (parsed JSON) into standardized Modelica ``figures = {...}`` text.

Shape: ``figures`` -> ``Figure`` -> ``Plot`` -> ``Curve`` / ``Axis`` (see SKILL.md). Only fields
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


def _render_plot(plot: dict, indent: str) -> str:
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
    plots = (",\n" + inner + "  ").join(_render_plot(p, inner + "  ") for p in fig["plots"])
    parts.append("plots = {\n%s  %s}" % (inner, plots))
    if fig.get("caption"):
        parts.append("caption = %s" % _mstr(fig["caption"]))
    return "Figure(\n%s%s)" % (inner, (",\n" + inner).join(parts))


def render_figures_array(figures: list, indent: str = "    ") -> str:
    """Render the ``{Figure(...), ...}`` array (without the ``figures = `` prefix)."""
    body = (",\n" + indent).join(_render_figure(f, indent) for f in figures)
    return "{\n%s%s}" % (indent, body)


def validate_spec(spec: dict, known_vars: set | None = None,
                  protected_vars: set | None = None) -> list:
    """Validate a figures spec. Returns non-fatal warnings; raises :class:`SpecError` on hard
    errors (bad result-refs, duplicate identifiers, missing plots/curves).

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
            if "time" in x_refs and len(x_refs) > 1:
                warnings.append("a plot in figure %r mixes time-based and X-vs-Y curves — all "
                                "curves share the plot's x axis; split them into separate plots"
                                % (fid or "<unnamed>"))
    return warnings
