"""
Shared text-splicing primitives for the Modelica annotation skills.

The annotators (``annotate-modelica-graphics``, ``annotate-modelica-plots``, and
``annotate-control-panel``) compute their changes as ``(start, end, replacement)``
edits applied bottom-up, and all need the indentation at a position and the
bracket that matches a given opener. That machinery lives here so each skill's
``inject.py`` doesn't carry its own copy.

Standard-library only. Bracket matching counts all bracket kinds, so run it on a
masked copy of the source (strings/comments blanked, see ``modelica_parser`` /
``mask_code``) when literals might contain stray brackets.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass


@dataclass
class Edit:
    start: int
    end: int
    text: str


def splice(text: str, edits: list) -> str:
    """Apply ``edits`` to ``text``, highest start offset first so earlier offsets
    stay valid as the string is rewritten. Edit ranges must not overlap (raises
    ``ValueError``); insertions at the same offset come out in list order."""
    # Sort by (start, list index) descending: applying the later-listed edit first
    # leaves same-offset insertions in list order in the result.
    prev_start = None
    for _, e in sorted(enumerate(edits), key=lambda p: (p[1].start, p[0]), reverse=True):
        if e.end < e.start:
            raise ValueError("invalid edit range (%d, %d)" % (e.start, e.end))
        if prev_start is not None and e.end > prev_start:
            raise ValueError("overlapping edits at (%d, %d)" % (e.start, e.end))
        prev_start = e.start
        text = text[:e.start] + e.text + text[e.end:]
    return text


def indent_at(text: str, pos: int) -> str:
    """The leading whitespace of the line containing ``pos``."""
    line = text[text.rfind("\n", 0, pos) + 1:pos]
    return line[:len(line) - len(line.lstrip())]


_OPENERS, _CLOSERS = "([{", ")]}"


def balanced_close(s: str, open_idx: int) -> int:
    """Index of the bracket matching ``s[open_idx]``, or -1 if that position is not
    an opener or has no match. Counts all bracket kinds, so it relies on the source
    being well-formed — pass a masked copy so brackets inside literals can't
    unbalance the scan."""
    if open_idx < 0 or open_idx >= len(s) or s[open_idx] not in _OPENERS:
        return -1
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] in _OPENERS:
            depth += 1
        elif s[i] in _CLOSERS:
            depth -= 1
            if depth == 0:
                return i
    return -1


def find_call_open(mask: str, start: int, end: int, keyword: str) -> int:
    """Index of the ``(`` that opens ``keyword(`` within ``mask[start:end]``, or -1."""
    m = re.compile(r"\b" + re.escape(keyword) + r"\s*\(").search(mask, start, end)
    return m.end() - 1 if m else -1


def dominant_eol(raw: str) -> str:
    """The dominant line ending of ``raw`` (read with ``newline=""``): CRLF or LF."""
    crlf = raw.count("\r\n")
    return "\r\n" if crlf > raw.count("\n") - crlf else "\n"


def write_atomic(path: str, text: str, eol: str = "\n") -> None:
    """Atomically replace ``path`` with ``text``, written with ``eol`` line endings.
    Writes a temp file in the same directory, fsyncs, then os.replace()s it over the
    target so a crash mid-write can't leave a truncated file."""
    # Normalize to LF first so re-applying eol can't produce \r\r\n if the caller
    # passed text that still contains CRLF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if eol != "\n":
        text = text.replace("\n", eol)
    # Resolve a symlink to its target so we write THROUGH the link (and place the
    # temp beside the real file, on its filesystem) instead of replacing the link.
    real = os.path.realpath(path)
    directory = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(real) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
