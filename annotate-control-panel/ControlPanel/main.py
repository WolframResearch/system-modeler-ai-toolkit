"""CLI for annotate-control-panel. Run as a module from the skill directory:

    python3 -m ControlPanel.main --file Model.mo --analyze
    python3 -m ControlPanel.main --file Model.mo --suggest > panels.json
    python3 -m ControlPanel.main --file Model.mo --class Pkg.Model --spec panels.json --annotate [--write]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import xml.etree.ElementTree as ET

# Output (dry-run diffs, em dashes) may contain non-ASCII; force UTF-8 so it
# doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from . import panels as panels_mod
from . import discover as discover_mod
from . import simvars as simvars_mod
from . import suggest as suggest_mod
from .inject import inject_control_panels
from .parser import parse, mask_code, ParseError
from mo_edit import (dominant_eol, write_atomic,
                     balanced_close as _balanced_close, find_call_open as _find_call_open)


def _eprint(*a) -> None:
    print(*a, file=sys.stderr)


def _model_classes(classes: list) -> list:
    return [c for c in classes if c.kind in ("model", "block", "class")]


def _qualified_name(classes: list, idx: int) -> str:
    parts = []
    while idx != -1:
        parts.append(classes[idx].name)
        idx = classes[idx].parent
    return ".".join(reversed(parts))


def _index_of(classes: list, cls) -> int:
    return next((i for i, c in enumerate(classes) if c is cls), -1)


def _resolve_class(classes: list, want):
    """Pick the target instantiable class (model/block/class). Exact qualified-name match wins,
    else a unique leaf-name match; None if nothing matches or the leaf is ambiguous."""
    models = [(i, c) for i, c in enumerate(classes) if c.kind in ("model", "block", "class")]
    if not want:
        return models[0][1] if len(models) == 1 else None
    exact = [c for i, c in models if _qualified_name(classes, i) == want]
    if len(exact) == 1:
        return exact[0]
    leaf = want.split(".")[-1]
    byleaf = [c for i, c in models if c.name == leaf]
    return byleaf[0] if len(byleaf) == 1 else None


def _child_ranges(classes: list, target_idx: int) -> list:
    """Source spans of ``target``'s nested classes, so their parameters aren't attributed here."""
    return [(c.header_start, c.full_end) for c in classes if c.parent == target_idx]


def _params_for(text: str, classes: list, target) -> list:
    idx = _index_of(classes, target)
    return discover_mod.find_parameters(text, target, _child_ranges(classes, idx))


def _known_figure_ids(text: str, cls):
    """Identifiers of stored Figures in the class's ``Documentation(figures = {...})`` block, or
    None if the class has no such block (then figure-reference checks are skipped). Scoped to
    ``Documentation`` so a control panel's own ``figures = {"id"}`` list is never mistaken for it."""
    if cls.annotation_end <= 0:
        return None
    mask = mask_code(text)
    doc_open = _find_call_open(mask, cls.annotation_start, cls.annotation_end + 1, "Documentation")
    if doc_open == -1:
        return None
    doc_close = _balanced_close(mask, doc_open)
    if doc_close == -1:
        return None
    m = re.compile(r"\bfigures\s*=\s*").search(mask, doc_open, doc_close)
    if not m:
        return None
    brace = mask.find("{", m.end(), doc_close)
    close = _balanced_close(mask, brace) if brace != -1 else -1
    if close == -1:
        return None
    return set(re.findall(r'identifier\s*=\s*"([^"]+)"', text[brace:close]))


def _sim_context(sim_file):
    """Return ``(known_vars, tunable_vars)`` from a ``.sim`` file, or ``(None, None)``."""
    if not sim_file:
        return None, None
    sim = simvars_mod.read_sim(sim_file)
    return simvars_mod.names(sim), simvars_mod.tunable_names(sim)


def cmd_analyze(args, text, classes) -> int:
    print("Classes in %s:" % args.file)
    for c in classes:
        has_cp = False
        if c.annotation_end > 0:
            has_cp = re.compile(r"\bControlPanels\s*\(").search(
                mask_code(text), c.annotation_start, c.annotation_end + 1) is not None
        print("  %-9s %s%s" % (c.kind, c.name, " [HAS control panels]" if has_cp else ""))
    target = _resolve_class(classes, args.cls)
    if target is not None:
        params = _params_for(text, classes, target)
        print("\nControllable parameters in %s: %d" % (target.name, len(params)))
        for p in params:
            d = (" = %s" % p.default) if p.default else ""
            print("  %-12s %s%s%s" % (p.base_kind, p.type_name, " " + p.name, d))
    print("\n%d instantiable class(es); target with --class <Name>." % len(_model_classes(classes)))
    return 0


def cmd_suggest(args, text, classes) -> int:
    target = _resolve_class(classes, args.cls)
    if target is None:
        _eprint("error: could not resolve target class — pass --class explicitly (%d instantiable "
                "classes)" % len(_model_classes(classes)))
        return 2
    params = _params_for(text, classes, target)
    spec, notes = suggest_mod.suggest_spec(params, max_controls=args.max_controls,
                                           title="%s controls" % target.name)
    for n in notes:
        _eprint("note: " + n)
    json.dump(spec, sys.stdout, indent=2)
    print()
    return 0


def cmd_annotate(args, text, classes, eol="\n") -> int:
    if not args.spec:
        _eprint("error: --annotate requires --spec PATH (a control-panel-spec JSON)")
        return 2
    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)

    target = _resolve_class(classes, args.cls)
    if target is None:
        _eprint("error: could not resolve target class %r — pass --class explicitly (%d "
                "instantiable classes)" % (args.cls, len(_model_classes(classes))))
        return 2

    params = _params_for(text, classes, target)
    var_types = {p.name: p.type_name for p in params}
    sim_vars, tunable = _sim_context(args.sim_file)
    known = None
    if sim_vars is not None or params:
        known = set(var_types) | (sim_vars or set())
    known_figs = _known_figure_ids(text, target)

    try:
        warns = panels_mod.validate_spec(spec, known_vars=known, tunable_vars=tunable,
                                         var_types=var_types, known_figures=known_figs)
        rendered = panels_mod.render_control_panels(spec["panels"])
    except (panels_mod.SpecError, ValueError) as e:
        _eprint("error: invalid spec for class %s: %s" % (target.name, e))
        return 1
    for w in warns:
        _eprint("warning [%s]: %s" % (target.name, w))

    # re-parse against the (possibly re-read) text so spans are valid; match by qualified name.
    target_q = _qualified_name(classes, _index_of(classes, target))
    fresh = parse(text)
    live = next((c for i, c in enumerate(fresh)
                 if _qualified_name(fresh, i) == target_q and c.kind == target.kind), None)
    if live is None:
        _eprint("error: lost track of class %s" % target.name)
        return 1
    new_text, status = inject_control_panels(text, live, rendered, force=args.force)
    _eprint("%s: %s" % (target.name, status))

    if status == "skipped":
        _eprint("nothing to do (already has control panels; use --force to regenerate)")
        return 0
    if args.write:
        write_atomic(args.file, new_text, eol)
        _eprint("wrote %s" % args.file)
    else:
        sys.stdout.writelines(difflib.unified_diff(
            text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=args.file, tofile=args.file + " (annotated)"))
        _eprint("\n(dry run — re-run with --write to apply)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ControlPanel.main",
                                description="Add Wolfram control-panel (Explore) annotations to a .mo")
    p.add_argument("--file", required=True, help="the .mo file")
    p.add_argument("--class", dest="cls", default=None,
                   help="target class (simple or dotted); default the sole model class")
    p.add_argument("--analyze", action="store_true",
                   help="list classes, control-panel status, and controllable parameters")
    p.add_argument("--suggest", action="store_true",
                   help="print a suggested control-panel spec from the class parameters (no edits)")
    p.add_argument("--annotate", action="store_true", help="inject control panels from --spec")
    p.add_argument("--write", action="store_true", help="apply edits (default is a dry-run diff)")
    p.add_argument("--force", action="store_true",
                   help="regenerate even if control panels already exist")
    p.add_argument("--spec", default=None, help="control-panel-spec JSON path")
    p.add_argument("--sim-file", dest="sim_file", default=None,
                   help="the .sim file beside a built/simulated result .mat; used to check that "
                        "controlled variables exist and are runtime-tunable")
    p.add_argument("--max-controls", dest="max_controls", type=int, default=12,
                   help="cap for --suggest (default 12)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
    except OSError as e:
        _eprint("error: cannot read %s: %s" % (args.file, e))
        return 2
    eol = dominant_eol(raw)
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    try:
        classes = parse(text)
        if args.suggest:
            return cmd_suggest(args, text, classes)
        if args.annotate:
            return cmd_annotate(args, text, classes, eol)
        return cmd_analyze(args, text, classes)
    except ParseError as e:
        _eprint("error: cannot parse %s: %s" % (args.file, e))
        return 2
    except (OSError, json.JSONDecodeError, ET.ParseError) as e:
        _eprint("error: %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
