"""Splice a ``figures = {...}`` annotation into a class's source.

All bracket matching runs on a masked copy of the source (strings/comments blanked, see
:func:`parser.mask_code`) so parentheses or braces inside a doc-string never throw it off.
Placement, in order: inside an existing ``Documentation(...)``; into a bare ``annotation(...)``;
or a fresh ``annotation`` before ``end Name;``. Idempotent unless ``force``, which strips the
existing ``figures`` assignment first.
"""

from __future__ import annotations

import re

from .parser import ClassSpan, mask_code, parse
from mo_edit import (Edit, splice, indent_at as _indent_at,
                     balanced_close as _balanced_close, find_call_open as _find_call_open)


def _strip_figures(text: str, doc_open: int, doc_close: int) -> str:
    """Remove a ``figures = {...}`` assignment between the Documentation parens, plus one comma."""
    mask = mask_code(text)
    m = re.compile(r"\bfigures\s*=\s*").search(mask, doc_open, doc_close)
    if not m:
        return text
    brace = mask.find("{", m.end(), doc_close)
    close = _balanced_close(mask, brace) if brace != -1 else -1
    if close == -1:
        return text
    s, e = m.start(), close + 1
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
    return text[:s] + text[e:]


def inject_figures(text: str, cls: ClassSpan, figures_text: str, force: bool = False) -> tuple:
    """Return ``(new_text, status)`` with status ``added`` / ``skipped`` / ``regenerated``.
    ``figures_text`` is the rendered ``{Figure(...)}`` array."""
    if cls.has_figures and not force:
        return text, "skipped"

    if cls.has_figures and force:
        mask = mask_code(text)
        doc_open = _find_call_open(mask, cls.annotation_start, cls.annotation_end + 1,
                                   "Documentation")
        if doc_open != -1:
            text = _strip_figures(text, doc_open, _balanced_close(mask, doc_open))
        cls = next((c for c in parse(text)
                    if c.name == cls.name and c.kind == cls.kind), cls)
        status = "regenerated"
    else:
        status = "added"

    mask = mask_code(text)
    ind = _indent_at(text, cls.annotation_start)

    if cls.annotation_end > 0:
        doc_open = _find_call_open(mask, cls.annotation_start, cls.annotation_end + 1,
                                   "Documentation")
        if doc_open != -1:
            close = _balanced_close(mask, doc_open)
            empty = mask[doc_open + 1:close].strip() == ""
            payload = "figures = %s" % figures_text
            ins = ("\n%s    %s\n%s  " % (ind, payload, ind)) if empty \
                else (",\n%s    %s" % (ind, payload))
            return splice(text, [Edit(close, close, ins)]), status

        ann_open = _find_call_open(mask, cls.annotation_start, cls.annotation_end + 1,
                                   "annotation")
        if ann_open != -1:
            close = _balanced_close(mask, ann_open)
            empty = mask[ann_open + 1:close].strip() == ""
            payload = "Documentation(figures = %s)" % figures_text
            ins = ("\n%s  %s\n%s" % (ind, payload, ind)) if empty \
                else (",\n%s  %s" % (ind, payload))
            return splice(text, [Edit(close, close, ins)]), status

    base = _indent_at(text, cls.header_start)
    block = "\n%s  annotation(Documentation(figures = %s));\n%s" % (base, figures_text, base)
    return splice(text, [Edit(cls.body_end, cls.body_end, block)]), status
