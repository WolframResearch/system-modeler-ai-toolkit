"""Splice generated annotations back into the original source.

Edits are computed as (start, end, replacement) triples and applied bottom-up so earlier
offsets stay valid. Sites that are already annotated are skipped (idempotent); ``--force``
first strips every Placement/Line annotation, Icon/Diagram class-annotation element and
``extends Modelica.Icons.*;`` line — hand-written ones included, since generated output
carries no marker — and then re-applies.
"""

from __future__ import annotations

import re

from . import icon as icon_mod
from . import layout as layout_mod
from . import routing as routing_mod
from .classify import classify
from .parser import ClassSpan, QUALIFIERS, mask_code, parse
from mo_edit import Edit, splice, indent_at as _indent_at, balanced_close, find_call_open


# ---------------------------------------------------------------------------
# small text helpers
# ---------------------------------------------------------------------------

def _box(x: int, y: int) -> str:
    return "extent={{%d,%d},{%d,%d}}" % (x - 10, y - 10, x + 10, y + 10)


def _connector_placement(icon_pt, diag_pt) -> str:
    ix, iy = icon_pt
    dx, dy = diag_pt if diag_pt is not None else icon_pt
    return ("Placement(transformation(%s), iconTransformation(%s))"
            % (_box(dx, dy), _box(ix, iy)))


# ---------------------------------------------------------------------------
# per-class edit construction
# ---------------------------------------------------------------------------

def build_class_edits(text: str, mask: str, cls: ClassSpan, opts: dict) -> tuple:
    """Return (edits, summary_dict) for one class. ``mask`` is ``mask_code(text)``."""
    plan = classify(cls)
    edits = []
    summary = {"name": cls.name, "actions": [], "reason": plan.reason}
    if plan.is_noop:
        summary["actions"].append("skip")
        return edits, summary

    no_glyphs = opts.get("no_glyphs", False)

    # ---- 1. standard Icons.* base via extends -------------------------------
    if plan.standard_icon:
        indent = _indent_at(text, cls.body_start) + "  "
        ins = "\n%sextends %s;" % (indent, plan.standard_icon)
        edits.append(Edit(cls.body_start, cls.body_start, ins))
        summary["actions"].append("extends %s" % plan.standard_icon)

    # ---- 2/3. class-level Icon / Diagram annotation -------------------------
    extra_elems = []
    icon_points = {}
    layout_res = None

    if plan.wants_custom_icon and not cls.has_icon:
        custom = (opts.get("glyphs") or {}).get(cls.name)
        icon_block, icon_points = icon_mod.build_icon(cls, no_glyphs=no_glyphs, custom=custom)
        extra_elems.append(icon_block)
        summary["actions"].append("custom Icon (authored)" if custom else "custom Icon")

    if plan.wants_diagram:
        layout_res = layout_mod.compute_layout(cls, opts.get("type_ports"))
        (x1, y1), (x2, y2) = layout_res["extent"]
        if opts.get("extent") is not None:   # 0 is invalid, rejected by the CLI validator
            n = abs(opts["extent"])
            x1, y1, x2, y2 = -n, -n, n, n
        if not cls.has_diagram:
            extra_elems.append(
                "Diagram(coordinateSystem(preserveAspectRatio=false, "
                "extent={{%d,%d},{%d,%d}}))" % (x1, y1, x2, y2))
            summary["actions"].append("Diagram layout (%d comps)" % len(cls.instances))

    if extra_elems:
        edits.append(_class_annotation_edit(text, mask, cls, extra_elems))

    # ---- 4. connectors: Placement (icon + diagram boxes) --------------------
    if (plan.wants_custom_icon or plan.wants_diagram) and cls.connectors:
        if not icon_points:
            icon_points = icon_mod.assign_connector_edges(cls.connectors, "block")
        diag_points = layout_res["connectors"] if layout_res else {}
        cedits, ncon = _decl_group_edits(
            text, mask, cls.connectors,
            lambda c: _connector_placement(icon_points.get(c.name, (-100, 0)),
                                           diag_points.get(c.name)))
        edits += cedits
        if ncon:
            summary["actions"].append("%d connector Placement" % ncon)

    # ---- 5. instances: Placement -------------------------------------------
    if plan.wants_diagram and layout_res:
        placements = layout_res["instances"]

        def inst_ann(inst):
            ox, oy, rot = placements.get(inst.name, (0, 0, 0))
            return layout_mod.instance_placement(ox, oy, rot)
        iedits, ninst = _decl_group_edits(text, mask, cls.instances, inst_ann)
        edits += iedits
        if ninst:
            summary["actions"].append("%d Placement" % ninst)

        # ---- 6. connects: Line ---------------------------------------------
        n_lines = 0
        for cn in cls.connects:
            # under --force the stripper ran first; a surviving Line/annotation is
            # hand-written, and a connect must not get a second annotation clause
            if cn.has_line:
                continue
            line = routing_mod.line_for(cn, cls, layout_res)
            edits.append(Edit(cn.semicolon, cn.semicolon, " annotation(%s)" % line))
            n_lines += 1
        if n_lines:
            summary["actions"].append("%d Line" % n_lines)

    return edits, summary


def _class_annotation_edit(text: str, mask: str, cls: ClassSpan, elems: list) -> Edit:
    joined = ",\n    ".join(elems)
    if cls.annotation_end > 0:                       # merge into existing annotation
        ann_open = find_call_open(mask, cls.annotation_start, cls.annotation_end + 1,
                                  "annotation")
        close = balanced_close(mask, ann_open)
        if close != -1:
            # no leading comma when the annotation is empty (e.g. after --force stripping)
            empty = mask[ann_open + 1:close].strip() == ""
            return Edit(close, close, ("\n    " if empty else ",\n    ") + joined)
    # otherwise create a fresh annotation before 'end Name;'
    indent = _indent_at(text, cls.header_start) + "  "
    block = "\n%sannotation(\n    %s);\n%s" % (indent, joined, indent)
    return Edit(cls.body_end, cls.body_end, block)


def _decl_group_edits(text: str, mask: str, members: list, ann_fn) -> tuple:
    """Add Placement to component/connector declarations, splitting multi-name decls so
    each member gets its own placement. ``members`` are Connector or Instance objects.
    Declarations that still carry a Placement are skipped — under ``--force`` the stripper
    runs first, so anything left is hand-written and must not get a second annotation clause.
    Returns (edits, n_declarations_edited)."""
    edits = []
    n = 0
    # group members by their shared declaration (decl_start)
    groups = {}
    for m in members:
        groups.setdefault(m.decl_start, []).append(m)

    for decl_start, group in groups.items():
        rep = group[0]
        if rep.has_placement:
            continue
        n += len(group)
        if len(group) == 1:
            # single declaration: insert the annotation just before the ';'
            ann = " annotation(%s)" % ann_fn(group[0])
            edits.append(Edit(rep.semicolon, rep.semicolon, ann))
        else:
            # multi-name declaration: rewrite as one declaration per member, reusing each
            # member's own declarator text (name + subscript + modification) verbatim so
            # one member's modifications are never cross-applied to its siblings.
            indent = _indent_at(text, rep.core_start)
            # prefix keywords (replaceable, inner, final, ...) precede the type token; the
            # first member keeps the originals in place, every split-off one repeats them
            prefix = " ".join(w for w in mask[rep.decl_start:rep.core_start].split()
                              if w in QUALIFIERS)
            prefix = prefix + " " if prefix else ""
            desc = ' "%s"' % rep.description if rep.description else ""
            parts = []
            for k, m in enumerate(group):
                decl = getattr(m, "decl_text", "") or m.name
                parts.append("%s%s %s%s annotation(%s)"
                             % (prefix if k else "", m.type_name, decl, desc, ann_fn(m)))
            replacement = (";\n%s" % indent).join(parts)
            edits.append(Edit(rep.core_start, rep.semicolon, replacement))
    return edits, n


# ---------------------------------------------------------------------------
# force: strip previously generated annotations
# ---------------------------------------------------------------------------

def strip_generated(text: str) -> str:
    """Remove the annotation kinds this tool generates, so --force can regenerate them.

    The tool leaves no marker in its output, so matching is by shape, not provenance:
    EVERY ``annotation(Placement(...))`` / ``annotation(Line(...))`` clause, every
    ``Icon(...)`` / ``Diagram(...)`` element of a class annotation and every
    ``extends Modelica.Icons.*;`` line is removed — hand-written ones included.
    All scanning runs on a masked copy (see ``mask_code``) so brackets inside string
    literals or comments can't derail the removal."""
    text = _remove_balanced(text, r"\bannotation\s*\(\s*Placement\s*\(")
    text = _remove_balanced(text, r"\bannotation\s*\(\s*Line\s*\(")
    # remove extends Icons.* lines
    mask = mask_code(text)
    spans = [m.span() for m in
             re.finditer(r"\n[ \t]*extends\s+Modelica\.Icons\.\w+\s*;", mask)]
    for s, e in reversed(spans):
        text = text[:s] + text[e:]
    # remove Icon(...) / Diagram(...) elements inside class annotations
    for pat in (r"\bIcon\s*\(", r"\bDiagram\s*\("):
        text = _remove_element(text, pat)
    # a class whose only annotation was its Icon/Diagram is now left with a bare
    # `annotation()`, which is invalid Modelica — drop the empty wrapper.
    return _remove_empty_annotations(text)


def _remove_empty_annotations(text: str) -> str:
    """Delete any ``annotation(...)`` whose body is now empty (all generated elements
    stripped), including a trailing ';' and a leading space."""
    rx = re.compile(r"\bannotation\s*\(")
    while True:
        mask = mask_code(text)
        removed = False
        for m in rx.finditer(mask):
            open_paren = mask.index("(", m.start())
            close = balanced_close(mask, open_paren)
            if close == -1 or mask[open_paren + 1:close].strip() != "":
                continue
            s, e = m.start(), close + 1
            if s > 0 and text[s - 1] == " ":
                s -= 1
            es = e
            while es < len(text) and text[es] in " \n\t":
                es += 1
            if es < len(text) and text[es] == ";":
                e = es + 1
            text = text[:s] + text[e:]
            removed = True
            break
        if not removed:
            return text


def _find_balanced(text: str, rx: re.Pattern) -> tuple:
    """First match of ``rx`` in the masked text plus the index of the ')' balancing the
    match's last '('. Returns (start, close) or (-1, -1). Scanning the mask keeps brackets
    inside strings/comments from unbalancing the count; the offsets index ``text``."""
    mask = mask_code(text)
    m = rx.search(mask)
    if m is None:
        return -1, -1
    close = balanced_close(mask, m.end() - 1)
    if close == -1:
        return -1, -1
    return m.start(), close


def _remove_balanced(text: str, pattern: str) -> str:
    """Remove every occurrence of ``pattern`` (ending in an opening '(') through the ')'
    balancing the FIRST '(' of the match — i.e. the whole annotation clause."""
    rx = re.compile(pattern)
    while True:
        mask = mask_code(text)
        m = rx.search(mask)
        if m is None:
            break
        end = balanced_close(mask, mask.index("(", m.start()))
        if end == -1:
            break
        seg_start = m.start()
        # also swallow a leading space if the annotation was inserted as ' annotation(...)'
        if seg_start > 0 and text[seg_start - 1] == " ":
            seg_start -= 1
        text = text[:seg_start] + text[end + 1:]
    return text


def _remove_element(text: str, pattern: str) -> str:
    """Remove a ``kw(...)`` element plus a trailing/leading comma inside a class annotation."""
    rx = re.compile(pattern)
    while True:
        s, end = _find_balanced(text, rx)
        if s == -1:
            break
        e = end + 1
        # consume one adjacent comma (prefer the leading one)
        ls = s
        while ls > 0 and text[ls - 1] in " \n\t":
            ls -= 1
        if ls > 0 and text[ls - 1] == ",":
            s = ls - 1
        else:
            es = e
            while es < len(text) and text[es] in " \n\t":
                es += 1
            if es < len(text) and text[es] == ",":
                e = es + 1
        text = text[:s] + text[e:]
    return text


# ---------------------------------------------------------------------------
# top-level
# ---------------------------------------------------------------------------

def _build_type_ports(classes: list, glyphs: dict | None = None) -> dict:
    """Map each class's leaf name -> {connector: (px,py)} in the ±100 icon frame.

    Connector edges are assigned exactly as the icon builder does, so a connection routed to
    an *instance* of one of these types lands on the same pin the icon draws. A class with no
    own connectors inherits them from an extended base (one level), which is what lets
    instances of a thin ``extends`` (e.g. a behavioral OTA extending a PartialOTA) be routed.
    """
    have = {c.name: c for c in classes if c.connectors}
    tp = {}
    for c in classes:
        conns, src = c.connectors, c
        if not conns:
            for base in c.extends:
                b = have.get(base.split(".")[-1])
                if b:
                    conns, src = b.connectors, b
                    break
        if conns:
            spec = (glyphs or {}).get(c.name) or (glyphs or {}).get(src.name)
            overrides = spec.get("ports") if spec else None
            tp[c.name] = icon_mod.assign_connector_edges(
                conns, "custom" if spec else icon_mod._device_kind(src), overrides)
    return tp


def annotate(text: str, opts: dict | None = None) -> tuple:
    """Annotate the whole file. Returns (new_text, summaries)."""
    opts = opts or {}
    only = opts.get("only_class")
    if opts.get("force"):
        if only:
            # Strip only within the target class's span, so `--force --class X`
            # can't wipe (and, per the empty-wrapper case, invalidate) other classes.
            target = next((c for c in parse(text) if c.name == only), None)
            if target is not None:
                s, e = target.header_start, target.full_end
                text = text[:s] + strip_generated(text[s:e]) + text[e:]
        else:
            text = strip_generated(text)
    mask = mask_code(text)
    classes = parse(text)
    opts = {**opts, "type_ports": _build_type_ports(classes, opts.get("glyphs"))}
    all_edits = []
    summaries = []
    for cls in classes:
        if only and cls.name != only:
            continue
        edits, summary = build_class_edits(text, mask, cls, opts)
        all_edits += edits
        summaries.append(summary)
    return splice(text, all_edits), summaries
