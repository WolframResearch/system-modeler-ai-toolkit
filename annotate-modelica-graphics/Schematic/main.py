"""CLI for the schematic annotator.

Usage (run from this skill's directory so the ``Schematic`` package is importable):

    python3 -m Schematic.main --file Model.mo --analyze
    python3 -m Schematic.main --file Model.mo --annotate          # dry-run diff
    python3 -m Schematic.main --file Model.mo --annotate --write   # apply in place
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys

# Output (dry-run diffs, em dashes) may contain non-ASCII; force UTF-8 so it
# doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from . import colors
from . import icon as icon_mod
from . import inject
from .classify import classify
from .parser import parse, ParseError
from mo_edit import dominant_eol, write_atomic  # importable once .parser has run


def _pos_int(text):
    """argparse type for --extent: a positive half-width (0/negative are degenerate)."""
    val = int(text)
    if val <= 0:
        raise argparse.ArgumentTypeError("must be > 0, got %s" % text)
    return val


def _analyze(text: str) -> int:
    classes = parse(text)
    print("%-22s %-13s %-26s %-7s %-8s" % ("class", "category", "standard icon", "custom", "diagram"))
    print("-" * 80)
    needs_glyph = []
    for c in classes:
        p = classify(c)
        print("%-22s %-13s %-26s %-7s %-8s"
              % (c.name, p.category, str(p.standard_icon), p.wants_custom_icon, p.wants_diagram))
        detail = []
        if c.connectors:
            detail.append("connectors: " + ", ".join(x.name for x in c.connectors))
        if c.instances:
            detail.append("instances: %d" % len(c.instances))
        if c.connects:
            detail.append("connects: %d" % len(c.connects))
        if detail:
            print("    " + " | ".join(detail))
        print("    -> %s" % p.reason)
        if p.wants_custom_icon:
            if c.kind == "connector":
                domain = colors.name_for(colors.color_for_type(c.name))
                if domain == "unknown":
                    print("    glyph: neutral connector square (domain unrecognized — author a "
                          "symbol from the name/description via --glyphs-file)")
                    needs_glyph.append(c.name)
                else:
                    print("    glyph: connector square (%s)" % domain)
            else:
                device = icon_mod._device_kind(c)
                if device == "block":
                    print("    glyph: generic block (domain unrecognized — author one from the "
                          "name/description via --glyphs-file)")
                    needs_glyph.append(c.name)
                else:
                    print("    glyph: %s" % device)
    if needs_glyph:
        print("\nUnrecognized classes/connectors (generic fallback icon): %s" % ", ".join(needs_glyph))
        print("ACTION: for each, read its name/description and author a representative glyph from "
              "Modelica primitives,\nthen pass --glyphs-file. JSON shape:")
        print('  {"%s": {"graphics": ["Rectangle(...)", "Line(...)"], '
              '"ports": {"port_a": "L"}}}' % needs_glyph[0])
    return 0


def _load_glyphs(path: str | None) -> dict:
    """Load an LLM-authored glyph spec file: {ClassName: {graphics:[...], ports:{...}}}.

    A bare list value is accepted as graphics-only. Returns {} if no path given.
    """
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    glyphs = {}
    for name, spec in raw.items():
        if isinstance(spec, list):
            glyphs[name] = {"graphics": spec}
        elif isinstance(spec, dict) and spec.get("graphics"):
            glyphs[name] = spec
        else:
            raise ValueError("glyph for %r must be a list of primitives or a dict with "
                             "a 'graphics' list" % name)
    return glyphs


def _annotate(path: str, text: str, opts: dict, write: bool, eol: str = "\n") -> int:
    new_text, summaries = inject.annotate(text, opts)
    only = opts.get("only_class")
    if only and not summaries:
        print("ERROR: --class %r matched no class in %s" % (only, path), file=sys.stderr)
        return 2
    for s in summaries:
        acts = ", ".join(s["actions"]) or "skip"
        print("  %-22s %s" % (s["name"], acts))
    if new_text == text:
        print("\nNo changes (already annotated, or nothing to do). Use --force to regenerate.")
        return 0
    if write:
        write_atomic(path, new_text, eol)
        print("\nWrote annotations to %s" % path)
    else:
        diff = difflib.unified_diff(
            text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=path, tofile=path + " (annotated)")
        sys.stdout.writelines(diff)
        print("\n(dry run — re-run with --write to apply)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Add Modelica Icon/Diagram annotations to a text model.")
    ap.add_argument("--file", "-f", required=True, help="Path to the .mo file")
    ap.add_argument("--analyze", action="store_true", help="Report classes and what each would receive")
    ap.add_argument("--annotate", action="store_true", help="Generate annotations (dry-run diff by default)")
    ap.add_argument("--write", action="store_true", help="Apply edits in place (with --annotate)")
    ap.add_argument("--force", action="store_true",
                    help="Strip ALL Placement/Line/Icon/Diagram annotations and "
                         "'extends Modelica.Icons.*' (hand-written included) and regenerate")
    ap.add_argument("--class", dest="only_class", default=None, help="Restrict to one nested class")
    ap.add_argument("--extent", type=_pos_int, default=None, help="Override the diagram half-width")
    ap.add_argument("--no-glyphs", action="store_true", help="Use plain rectangles instead of typed glyphs")
    ap.add_argument("--glyphs-file", dest="glyphs_file", default=None,
                    help="JSON of LLM-authored icon glyphs: {ClassName: {graphics:[...], ports:{...}}}")
    args = ap.parse_args(argv)

    try:
        # newline="" keeps the raw line endings so the file's own EOL can be restored on write
        with open(args.file, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
    except OSError as e:
        print("ERROR: cannot read %s: %s" % (args.file, e), file=sys.stderr)
        return 2
    eol = dominant_eol(raw)
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    try:
        glyphs = _load_glyphs(args.glyphs_file)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("ERROR: cannot load --glyphs-file %s: %s" % (args.glyphs_file, e), file=sys.stderr)
        return 2

    opts = {
        "force": args.force,
        "only_class": args.only_class,
        "extent": args.extent,
        "no_glyphs": args.no_glyphs,
        "glyphs": glyphs,
    }

    try:
        if args.analyze and not args.annotate:
            return _analyze(text)
        if args.annotate:
            return _annotate(args.file, text, opts, args.write, eol)
        # default: analyze
        return _analyze(text)
    except ParseError as e:
        print("ERROR: cannot parse %s: %s" % (args.file, e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
