"""
Find features in a Modelica simulation .mat result and write them as plot markers
(``Figure.markers`` in an annotate-modelica-plots figures spec).

A marker is a vertical line at a time or a horizontal line at a level. Simulation
Center lists the value of every curve where a vertical marker crosses it, and every
time a curve crosses a horizontal one. Vertical lines go on time-based plots only:
on an X vs. Y plot a vertical marker is read in the x variable's unit.

Each FEATURE is ``VAR:KIND[:ARG]``:

    VAR:max            vertical line at the time of the maximum of VAR
    VAR:min            vertical line at the time of the minimum of VAR
    VAR:at:T           vertical line at time T
    VAR:settle:FRAC    vertical line at the settling time: from then on VAR stays within
                       FRAC * |final - initial| of its final value (default FRAC 0.02), or
                       within FRAC * its largest deviation from the final value when VAR
                       returns to about where it started
    VAR:cross:LEVEL    horizontal line at LEVEL, given in the unit the marker is written in
    VAR:final          horizontal line at the final value of VAR
    VAR:initial        horizontal line at the initial value of VAR

Horizontal lines are written in the unit the plot's y axis shows: --unit if given, else
the Axis.unit of the target plots in --spec, else the variable's displayUnit, else its
unit (read from the .sim file beside the .mat).

Usage:
    python mat_features.py <mat_file> FEATURE [FEATURE ...] [options]

Options:
    --spec PATH       figures-spec JSON to add the markers to (rewritten in place)
    --class NAME      class in a mapping spec ({"Class": {"figures": ...}}); optional
                      when the mapping has one class
    --figure ID       Figure in --spec that receives them (default: the preferred / first)
    --plots LIST      comma list of plot identifiers or 0-based indices that show them
                      (default: every plot of the figure)
    --unit U          unit for horizontal lines (and for a cross LEVEL)
    --digits N        significant digits in labels (default: 4)
    --no-label        write markers without labels

Without --spec the markers are printed as JSON.

Examples:
    python mat_features.py res.mat s:min s:settle:0.02
    python mat_features.py res.mat p:max p:cross:3 --unit bar --spec figs.json --plots pressure
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _env import reexec_under_managed_venv
    reexec_under_managed_venv(["DyMat", "numpy"])
except Exception:
    pass

try:
    import numpy as np
    import matresult
except ImportError:
    _py = "python" if sys.platform == "win32" else "python3"
    print("ERROR: DyMat and numpy are required. Provision them into the managed venv with:\n"
          "  %s \"%s/bootstrap_env.py\"" % (_py, os.path.dirname(os.path.abspath(__file__))),
          file=sys.stderr)
    sys.exit(1)

import mo_edit

VERTICAL = ("max", "min", "at", "settle")
HORIZONTAL = ("cross", "final", "initial")
_PREFIXES = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6,
             "k": 1e3, "h": 1e2, "da": 1e1, "d": 1e-1, "c": 1e-2, "m": 1e-3, "u": 1e-6,
             "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18}


class FeatureError(ValueError):
    pass


class Units:
    """Variable units from the .sim file and unit conversions from its units table."""

    def __init__(self, mat_path):
        self.var_units = {}
        self.table = {}
        sim = os.path.splitext(mat_path)[0] + ".sim"
        if not os.path.isfile(sim):
            return
        root = ET.parse(sim).getroot()
        for v in root.iter("variable"):
            if v.get("name"):
                self.var_units[v.get("name")] = (v.get("unit") or "", v.get("displayUnit") or "")
        units_path = root.get("unitsPath")
        if units_path:
            units_path = os.path.join(os.path.dirname(sim), units_path)
            if os.path.isfile(units_path):
                with open(units_path, encoding="utf-8") as f:
                    for u in json.load(f).get("units", []):
                        self.table[u["symbol"]] = u

    def of(self, var):
        """(unit, displayUnit) of a result variable; empty strings when unknown."""
        return self.var_units.get(var, ("", ""))

    def _lookup(self, symbol):
        """(scale, offset, dimension) taking a value in ``symbol`` to SI, or None."""
        u = self.table.get(symbol)
        if u:
            return u["scale"], u["offset"], u["factors"]
        for prefix, factor in _PREFIXES.items():
            u = self.table.get(symbol[len(prefix):]) if symbol.startswith(prefix) else None
            if u and u.get("prefixable") and not u["offset"]:
                return u["scale"] * factor, 0.0, u["factors"]
        return None

    def converter(self, src, dst):
        """A function converting values from unit ``src`` to ``dst``, or None if unknown."""
        if src == dst:
            return lambda x: x
        a, b = self._lookup(src), self._lookup(dst)
        if not a or not b or a[2] != b[2]:
            return None
        return lambda x: ((x * a[0] + a[1]) - b[1]) / b[0]

    def presentation(self, symbol):
        u = self.table.get(symbol)
        return (u.get("presentation") or symbol) if u else symbol


def _fmt(x, digits):
    x = float(x)
    if x == 0 or 1e-3 <= abs(x) < 1e6:
        return np.format_float_positional(x, precision=digits, unique=False, fractional=False,
                                          trim="-")
    return "%.*g" % (digits, x)


def _num(x):
    return float("%.10g" % float(x))


def _with_unit(text, unit):
    return "%s %s" % (text, unit) if unit else text


def _series(d, var):
    if var not in d.names():
        raise FeatureError("variable %r not in result (see plot_mat.py --list)" % var)
    y = matresult.series(d, var)
    t = np.asarray(d.abscissa(var)[0], dtype=float)
    if y.size == 1:
        y = np.repeat(y, t.size)
    return t, y


def _settling_time(t, y, frac, var):
    yf, y0 = y[-1], y[0]
    excursion = float(np.max(np.abs(y - yf)))
    step = abs(yf - y0)
    band = frac * (step if step >= frac * excursion else excursion)
    outside = np.nonzero(np.abs(y - yf) > band)[0]
    if outside.size == 0:
        return float(t[0])
    ts = float(t[min(outside[-1] + 1, t.size - 1)])
    if ts > t[0] + 0.9 * (t[-1] - t[0]):
        raise FeatureError("%s has not settled: it leaves the %g band around its last value "
                           "until %s s, too close to the end of the run (%s s) to tell a final "
                           "value; simulate longer" % (var, frac, _fmt(ts, 6), _fmt(t[-1], 6)))
    return ts


def _identifier(feature):
    var, _, rest = feature.partition(":")
    rest = rest.lower().replace("-", "m").replace(".", "p").replace("+", "")
    return re.sub(r"[^A-Za-z0-9_]+", "_", var + ":" + rest).strip("_")


def feature_marker(d, units, feature, unit=None, digits=4, label=True):
    """A marker dict for one ``VAR:KIND[:ARG]`` feature. ``unit`` is the unit a horizontal
    line is written in (default: the variable's displayUnit, else its unit)."""
    var, sep, rest = feature.partition(":")
    if not sep or not var:
        raise FeatureError("feature %r must be VAR:KIND[:ARG]" % feature)
    kind, _, arg = rest.partition(":")
    kind = kind.lower()
    if kind not in VERTICAL + HORIZONTAL:
        raise FeatureError("unknown feature kind %r (%s)" % (kind, "|".join(VERTICAL + HORIZONTAL)))
    t, y = _series(d, var)
    var_unit, display_unit = units.of(var)
    target = unit if unit is not None else (display_unit or var_unit)
    to_target = units.converter(var_unit, target)
    if to_target is None:
        print("note: no conversion from %r to %r; writing %s in %r" % (var_unit, target, feature,
              var_unit), file=sys.stderr)
        target, to_target = var_unit, (lambda x: x)
    shown = units.presentation(target)
    m = {"identifier": _identifier(feature)}

    def number(text):
        try:
            return float(text)
        except ValueError:
            raise FeatureError("%s: %r is not a number" % (feature, text))

    if kind in ("max", "min"):
        i = int(np.argmax(y) if kind == "max" else np.argmin(y))
        m.update(x=_num(t[i]), xUnit="s")
        text = "%s %s = %s at %s s" % (kind, var, _with_unit(_fmt(to_target(y[i]), digits), shown),
                                       _fmt(t[i], digits))
    elif kind == "at":
        tv = number(arg) if arg else None
        if tv is None or not t[0] <= tv <= t[-1]:
            raise FeatureError("%s: 'at' needs a time within the run (%s to %s s), e.g. %s:at:%s"
                               % (feature, _fmt(t[0], 6), _fmt(t[-1], 6), var, _fmt(t[-1] / 2, 3)))
        m.update(x=_num(tv), xUnit="s")
        text = "%s(%s s) = %s" % (var, _fmt(tv, digits),
                                  _with_unit(_fmt(to_target(np.interp(tv, t, y)), digits), shown))
    elif kind == "settle":
        frac = number(arg) if arg else 0.02
        ts = _settling_time(t, y, frac, var)
        m.update(x=_num(ts), xUnit="s")
        text = "%s settles (%g%%%%) at %s s" % (var, 100 * frac, _fmt(ts, digits))
    else:
        if kind == "cross":
            if not arg:
                raise FeatureError("%s: 'cross' needs a level, e.g. %s:cross:0" % (feature, var))
            level = number(arg)
            yt = np.array([to_target(v) for v in y])
            if not yt.min() <= level <= yt.max():
                print("note: %s never reaches %s %s" % (var, arg, target), file=sys.stderr)
            text = "%s = %s" % (var, _with_unit(_fmt(level, digits), shown))
        else:
            level = to_target(y[-1] if kind == "final" else y[0])
            text = ("final %s = %%{%s}" % (var, var)) if kind == "final" else \
                "initial %s = %s" % (var, _with_unit(_fmt(level, digits), shown))
        m.update(y=_num(level))
        if target:
            m["yUnit"] = target
    if label:
        m["label"] = text
    return m


def _parse_plots(s):
    out = [int(tok) if tok.isdigit() else tok for tok in (x.strip() for x in s.split(",")) if tok]
    return out or None


def _class_spec(spec, cls):
    """The single-class part of a spec: the spec itself, or one entry of a mapping spec."""
    if "figures" in spec:
        if cls:
            raise FeatureError("--class is only for a mapping spec ({\"Class\": {\"figures\": ...}})")
        return spec
    if cls:
        if not isinstance(spec.get(cls), dict):
            raise FeatureError("mapping spec has no class %r (it has: %s)" % (cls, ", ".join(spec)))
        return spec[cls]
    if len(spec) == 1 and isinstance(next(iter(spec.values())), dict):
        return next(iter(spec.values()))
    raise FeatureError("spec has no figures; for a mapping spec with several classes pass "
                       "--class (it has: %s)" % ", ".join(spec))


def _target_figure(spec, fig_id):
    figs = spec.get("figures") or []
    if not figs:
        raise FeatureError("spec has no figures")
    if fig_id:
        for f in figs:
            if f.get("identifier") == fig_id:
                return f
        raise FeatureError("no figure with identifier %r in spec" % fig_id)
    return next((f for f in figs if f.get("preferred")), figs[0])


def _target_plots(fig, wanted):
    plots = fig.get("plots") or []
    if wanted is None:
        return plots
    chosen = []
    for w in wanted:
        if isinstance(w, int) and 0 <= w < len(plots):
            chosen.append(plots[w])
        else:
            match = [p for p in plots if p.get("identifier") == w]
            if not match:
                raise FeatureError("figure %r has no plot %r" % (fig.get("identifier"), w))
            chosen.extend(match)
    return chosen


def _axis_unit(plots):
    """The y-axis unit shared by all target plots, or None if they set none or differ."""
    found = {((p.get("y") or {}).get("unit") or "") for p in plots}
    return found.pop() if len(found) == 1 and "" not in found else None


def _reject_xy_plots(feature, plots):
    """A vertical marker is read in the x axis' unit, so a time only belongs on a time plot."""
    for p in plots:
        if any(str(c.get("x", "time")).strip() != "time" for c in p.get("curves") or []):
            raise FeatureError("%s is a time, but plot %r is an X vs. Y plot, where a vertical "
                               "marker is read in the x variable's unit; pass --plots naming "
                               "only time-based plots" % (feature, p.get("identifier") or p.get("title")))


def _warn_unplotted(var, plots):
    for p in plots:
        if any(str(c.get("y", "")).strip() == var for c in p.get("curves") or []):
            return
    print("note: %s is not a curve in the target plots; its marker may sit on another variable's "
          "axis" % var, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Turn .mat result features into plot markers")
    ap.add_argument("mat_file")
    ap.add_argument("features", nargs="+", help="VAR:KIND[:ARG] (see module docstring)")
    ap.add_argument("--spec", help="figures-spec JSON to add the markers to (rewritten in place)")
    ap.add_argument("--class", dest="class_name",
                    help="class whose figures receive the markers, in a mapping spec")
    ap.add_argument("--figure", help="Figure identifier in --spec (default: preferred / first)")
    ap.add_argument("--plots", help="comma list of plot identifiers / indices (default: all)")
    ap.add_argument("--unit", help="unit for horizontal lines (and for a cross LEVEL)")
    ap.add_argument("--digits", type=int, default=4)
    ap.add_argument("--no-label", action="store_true")
    args = ap.parse_args()

    try:
        d = matresult.load(args.mat_file)
        units = Units(args.mat_file)
        plots = _parse_plots(args.plots) if args.plots else None
        spec = fig = None
        unit = args.unit
        if args.spec:
            raw = mo_edit.read_raw(args.spec)
            spec = json.loads(raw)
            fig = _target_figure(_class_spec(spec, args.class_name), args.figure)
            targets = _target_plots(fig, plots)
            if unit is None:
                unit = _axis_unit(targets)
        markers = {}
        for feat in args.features:
            m = feature_marker(d, units, feat, unit=unit, digits=args.digits,
                               label=not args.no_label)
            if plots:
                m["plots"] = plots
            if fig is not None and "x" in m:
                _reject_xy_plots(feat, targets)
            if fig is not None:
                _warn_unplotted(feat.split(":")[0], targets)
            if m["identifier"] in markers:
                raise FeatureError("features %r and %r give the same marker identifier %r"
                                   % (markers[m["identifier"]]["_feature"], feat, m["identifier"]))
            markers[m["identifier"]] = dict(m, _feature=feat)
    except (FeatureError, OSError, ValueError, ET.ParseError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1

    for m in markers.values():
        del m["_feature"]
    if spec is None:
        json.dump(list(markers.values()), sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    kept = [m for m in fig.get("markers") or [] if m.get("identifier") not in markers]
    fig["markers"] = kept + list(markers.values())
    mo_edit.write_atomic(args.spec, json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
                         mo_edit.dominant_eol(raw))
    print("added %d marker(s) to figure %r in %s" % (len(markers), fig.get("identifier"), args.spec),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
