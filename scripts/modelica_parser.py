"""Span-aware Modelica source parser — shared by the annotation skills.

This is the single, generic parser reused by ``annotate-modelica-graphics``,
``annotate-modelica-plots``, and any future skill that needs to splice annotations into a
``.mo``. Each skill's ``parser.py`` is a thin shim that re-exports this module, so the parsing
logic lives in exactly one place. It is stdlib-only and has no import-time side effects.

Unlike the regex/one-entity-per-file parser in ``create-hydraulic-model``, this scanner
returns **byte spans** into the original text so annotations can be spliced back in place,
and it handles a file that is a ``package`` with several nested ``model`` classes.

Strategy: build a length-preserving *mask* of the source in which string literals and
comments are blanked to spaces. All structural scanning runs on the mask (so a ``;`` or the
word ``model`` inside a doc string or comment is never mistaken for code), while spans index
the untouched original text.

``ClassSpan`` carries generic annotation-presence flags (``has_icon``, ``has_diagram``,
``has_experiment``, ``has_documentation``, ``has_figures``) so different skills can ask whatever
they need without each forking the parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ParseError(ValueError):
    """The source is malformed in a way that makes span-based annotation unsafe
    (an unterminated block comment or an unclosed class). Raised rather than
    returning a silently truncated parse a caller would mistake for an empty class."""


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

def mask_code(text: str) -> str:
    """Return a same-length copy of ``text`` with string literals and comments
    replaced by spaces (newlines preserved). Offsets are identical to ``text``.
    """
    out = list(text)
    i = 0
    n = len(text)
    NORMAL, LINE, BLOCK, STRING, QIDENT = 0, 1, 2, 3, 4
    state = NORMAL
    while i < n:
        ch = text[i]
        if state == NORMAL:
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                state = LINE
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                state = BLOCK
                continue
            if ch == '"':
                # keep the opening quote so we can still see decl shape; blank content
                state = STRING
                i += 1
                continue
            if ch == "'":
                # Modelica quoted identifier: keep word chars and spaces so the
                # header regexes still see the name, but blank anything that could
                # confuse structural scanning (e.g. an embedded '"' or ';').
                state = QIDENT
                i += 1
                continue
            i += 1
        elif state == LINE:
            if ch == "\n":
                state = NORMAL
            else:
                out[i] = " "
            i += 1
        elif state == BLOCK:
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                state = NORMAL
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
        elif state == STRING:
            if ch == "\\" and i + 1 < n:
                out[i] = " "
                out[i + 1] = " "
                i += 2
                continue
            if ch == '"':
                state = NORMAL
                i += 1
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
        elif state == QIDENT:
            if ch == "\\" and i + 1 < n:
                out[i] = " "
                out[i + 1] = " "
                i += 2
                continue
            if ch == "'":
                state = NORMAL
                i += 1
                continue
            if ch != "\n" and not (ch.isalnum() or ch in "_ "):
                out[i] = " "
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Type classification helpers
# ---------------------------------------------------------------------------

# A type is a connector if it names an interface/connector class.
CONNECTOR_SUFFIXES = (
    "Pin", "PositivePin", "NegativePin", "PositivePlug", "NegativePlug", "Plug",
    "Flange", "Flange_a", "Flange_b", "Frame", "Frame_a", "Frame_b",
    "RealInput", "RealOutput", "BooleanInput", "BooleanOutput",
    "IntegerInput", "IntegerOutput", "HeatPort", "HeatPort_a", "HeatPort_b",
)

# Domain-agnostic fallback: a type whose last segment ends in ``Port``/``Ports``
# (optionally ``_a``/``_b``) is, by overwhelming Modelica convention, a physical
# connector — fluid (``FluidPort_a``, ``VesselFluidPorts_b``), magnetic
# (``MagneticPort``), pneumatic, thermal (``HeatPort``), etc. The capital ``P`` keeps
# this from matching ordinary names like ``Support`` or ``Report``.
_PORT_SUFFIX_RE = re.compile(r"Ports?(?:_[ab])?$")

# A type used for ordinary variables/parameters (never a placeable component).
VALUE_TYPE_NAMES = {"Real", "Integer", "Boolean", "String"}
VALUE_TYPE_PREFIXES = (
    "SI.", "Modelica.Units.", "Modelica.SIunits.", "Modelica.Constants.",
    "Modelica.Units.SI.", "Types.", "Modelica.Units.NonSI.",
)

QUALIFIERS = (
    "final", "inner", "outer", "replaceable", "redeclare", "discrete",
    "parameter", "constant", "flow", "stream", "input", "output",
)

SECTION_KEYWORDS = (
    "initial equation", "initial algorithm", "equation", "algorithm",
    "public", "protected",
)


def is_connector_type(type_name: str, known_connectors=None) -> bool:
    """True if ``type_name`` denotes a connector.

    Recognition is layered so the parser is not tied to any one physical domain:

    1. ``known_connectors`` — names of ``connector`` classes defined in this file. This is
       authoritative and covers any custom / library-local domain with zero hardcoding.
    2. A ``.Interfaces.`` qualified path (the MSL convention for connector packages).
    3. An explicit suffix from :data:`CONNECTOR_SUFFIXES` (electrical/mechanical/control/heat).
    4. The generic ``…Port`` / ``…Ports`` family rule (fluid, magnetic, pneumatic, …).
    """
    last = type_name.split(".")[-1]
    if known_connectors and last in known_connectors:
        return True
    if ".Interfaces." in type_name:
        return True
    if last in CONNECTOR_SUFFIXES:
        return True
    return bool(_PORT_SUFFIX_RE.search(last))


def is_value_type(type_name: str) -> bool:
    if type_name in VALUE_TYPE_NAMES:
        return True
    return any(type_name.startswith(p) for p in VALUE_TYPE_PREFIXES)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Connector:
    name: str
    type_name: str
    description: str = ""
    decl_start: int = 0        # statement start (just after previous ';')
    core_start: int = 0        # index of the TYPE token (past indent/comments)
    decl_end: int = 0          # index just past the terminating ';'
    semicolon: int = 0         # index of the terminating ';'
    has_placement: bool = False
    siblings: list = field(default_factory=list)   # all names declared together on this line
    decl_text: str = ""        # this member's own declarator source: name[subscript](mods)


@dataclass
class Instance:
    name: str
    type_name: str
    modifications: str = ""    # first balanced (...) of the whole declaration
    description: str = ""
    decl_start: int = 0
    core_start: int = 0
    decl_end: int = 0
    semicolon: int = 0
    has_placement: bool = False
    siblings: list = field(default_factory=list)
    decl_text: str = ""        # this member's own declarator source: name[subscript](mods)


@dataclass
class Connect:
    from_path: str
    to_path: str
    stmt_start: int = 0
    semicolon: int = 0         # index of the terminating ';'
    has_line: bool = False

    @property
    def from_inst(self) -> str:
        return self.from_path.split(".")[0]

    @property
    def from_port(self) -> str:
        return self.from_path.split(".", 1)[1] if "." in self.from_path else ""

    @property
    def to_inst(self) -> str:
        return self.to_path.split(".")[0]

    @property
    def to_port(self) -> str:
        return self.to_path.split(".", 1)[1] if "." in self.to_path else ""


@dataclass
class ClassSpan:
    kind: str                  # model | package | class | block | record | connector | function | type
    name: str
    is_partial: bool = False
    is_short: bool = False     # short class definition: `package P = Q;`, `model M = N(...);`
    short_base: str = ""       # the class a short definition names, e.g. ``Q``
    header_start: int = 0      # index of the class keyword
    body_start: int = 0        # index just after header (+ description), where body begins
    body_end: int = 0          # index of the matching 'end Name;' keyword
    full_end: int = 0          # index just past the 'end Name;'
    description: str = ""
    parent: int = -1           # index into the flat class list, or -1
    children: list = field(default_factory=list)

    extends: list = field(default_factory=list)        # list[str] base classes
    connectors: list = field(default_factory=list)     # list[Connector]
    instances: list = field(default_factory=list)      # list[Instance]
    connects: list = field(default_factory=list)       # list[Connect]

    has_experiment: bool = False
    has_icon: bool = False
    has_diagram: bool = False
    has_documentation: bool = False  # class annotation already has a Documentation(...)
    has_figures: bool = False        # Documentation(...) already carries a figures = {...}
    annotation_start: int = 0   # span of the class-level annotation(...) statement, or (0,0)
    annotation_end: int = 0
    placements: dict = field(default_factory=dict)  # declared name -> masked declaration with a Placement
    imports: list = field(default_factory=list)  # (name, path): ``import A.B.*`` gives ("", "A.B")


# ---------------------------------------------------------------------------
# Class boundary scanning
# ---------------------------------------------------------------------------

_CLASS_KW = r"(?:model|package|class|block|record|connector|function|operator|type)"
# An identifier is either a plain word or a Modelica quoted identifier ('...'),
# which may contain spaces, e.g.  model 'My Model'.
_IDENT = r"(?:'[^'\n]+'|\w+)"
_HEADER_RE = re.compile(
    r"\b(?:encapsulated\s+)?(?:partial\s+)?(?:final\s+)?(?:replaceable\s+)?"
    r"(?:expandable\s+)?(" + _CLASS_KW + r")\s+(" + _IDENT + r")"
)
_END_RE = re.compile(r"\bend\s+(" + _IDENT + r")\s*;")
_CONTROL_ENDS = {"if", "for", "while", "when"}


def _next_significant(mask: str, pos: int) -> str:
    n = len(mask)
    while pos < n and mask[pos].isspace():
        pos += 1
    return mask[pos] if pos < n else ""


def _paren_depths(mask: str) -> list:
    """Parenthesis nesting depth at every offset of ``mask``."""
    out, d = [], 0
    for ch in mask:
        if ch == "(":
            d += 1
        elif ch == ")":
            d = max(0, d - 1)
        out.append(d)
    return out


def find_classes(text: str, mask: str) -> list:
    """Return a flat list of ClassSpan with parent/children links, in source order."""
    # Collect open-header and end events on the mask.
    events = []  # (pos, kind, payload)
    depth = _paren_depths(mask)
    for m in _HEADER_RE.finditer(mask):
        if depth[m.start(1)]:
            continue        # `redeclare package Medium = ...` inside a modification
        kw = m.group(1)
        name = m.group(2).strip("'")
        name_end = m.end(2)
        is_partial = "partial" in mask[m.start():m.start(2)]
        # Short class definition?  e.g.  type X = Real(...);   package P = Q;
        nxt = _next_significant(mask, name_end)
        is_short = nxt == "="
        events.append((m.start(1), "open", {
            "kind": kw, "name": name, "is_partial": is_partial,
            "header_start": m.start(1), "name_end": name_end, "short": is_short,
        }))
    for m in _END_RE.finditer(mask):
        name = m.group(1).strip("'")
        if name in _CONTROL_ENDS:
            continue
        events.append((m.start(), "end", {"name": name, "end_pos": m.start(), "after": m.end()}))
    events.sort(key=lambda e: e[0])

    classes: list = []
    stack: list = []  # indices into `classes` for open long-classes

    for pos, kind, p in events:
        if kind == "open":
            # description string directly after the name?
            body_start, description = _scan_description(text, mask, p["name_end"])
            cs = ClassSpan(
                kind=p["kind"], name=p["name"], is_partial=p["is_partial"],
                is_short=p["short"], header_start=p["header_start"], body_start=body_start,
                description=description,
            )
            idx = len(classes)
            cs.parent = stack[-1] if stack else -1
            if cs.parent != -1:
                classes[cs.parent].children.append(idx)
            classes.append(cs)
            if p["short"]:
                # short class: terminate at the next top-level ';'
                semi = _find_semicolon(mask, p["name_end"])
                base = re.match(r"\s*=\s*(?:input\s+|output\s+)?([\w.]+)", mask[p["name_end"]:semi])
                cs.short_base = base.group(1) if base else ""
                cs.body_end = semi
                cs.full_end = semi + 1
            else:
                stack.append(idx)
        else:  # end
            if not stack:
                continue
            # pop the nearest matching name (defensive: search down)
            popped = None
            for k in range(len(stack) - 1, -1, -1):
                if classes[stack[k]].name == p["name"]:
                    popped = stack.pop(k)
                    break
            if popped is None:
                popped = stack.pop()
            classes[popped].body_end = p["end_pos"]
            classes[popped].full_end = p["after"]
    if stack:
        # Classes still open at EOF: an unclosed class or an unterminated block
        # comment that swallowed the matching `end`. Their body_end/full_end are 0,
        # which would parse as an empty class (and re-parse enclosing declarations
        # twice); refuse rather than annotate against a broken span map.
        unclosed = ", ".join(classes[i].name for i in stack)
        raise ParseError("unterminated class or block comment (unclosed: %s)" % unclosed)
    return classes


def _scan_description(text: str, mask: str, pos: int) -> tuple:
    """Starting just after the class name, skip whitespace and capture an optional
    description string. Returns (body_start_index, description)."""
    n = len(text)
    i = pos
    while i < n and mask[i].isspace():
        i += 1
    if i < n and text[i] == '"':
        # find closing quote in original text (handle \")
        j = i + 1
        buf = []
        while j < n:
            if text[j] == "\\" and j + 1 < n:
                buf.append(text[j + 1])
                j += 2
                continue
            if text[j] == '"':
                j += 1
                break
            buf.append(text[j])
            j += 1
        return j, "".join(buf)
    return pos, ""


def _find_semicolon(mask: str, start: int) -> int:
    """Index of the next depth-0 ';' at or after start (paren/brace/bracket aware)."""
    depth = 0
    for i in range(start, len(mask)):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return i
    return len(mask) - 1


# ---------------------------------------------------------------------------
# Statement splitting within a class's own region
# ---------------------------------------------------------------------------

def _own_intervals(cls: ClassSpan, classes: list) -> list:
    """Return the [start,end) intervals of cls's body that are NOT covered by a child class."""
    spans = [(classes[c].header_start, classes[c].full_end) for c in cls.children]
    spans.sort()
    result = []
    cur = cls.body_start
    for s, e in spans:
        e = max(e, s)  # defensive: a malformed child span never rewinds `cur`
        if s > cur:
            result.append((cur, s))
        cur = max(cur, e)
    if cur < cls.body_end:
        result.append((cur, cls.body_end))
    return result


def _split_statements(mask: str, start: int, end: int) -> list:
    """Split [start,end) into top-level statements at depth-0 ';'. Returns (s,e) spans
    (e is the index of the ';')."""
    stmts = []
    depth = 0
    s = start
    for i in range(start, end):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == ";" and depth == 0:
            stmts.append((s, i))
            s = i + 1
    return stmts


# A component name is a plain identifier or a quoted identifier, which may contain
# spaces and dots (e.g. `'my sine'`); capture the quoted form whole so it isn't
# truncated at the first space.
_NAME = r"(?:'(?:\\.|[^'\n])*'|\w+)"
_DECL_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s+(" + _NAME + r")")
# A connect endpoint is a dotted path whose segments may carry an array subscript, e.g.
# ``src.ports[1]`` or ``a.b[2].c`` — common in fluid/vessel models with port arrays.
_PATH_RE = r"\w+(?:\[[^\]]*\])?(?:\.\w+(?:\[[^\]]*\])?)*"
_CONNECT_RE = re.compile(r"connect\s*\(\s*(" + _PATH_RE + r")\s*,\s*(" + _PATH_RE + r")\s*\)")


def _decl_type_and_names(cm2: str) -> tuple:
    """Parse 'TYPE name1, name2, ... [mods]' from a mask-core.
    Returns (type, [names], [declarator spans]).

    Handles multi-name declarations including ones where each component carries its own
    modification, e.g. ``NPN Q1(VAF=80), Q2(VAF=50) "pair";`` — a depth-0 ``(`` begins a
    per-component modifier and is skipped (with its balanced parens), so every name is kept.
    The names section ends at the first depth-0 ``=`` (binding), ``"`` (description) or
    ``;``. The spans are each member's own ``name[subscript](mods)`` declarator text in
    ``cm2`` (whitespace-trimmed, between the depth-0 commas), so a caller splitting the
    declaration can reproduce every member's own subscript and modification verbatim
    instead of cross-applying the first member's."""
    m = re.match(r"\s*([A-Za-z_][\w.]*)\s+", cm2)
    if not m:
        return "", [], []
    type_name = m.group(1)
    base = m.end()
    rest = cm2[base:]
    # End of the names section: first depth-0 '=' / '"' / ';'. A '(' or '[' opens a
    # per-component modification / array subscript, so descend into it rather than stopping.
    depth = 0
    cut = len(rest)
    for i, c in enumerate(rest):
        if depth == 0 and c in '=";':
            cut = i
            break
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
    names_part = rest[:cut]
    # Split on depth-0 commas; record each member's leading identifier and the span of
    # its whole declarator (identifier + any [subscript] / (mods) it carries).
    names = []
    spans = []
    depth = 0
    start = 0
    for i, c in enumerate(names_part + ","):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == "," and depth == 0:
            seg = names_part[start:i]
            nm = re.match(r"\s*(" + _NAME + r")", seg)
            if nm:
                names.append(nm.group(1))
                lead = len(seg) - len(seg.lstrip())
                spans.append((base + start + lead, base + start + len(seg.rstrip())))
            start = i + 1
    return type_name, names, spans


def _strip_leading(mask_stmt: str) -> int:
    """Return the offset within mask_stmt past leading section keywords + qualifiers."""
    pos = 0
    changed = True
    while changed:
        changed = False
        rest = mask_stmt[pos:]
        stripped = rest.lstrip()
        lead_ws = len(rest) - len(stripped)
        for kw in SECTION_KEYWORDS:
            m = re.match(re.escape(kw) + r"\b", stripped)
            if m:
                pos += lead_ws + m.end()
                changed = True
                break
        if changed:
            continue
        for kw in QUALIFIERS:
            m = re.match(kw + r"\b", stripped)
            if m:
                pos += lead_ws + m.end()
                changed = True
                break
    return pos


def _strip_section(mask_stmt: str) -> str:
    pos = 0
    for kw in SECTION_KEYWORDS:
        m = re.match(r"\s*" + re.escape(kw) + r"\b", mask_stmt)
        if m:
            pos = m.end()
            break
    return mask_stmt[pos:]


def populate_class(cls: ClassSpan, text: str, mask: str, classes: list,
                   known_connectors=None, known_components=None) -> None:
    """Fill connectors / instances / connects / extends / annotation info for one class.

    ``known_connectors`` is the set of names of ``connector`` classes defined anywhere in the
    file; a declaration whose type resolves to one of them is treated as a connector even if
    its name matches no built-in heuristic (custom-domain support).

    ``known_components`` is the set of names of instantiable component classes (model/block/
    class) defined anywhere in the file; a simple-name declaration of one of them is a placeable
    sub-component, even when its type is a package-level sibling rather than a nested child.
    """
    sibling_names = {classes[c].name for c in cls.children}
    component_names = sibling_names | (known_components or set())
    # a declaration of a type defined elsewhere (imported, or a sibling in another file)
    # is a component when a connect reaches into it
    reached = {g.split(".")[0].split("[")[0] for a, b in _own_intervals(cls, classes)
               for m in _CONNECT_RE.finditer(mask, a, b) for g in m.groups() if "." in g}

    def connected(names):
        return any(nm in reached for nm in names)
    for (a, b) in _own_intervals(cls, classes):
        for (s, e) in _split_statements(mask, a, b):
            mstmt = mask[s:e]
            ostmt = text[s:e]
            lead = _strip_leading(mstmt)
            core_mask = mstmt[lead:]
            core_off = s + lead
            core = core_mask.lstrip()
            core_off += len(core_mask) - len(core_mask.lstrip())

            if not core:
                continue

            # connect(...)
            cm = _CONNECT_RE.search(mstmt)
            if cm and core.startswith("connect"):
                has_line = bool(re.search(r"\bLine\s*\(", mstmt)
                                or re.search(r"\bannotation\s*\(", mstmt))
                cls.connects.append(Connect(
                    from_path=cm.group(1), to_path=cm.group(2),
                    stmt_start=s, semicolon=e, has_line=has_line,
                ))
                continue

            # extends
            if core.startswith("extends"):
                em = re.match(r"extends\s+([\w.]+)", core)
                if em:
                    cls.extends.append(em.group(1))
                continue

            if re.match(r"import\b", core):
                cls.imports += _imports(core)
                continue

            # class-level annotation
            if core.startswith("annotation"):
                cls.annotation_start = s
                cls.annotation_end = e
                if "experiment" in mstmt:
                    cls.has_experiment = True
                if re.search(r"\bIcon\s*\(", mstmt):
                    cls.has_icon = True
                if re.search(r"\bDiagram\s*\(", mstmt):
                    cls.has_diagram = True
                if re.search(r"\bDocumentation\s*\(", mstmt):
                    cls.has_documentation = True
                if re.search(r"\bfigures\s*=", mstmt):
                    cls.has_figures = True
                continue

            # declaration: TYPE name ...
            # Align mask-core and orig-core so paren/string scanning ignores comments.
            ws = len(core_mask) - len(core_mask.lstrip())
            cm2 = core_mask[ws:]            # mask core (strings shown as "   ", comments blank)
            co2 = ostmt[lead:][ws:]         # original core, same offsets as cm2
            core_start = s + lead + ws
            type_name, names, decl_spans = _decl_type_and_names(cm2)
            if not type_name or not names:
                continue
            # Skip obvious non-declarations (equations look like 'x =' -> no second ident)
            if type_name in ("der", "connect"):
                continue

            had_param = bool(re.match(r"\s*(?:parameter|constant)\b", _strip_section(mstmt)))
            has_placement = bool(re.search(r"\bPlacement\s*\(", mstmt))
            if has_placement:
                for nm in names:
                    cls.placements[nm] = cm2
            description = _trailing_description(cm2, co2)

            if is_connector_type(type_name, known_connectors):
                for nm, sp in zip(names, decl_spans):
                    cls.connectors.append(Connector(
                        name=nm, type_name=type_name, description=description,
                        decl_start=s, core_start=core_start, decl_end=e + 1, semicolon=e,
                        has_placement=has_placement, siblings=list(names),
                        decl_text=co2[sp[0]:sp[1]],
                    ))
            elif had_param or is_value_type(type_name):
                continue  # parameter / variable
            elif ("." in type_name) or (type_name in component_names) or connected(names):
                mods = _capture_mods(cm2, co2)
                for nm, sp in zip(names, decl_spans):
                    cls.instances.append(Instance(
                        name=nm, type_name=type_name, modifications=mods,
                        description=description, decl_start=s, core_start=core_start,
                        decl_end=e + 1, semicolon=e, has_placement=has_placement,
                        siblings=list(names), decl_text=co2[sp[0]:sp[1]],
                    ))
            # else: local simple-type variable -> skip


def _imports(core: str) -> list:
    """``(name, path)`` pairs of one import clause; ``name`` is "" for a wildcard."""
    m = re.match(r"import\s+(\w+)\s*=\s*([\w.]+)", core)
    if m:
        return [(m.group(1), m.group(2))]
    m = re.match(r"import\s+([\w.]+)\.\s*\*", core)
    if m:
        return [("", m.group(1))]
    m = re.match(r"import\s+([\w.]+)\.\s*\{([^}]*)\}", core)
    if m:
        return [(n.strip(), m.group(1) + "." + n.strip()) for n in m.group(2).split(",") if n.strip()]
    m = re.match(r"import\s+([\w.]+)", core)
    return [(m.group(1).split(".")[-1], m.group(1))] if m else []


def import_candidates(cls: ClassSpan, classes: list, type_name: str) -> list:
    """Full paths a type name may denote through the imports in scope, most specific first.

    A named import is certain; each wildcard gives a candidate the caller has to confirm.
    Empty when no import applies.
    """
    head, _, rest = type_name.partition(".")
    named, wild = [], []
    c = cls
    while c is not None:
        for name, path in c.imports:
            if name == head:
                named.append(path + ("." + rest if rest else ""))
            elif not name:
                wild.append(path + "." + type_name)
        c = classes[c.parent] if c.parent != -1 else None
    return named + wild


def _trailing_description(cm2: str, co2: str) -> str:
    """Last depth-0 string in the (mask, orig) aligned cores. Depth-0 excludes any
    string inside annotation(...)/modifications. ``cm2`` shows strings as ``"   "``."""
    depth = 0
    last = ""
    i = 0
    n = len(cm2)
    while i < n:
        c = cm2[i]
        if c in "([{":
            depth += 1
            i += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
            i += 1
        elif c == '"' and depth == 0:
            j = i + 1
            while j < n and cm2[j] != '"':
                j += 1
            last = co2[i + 1:j]
            i = j + 1
        else:
            i += 1
    return last


def _capture_mods(cm2: str, co2: str) -> str:
    """Text inside the first balanced (...) of the declaration, using mask for structure."""
    start = cm2.find("(")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(cm2)):
        if cm2[i] == "(":
            depth += 1
        elif cm2[i] == ")":
            depth -= 1
            if depth == 0:
                return co2[start + 1:i]
    return ""


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def parse(text: str) -> list:
    """Parse Modelica source text. Returns a flat list of populated ClassSpan."""
    mask = mask_code(text)
    classes = find_classes(text, mask)
    known_connectors = {c.name for c in classes if c.kind == "connector"}
    known_components = {c.name for c in classes if c.kind in ("model", "block", "class")}
    for cls in classes:
        populate_class(cls, text, mask, classes, known_connectors, known_components)
    return classes


def parse_file(path: str) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return text, parse(text)


# ---------------------------------------------------------------------------
# Statement structure (for tools that remove or rewrite whole statements)
# ---------------------------------------------------------------------------

@dataclass
class Statement:
    """One element, equation or algorithm statement of a class body.

    ``kind`` is ``section`` (``equation``, ``algorithm``, ``initial equation``,
    ``public``, ...), ``plain`` (anything ending at its own ``;``) or ``block``
    (an ``if``/``for``/``when``/``while`` statement up to its ``end ...;``).
    ``start``/``end`` span the statement in the source (``end`` is past the
    ``;``). A block's ``branches`` are ``(keyword_start, body_start, body_end,
    statements)``, one per ``then``/``elseif``/``else``/``elsewhen``/``loop`` body,
    where ``keyword_start`` is where the ``if``/``elseif``/``else``/... begins."""
    kind: str
    start: int
    end: int
    keyword: str = ""
    branches: list = field(default_factory=list)

    def walk(self):
        yield self
        for _, _, _, stmts in self.branches:
            for s in stmts:
                yield from s.walk()


_SECTION_RE = re.compile(r"(?:initial\s+)?(?:equation|algorithm)\b|(?:public|protected)\b")
_BLOCK_RE = re.compile(r"(if|for|when|while)\b")
_BLOCK_STOPS = {"if": ("elseif", "else", "end"), "when": ("elsewhen", "end"),
                "for": ("end",), "while": ("end",)}
_BLOCK_OPENER = {"if": "then", "elseif": "then", "when": "then", "elsewhen": "then",
                 "for": "loop", "while": "loop", "else": None}


def _skip_ws(mask: str, pos: int, end: int) -> int:
    while pos < end and mask[pos].isspace():
        pos += 1
    return pos


def _find_word(mask: str, word: str, pos: int, end: int) -> int:
    """Index of the next depth-0 ``word`` in ``mask[pos:end]``, or -1."""
    depth = 0
    pat = re.compile(r"(?<!\w)" + word + r"\b")
    for i in range(pos, end):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and pat.match(mask, i):
            return i
    return -1


def _parse_statements(mask: str, pos: int, end: int, stops=()) -> tuple:
    """Statements from ``pos`` until ``end`` or a statement starting with one of
    ``stops``. Returns ``(statements, stop_pos, stop_word)``."""
    stmts = []
    while True:
        pos = _skip_ws(mask, pos, end)
        if pos >= end:
            return stmts, end, None
        for word in stops:
            if re.match(word + r"\b", mask[pos:pos + len(word) + 1]):
                return stmts, pos, word
        sec = _SECTION_RE.match(mask, pos)
        if sec:
            stmts.append(Statement("section", pos, sec.end(), re.sub(r"\s+", " ", sec.group(0))))
            pos = sec.end()
            continue
        blk = _BLOCK_RE.match(mask, pos)
        if blk:
            stmt = _parse_block(mask, pos, end, blk.group(1))
            stmts.append(stmt)
            pos = stmt.end
            continue
        semi = _find_semicolon(mask, pos)
        if semi >= end or mask[semi] != ";":
            return stmts, end, None
        word = re.match(r"[A-Za-z_]\w*", mask[pos:])
        stmts.append(Statement("plain", pos, semi + 1, word.group(0) if word else ""))
        pos = semi + 1


def _parse_block(mask: str, start: int, end: int, keyword: str) -> Statement:
    stmt = Statement("block", start, end, keyword)
    word, pos = keyword, start
    while True:
        opener = _BLOCK_OPENER[word]
        if opener is None:
            body = pos + len(word)
        else:
            at = _find_word(mask, opener, pos + len(word), end)
            if at < 0:
                raise ParseError("no '%s' for '%s' at offset %d" % (opener, word, pos))
            body = at + len(opener)
        stmts, stop, word = _parse_statements(mask, body, end, _BLOCK_STOPS[keyword])
        if word is None:
            raise ParseError("unterminated '%s' at offset %d" % (keyword, start))
        stmt.branches.append((pos, body, stop, stmts))
        if word == "end":
            closing = re.compile(r"end\s+" + keyword + r"\s*;").match(mask, stop)
            if not closing:
                raise ParseError("expected 'end %s;' at offset %d" % (keyword, stop))
            stmt.end = closing.end()
            return stmt
        pos = stop


def class_statements(cls: ClassSpan, mask: str, classes: list) -> list:
    """The statements in ``cls``'s own body (nested classes excluded), in source order."""
    out = []
    for a, b in _own_intervals(cls, classes):
        stmts, _, _ = _parse_statements(mask, a, b)
        out.extend(stmts)
    return out


def comment_spans(text: str, mask: str) -> list:
    """``(start, end)`` of every comment in ``text``."""
    spans = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        if mask[i] == '"':
            in_string = not in_string
        elif not in_string and mask[i] == " " and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
            continue
        elif not in_string and mask[i] == " " and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans

