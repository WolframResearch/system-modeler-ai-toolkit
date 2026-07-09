"""Splice a ``__Wolfram(ControlPanels(...))`` vendor annotation into a class's source.

Unlike a figures annotation (which lives inside ``Documentation(...)``), the control-panel
annotation is a **direct child of** ``annotation(...)`` — a sibling of ``experiment`` /
``Documentation``. Placement, in order: into an existing ``annotation(...)``; or a fresh
``annotation(__Wolfram(ControlPanels(...)));`` before ``end Name;``. All bracket matching runs on
a masked copy so parentheses/braces inside a doc-string never throw it off. Idempotent unless
``force``, which first strips the existing ``ControlPanels`` block (and an emptied ``__Wolfram``
wrapper).
"""

from __future__ import annotations

import re

from .parser import ClassSpan, mask_code, parse
from mo_edit import (Edit, splice, indent_at as _indent_at,
                     balanced_close as _balanced_close, find_call_open as _find_call_open)

_CP_RE = re.compile(r"\bControlPanels\s*\(")
_EMPTY_WOLFRAM_RE = re.compile(r"\b__Wolfram\s*\(\s*\)")


def _has_panels(text: str, cls: ClassSpan) -> bool:
    if cls.annotation_end <= 0:
        return False
    mask = mask_code(text)
    return _CP_RE.search(mask, cls.annotation_start, cls.annotation_end + 1) is not None


def _cut_with_comma(text: str, s: int, e: int) -> str:
    """Remove ``text[s:e]`` plus one adjacent comma (preferring the one before)."""
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


def _strip_panels(text: str, cls: ClassSpan) -> str:
    """Remove the ``ControlPanels(...)`` call from the class annotation, plus an emptied
    ``__Wolfram(...)`` wrapper. Leaves any other vendor content in ``__Wolfram`` intact."""
    mask = mask_code(text)
    m = _CP_RE.search(mask, cls.annotation_start, cls.annotation_end + 1)
    if not m:
        return text
    close = _balanced_close(mask, m.end() - 1)
    if close == -1:
        return text
    text = _cut_with_comma(text, m.start(), close + 1)
    mask = mask_code(text)
    em = _EMPTY_WOLFRAM_RE.search(mask)
    if em:
        text = _cut_with_comma(text, em.start(), em.end())
    return text


def inject_control_panels(text: str, cls: ClassSpan, panels_text: str,
                          force: bool = False) -> tuple:
    """Return ``(new_text, status)`` with status ``added`` / ``skipped`` / ``regenerated``.
    ``panels_text`` is the rendered ``__Wolfram(ControlPanels(...))`` element."""
    has = _has_panels(text, cls)
    if has and not force:
        return text, "skipped"

    if has and force:
        text = _strip_panels(text, cls)
        cls = next((c for c in parse(text) if c.name == cls.name and c.kind == cls.kind), cls)
        status = "regenerated"
    else:
        status = "added"

    mask = mask_code(text)
    ind = _indent_at(text, cls.annotation_start)

    if cls.annotation_end > 0:
        ann_open = _find_call_open(mask, cls.annotation_start, cls.annotation_end + 1,
                                   "annotation")
        if ann_open != -1:
            close = _balanced_close(mask, ann_open)
            empty = mask[ann_open + 1:close].strip() == ""
            ins = ("\n%s  %s\n%s" % (ind, panels_text, ind)) if empty \
                else (",\n%s  %s" % (ind, panels_text))
            return splice(text, [Edit(close, close, ins)]), status

    base = _indent_at(text, cls.header_start)
    block = "\n%s  annotation(%s);\n%s" % (base, panels_text, base)
    return splice(text, [Edit(cls.body_end, cls.body_end, block)]), status
