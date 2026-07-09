"""CLI for annotate-modelica-plots. Run as a module from the skill directory:

    python3 -m PlotAnnotate.main --file Model.mo --analyze
    python3 -m PlotAnnotate.main --file Model.mo --vars-file vars.txt --suggest > figs.json
    python3 -m PlotAnnotate.main --file Model.mo --class Pkg.Model --spec figs.json --annotate [--write]
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import xml.etree.ElementTree as ET

# Output (dry-run diffs, em dashes) may contain non-ASCII; force UTF-8 so it
# doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from . import figures as fig_mod
from . import suggest as suggest_mod
from . import simvars as simvars_mod
from .inject import inject_figures
from .parser import parse, ParseError
from mo_edit import dominant_eol, write_atomic  # importable once .parser has run


def _eprint(*a) -> None:
    print(*a, file=sys.stderr)


def _model_classes(classes: list) -> list:
    return [c for c in classes if c.kind in ("model", "block", "class")]


def _qualified_name(classes: list, idx: int) -> str:
    """Dotted qualified name of classes[idx], walking the parent-index chain."""
    parts = []
    while idx != -1:
        parts.append(classes[idx].name)
        idx = classes[idx].parent
    return ".".join(reversed(parts))


def _index_of(classes: list, cls) -> int:
    return next((i for i, c in enumerate(classes) if c is cls), -1)


def _resolve_class(classes: list, want: str | None):
    """Pick the target instantiable class (model/block/class only).

    ``want`` may be simple or dotted. An exact qualified-name match wins first, so
    two classes sharing a leaf name (``A.M`` vs ``B.M``) are distinguishable;
    otherwise a *unique* leaf-name match is used. Returns None when nothing matches
    or the leaf is ambiguous (the caller then asks for an explicit --class), and
    never resolves to a non-instantiable class (package/record/…)."""
    models = [(i, c) for i, c in enumerate(classes)
              if c.kind in ("model", "block", "class")]
    if not want:
        return models[0][1] if len(models) == 1 else None
    exact = [c for i, c in models if _qualified_name(classes, i) == want]
    if len(exact) == 1:
        return exact[0]
    leaf = want.split(".")[-1]
    byleaf = [c for i, c in models if c.name == leaf]
    return byleaf[0] if len(byleaf) == 1 else None


def _load_vars(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [v for v in (line.strip() for line in f) if v and not v.startswith("#")]


def _known_vars(path: str | None) -> set | None:
    return {fig_mod.base_variable(v) for v in _load_vars(path)} if path else None


def _protected_vars(path: str | None) -> set:
    """Protected variable names from a ``.sim`` file (empty set if none passed)."""
    return simvars_mod.protected_names(path) if path else set()


def _specs_by_class(spec: dict) -> dict:
    """Normalize to ``{class_or_None: {figures:[...]}}``. A top-level ``figures`` key applies to
    the target class (key ``None``); otherwise the spec is already a class->spec mapping."""
    return {None: spec} if "figures" in spec else spec


def cmd_analyze(args, text, classes) -> int:
    print("Classes in %s:" % args.file)
    for c in classes:
        flags = [f for f, on in (("has Documentation", c.has_documentation),
                                 ("HAS figures", c.has_figures)) if on]
        print("  %-9s %s%s" % (c.kind, c.name, " [%s]" % ", ".join(flags) if flags else ""))
    if args.vars_file:
        print("\nPlottable variables supplied: %d" % len(_load_vars(args.vars_file)))
    print("\n%d instantiable class(es); target with --class <Name>." % len(_model_classes(classes)))
    return 0


def cmd_suggest(args, text, classes) -> int:
    if not args.vars_file:
        _eprint("error: --suggest requires --vars-file (a newline list from plot_mat.py --list)")
        return 2
    spec, notes = suggest_mod.suggest_spec(
        _load_vars(args.vars_file), max_curves=args.max_curves,
        protected=_protected_vars(args.sim_file))
    for n in notes:
        _eprint("note: " + n)
    json.dump(spec, sys.stdout, indent=2)
    print()
    return 0


def cmd_annotate(args, text, classes, eol="\n") -> int:
    if not args.spec:
        _eprint("error: --annotate requires --spec PATH (a figures-spec JSON)")
        return 2
    with open(args.spec, "r", encoding="utf-8") as f:
        raw_spec = json.load(f)
    known = _known_vars(args.vars_file)
    protected = _protected_vars(args.sim_file)

    new_text = text
    changed = False
    for cls_key, cls_spec in _specs_by_class(raw_spec).items():
        target = _resolve_class(classes, cls_key or args.cls)
        if target is None:
            _eprint("error: could not resolve target class %r — pass --class explicitly "
                    "(%d instantiable classes)"
                    % (cls_key or args.cls, len(_model_classes(classes))))
            return 2
        try:
            warns = fig_mod.validate_spec(cls_spec, known_vars=known, protected_vars=protected)
            arr = fig_mod.render_figures_array(cls_spec["figures"])
        except (fig_mod.SpecError, ValueError) as e:
            _eprint("error: invalid spec for class %s: %s" % (target.name, e))
            return 1
        for w in warns:
            _eprint("warning [%s]: %s" % (target.name, w))
        # re-parse against the evolving text so spans stay valid across multiple
        # classes; match by qualified name so same-leaf classes aren't confused.
        target_q = _qualified_name(classes, _index_of(classes, target))
        fresh = parse(new_text)
        live = next((c for i, c in enumerate(fresh)
                     if _qualified_name(fresh, i) == target_q and c.kind == target.kind), None)
        if live is None:
            _eprint("error: lost track of class %s after editing" % target.name)
            return 1
        new_text, status = inject_figures(new_text, live, arr, force=args.force)
        _eprint("%s: %s" % (target.name, status))
        changed = changed or status != "skipped"

    if not changed:
        _eprint("nothing to do (already annotated; use --force to regenerate)")
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
    p = argparse.ArgumentParser(prog="PlotAnnotate.main",
                                description="Add standardized result-plot annotations to a .mo")
    p.add_argument("--file", required=True, help="the .mo file")
    p.add_argument("--class", dest="cls", default=None,
                   help="target class (simple or dotted); default the sole model class")
    p.add_argument("--analyze", action="store_true", help="list classes and figure status")
    p.add_argument("--suggest", action="store_true",
                   help="print a suggested figures spec from --vars-file (no edits)")
    p.add_argument("--annotate", action="store_true", help="inject figures from --spec")
    p.add_argument("--write", action="store_true", help="apply edits (default is a dry-run diff)")
    p.add_argument("--force", action="store_true", help="regenerate even if figures already exist")
    p.add_argument("--spec", default=None, help="figures-spec JSON path")
    p.add_argument("--vars-file", dest="vars_file", default=None,
                   help="newline list of result variables (for --suggest and membership checks)")
    p.add_argument("--sim-file", dest="sim_file", default=None,
                   help="the .sim file beside the result .mat; its protected variables are "
                        "dropped from --suggest and flagged during --annotate")
    p.add_argument("--max-curves", dest="max_curves", type=int, default=8,
                   help="cap for --suggest (default 8)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # newline="" keeps the raw line endings so the file's own EOL can be restored on write
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
    except OSError as e:
        _eprint("error: cannot read %s: %s" % (args.file, e))
        return 2
    eol = dominant_eol(raw)
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Surface a malformed model, an unreadable/bad spec/vars/sim file, or invalid
    # JSON/XML as a clean 'error:' with exit 2 instead of an uncaught traceback.
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
