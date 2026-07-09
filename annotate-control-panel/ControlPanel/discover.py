"""Discover a class's controllable variables — its ``parameter`` declarations — from the model
source. The shared parser records placeable *components* but not plain parameters, so this scans
the class body directly (on a masked copy, so brackets/`;` inside strings and comments can't
confuse it) and returns each parameter's name, declared type, default, and description.

This is a *starting point* for suggestions; the caller refines. A ``.sim`` file (see
:mod:`simvars`) gives the authoritative flattened list with runtime-tunability, and should be
preferred for validation when available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import mask_code

_IDENT = r"(?:'[^'\n]+'|[A-Za-z_]\w*)"
# `parameter` variability prefix, optionally preceded/followed by causality/connection prefixes,
# then the type name and the first declared identifier.
_PARAM_RE = re.compile(
    r"\bparameter\s+(?:(?:input|output|flow|stream|discrete)\s+)*"
    r"(?P<type>[\w.]+)\s+(?P<name>" + _IDENT + r")")
_DESC_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*$')

_NUMERIC_TYPES = {"Real", "Integer"}


@dataclass
class Param:
    name: str
    type_name: str
    default: str = ""
    description: str = ""

    @property
    def base_kind(self) -> str:
        """One of 'boolean' | 'numeric' | 'string' | 'other' (for choosing a control type)."""
        t = self.type_name
        last = t.split(".")[-1]
        if last == "Boolean":
            return "boolean"
        if last == "String":
            return "string"
        if last in _NUMERIC_TYPES or any(p in t for p in ("Units.SI", "SIunits", "Units.NonSI")):
            return "numeric"
        return "other"

    @property
    def default_number(self):
        """The default parsed as a float, or None if it isn't a plain numeric literal."""
        try:
            return float(self.default)
        except (TypeError, ValueError):
            return None


def _top_level_statements(mask: str, start: int, end: int):
    """Yield (s, e) spans of ``;``-terminated statements at bracket depth 0 in ``mask[start:end]``."""
    depth = 0
    s = start
    for i in range(start, end):
        ch = mask[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            yield s, i
            s = i + 1


def _default_expr(text: str, mask: str, s: int, e: int, name_end: int, desc_start: int) -> str:
    """Text of the ``= <expr>`` default in a declaration statement, or ''.
    Skips an optional subscript ``[...]`` and modification ``(...)`` after the name, then takes
    everything from the top-level ``=`` up to the description string."""
    i = name_end
    limit = desc_start if desc_start != -1 else e
    while i < limit and mask[i].isspace():
        i += 1
    for opener in ("[", "("):
        if i < limit and mask[i] == opener:
            depth = 0
            while i < limit:
                if mask[i] in "([{":
                    depth += 1
                elif mask[i] in ")]}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            while i < limit and mask[i].isspace():
                i += 1
    if i < limit and mask[i] == "=":
        return text[i + 1:limit].strip()
    return ""


def find_parameters(text: str, cls, child_ranges=()) -> list:
    """Return the :class:`Param` list declared directly in ``cls`` (skipping nested-class ranges).

    ``child_ranges`` is an iterable of ``(start, end)`` spans of nested classes to ignore, so a
    subclass's parameters aren't attributed to this class."""
    mask = mask_code(text)
    out = []
    for s, e in _top_level_statements(mask, cls.body_start, cls.body_end):
        if any(cs <= s < ce for cs, ce in child_ranges):
            continue
        m = _PARAM_RE.search(mask, s, e)
        if not m:
            continue
        stmt = text[s:e]
        dm = _DESC_RE.search(stmt)
        description = dm.group(1) if dm else ""
        desc_start = s + dm.start() if dm else -1
        default = _default_expr(text, mask, m.start(), e, m.end("name"), desc_start)
        out.append(Param(name=m.group("name").strip("'"), type_name=m.group("type"),
                         default=default, description=description))
    return out
