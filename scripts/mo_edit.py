"""
Shared text-splicing primitives for the Modelica annotation skills.

The annotators (``annotate-modelica-graphics``, ``annotate-modelica-plots``, and
``annotate-control-panel``) compute their changes as ``(start, end, replacement)``
edits applied bottom-up, and all need the indentation at a position and the
bracket that matches a given opener. That machinery lives here so each skill's
``inject.py`` doesn't carry its own copy.

It also carries the line-ending handling every ``.mo`` writer needs: read with
``read_raw``, edit as LF, write back through ``write_atomic`` with the file's own
``dominant_eol``. Run as a script it exposes that as ``--eol`` / ``--set-eol``,
for checking or restoring a file's line endings around a hand-made edit.

Standard-library only. Bracket matching counts all bracket kinds, so run it on a
masked copy of the source (strings/comments blanked, see ``modelica_parser`` /
``mask_code``) when literals might contain stray brackets.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import stat
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


def read_raw(path: str) -> str:
    """Read ``path`` without newline translation, so the file's own line endings
    survive into the returned text and can be restored on write."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def eol_counts(raw: str) -> tuple:
    """``(crlf, lf)`` line-ending counts of ``raw`` (read with ``newline=""``).
    ``lf`` counts only bare LFs, so a file is mixed exactly when both are non-zero."""
    crlf = raw.count("\r\n")
    return crlf, raw.count("\n") - crlf


def dominant_eol(raw: str) -> str:
    """The dominant line ending of ``raw`` (read with ``newline=""``): CRLF or LF."""
    crlf, lf = eol_counts(raw)
    return "\r\n" if crlf > lf else "\n"


_LIB_SCAN_LIMIT = 500


def _library_root(directory: str) -> str | None:
    """The top of the directory-form library containing ``directory`` (the outermost
    enclosing folder chain that has a ``package.mo``), or None if there is none."""
    if not os.path.isfile(os.path.join(directory, "package.mo")):
        return None
    root = directory
    while True:
        parent = os.path.dirname(root)
        if parent == root or not os.path.isfile(os.path.join(parent, "package.mo")):
            return root
        root = parent


def _nearby_mo_files(path: str) -> list:
    """The ``.mo`` files whose convention ``path`` should follow: its whole
    directory-form library when one encloses it, else its own directory."""
    directory = os.path.dirname(path)
    root = _library_root(directory)
    if root is None:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return []
        return [os.path.join(directory, n) for n in names if n.endswith(".mo")]
    found = []
    for dirpath, dirnames, names in os.walk(root):
        dirnames.sort()
        for name in sorted(names):
            if name.endswith(".mo"):
                found.append(os.path.join(dirpath, name))
                if len(found) >= _LIB_SCAN_LIMIT:
                    return found
    return found


def neighbor_eol(path: str) -> str | None:
    """The line ending the ``.mo`` files around ``path`` agree on, or None if they
    give no clear answer. A neighbour that is itself mixed does not get a vote."""
    real = os.path.realpath(path)
    crlf = lf = 0
    for other in _nearby_mo_files(real):
        if os.path.realpath(other) == real:
            continue
        try:
            c, l = eol_counts(read_raw(other))
        except (OSError, UnicodeDecodeError):
            continue
        if c and l:
            continue
        if c:
            crlf += 1
        elif l:
            lf += 1
    if crlf == lf:
        return None
    return "\r\n" if crlf > lf else "\n"


def resolve_eol(path: str, raw: str) -> tuple:
    """The line ending ``path`` should be written back with, as ``(eol, note)``.

    A consistent file keeps its own ending. A **mixed** file does not: the mixing is
    damage, so its internal majority is not evidence of intent — the surrounding
    library decides, and the file's own dominant ending is only the fallback when
    there is nothing to compare against. ``note`` is a message to show, or None."""
    crlf, lf = eol_counts(raw)
    if not (crlf and lf):
        return dominant_eol(raw), None
    library = neighbor_eol(path)
    eol = library or dominant_eol(raw)
    why = ("the surrounding library uses it" if library else
           "it is this file's dominant ending — no sibling .mo file to compare with")
    return eol, ("NOTE: %s has mixed line endings (crlf=%d lf=%d); writing it back "
                 "gives the whole file %s, because %s."
                 % (path, crlf, lf, "CRLF" if eol == "\r\n" else "LF", why))


def read_for_edit(path: str) -> tuple:
    """Read ``path`` for an in-place edit. Returns ``(text, eol)``: ``text`` is
    LF-normalized so offsets and patterns need not care about line endings, and
    ``eol`` is what to hand back to ``write_atomic`` so the edit does not change the
    file's endings. See ``resolve_eol`` for how a mixed file is settled."""
    raw = read_raw(path)
    eol, note = resolve_eol(path, raw)
    if note:
        print(note, file=sys.stderr)
    return raw.replace("\r\n", "\n").replace("\r", "\n"), eol


def write_atomic(path: str, text: str, eol: str) -> None:
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
    try:
        mode = stat.S_IMODE(os.stat(real).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(real) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_EOL_NAMES = {"lf": "\n", "crlf": "\r\n"}


def describe_eol(raw: str) -> str:
    crlf, lf = eol_counts(raw)
    if crlf and lf:
        return "MIXED (crlf=%d lf=%d)" % (crlf, lf)
    if crlf:
        return "CRLF"
    return "LF" if lf else "NONE"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report or set the line endings of a text file.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--eol", action="store_true",
                      help="report each file's line endings; exit 1 if any file is mixed")
    mode.add_argument("--set-eol", choices=("auto", "lf", "crlf"), dest="set_eol",
                      help="rewrite each file with these line endings ('auto' keeps a "
                           "consistent file's own ending, and settles a mixed one on what "
                           "the surrounding library uses)")
    ap.add_argument("files", nargs="+", metavar="FILE")
    args = ap.parse_args(argv)

    status = 0
    for path in args.files:
        try:
            raw = read_raw(path)
        except (OSError, UnicodeDecodeError) as e:
            print("ERROR: cannot read %s: %s" % (path, e), file=sys.stderr)
            status = 2
            continue
        if args.eol:
            found = describe_eol(raw)
            print("%-28s %s" % (found, path))
            if found.startswith("MIXED") and status == 0:
                status = 1
            continue
        if args.set_eol == "auto":
            eol, note = resolve_eol(path, raw)
            if note:
                print(note, file=sys.stderr)
        else:
            eol = _EOL_NAMES[args.set_eol]
        try:
            write_atomic(path, raw, eol)
        except OSError as e:
            print("ERROR: cannot write %s: %s" % (path, e), file=sys.stderr)
            status = 2
            continue
        print("%-28s %s" % (describe_eol(read_raw(path)), path))
    return status


if __name__ == "__main__":
    sys.exit(main())
