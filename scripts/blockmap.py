"""
Maps the generated functions a profile samples back onto the model.

The diagnose build writes both the generated C++ and the block-debug JSON. In the
C++, every block is evaluated inside a `chunkFunction_N` under its own
`const size_t BLOCK_ID = ...;`, and the solver functions of a coupled system
(`residualFunc_N`, `solveTearingInner_N`, ...) are called from there. That ties
each sampled function -- and, where the sampler reports it, each source line --
to the equation blocks it evaluates, and through those to the variables and
components the model solves there.
"""

import bisect
import os
import re

import blockdebug as bd

# "static bool chunkFunction_74(SimData* simData)"
# "static void residualFunc_330_throw(SimData* simData, const double* x, ...)"
# Every generated function is matched, not only the ones that carry block ids: a
# function left out would have its body absorbed into the span of the one before
# it, and its block ids charged there.
_HELPERS = r"solveTearingInner|residualFunc|solveMixedContinuous|solveMixedDiscrete"
_FUNC_RE = re.compile(
    r"^static\s+[\w:<>*&\s]+?\b(chunkFunction|%s)_(\d+)(_throw)?\s*\(" % _HELPERS,
    re.M)
_CALL_RE = re.compile(r"\b(%s)_(\d+)(?:_throw)?\b" % _HELPERS)
_BLOCK_RE = re.compile(r"const size_t BLOCK_ID = (\d+);")

# The generated sources, and the block-debug section each one's block ids index
# into. Ids repeat across sections, so the file is what disambiguates them.
_PART_SECTIONS = {"_ode.cpp": "ode", "_init.cpp": "init",
                  "_output.cpp": "output", "_clocked.cpp": "clocked"}

component_of = bd.component_of


def split_frame(frame):
    """(function name, (source file, line) or None) of a sampled frame. A backend
    that knows the source line appends it as "name@file:line"."""
    name, _, where = frame.partition("@")
    path, _, line = where.rpartition(":")
    if path and line.isdigit():
        return name, (os.path.basename(path), int(line))
    return name, None


class Block(object):
    """What the report needs to know about one equation block."""

    def __init__(self, variables, equations, sources, system):
        self.variables = variables
        self.equations = equations           # equation count
        self.sources = sources               # {class path: sorted line numbers}
        self.system = system                 # (type, jacobian, torn size) or None


class _Source(object):
    """Where each generated function and each block's code sits in one file."""

    def __init__(self, section):
        self.section = section
        self.starts = []                     # first line of each span, sorted
        self.spans = []                      # (function name, block id or None)

    def at(self, line):
        i = bisect.bisect_right(self.starts, line) - 1
        return self.spans[i] if i >= 0 else (None, None)


class BlockMap(object):
    def __init__(self, functions, blocks, sources=None, solver_blocks=None):
        self._functions = functions          # name -> (section, sorted block ids)
        self._blocks = blocks                # (section, id) -> Block
        self._sources = sources or {}        # file name -> _Source
        self._solver_blocks = solver_blocks or {}   # chunk name -> {block ids}

    def __bool__(self):
        return bool(self._functions)

    __nonzero__ = __bool__

    def key_for(self, frame):
        """The row a frame's samples are charged to: the block its source line is
        in when the sampler reported one, otherwise the blocks its function
        evaluates. None when the frame is not generated from the model."""
        name, where = split_frame(frame)
        if where and where[0] in self._sources:
            source = self._sources[where[0]]
            function, block = source.at(where[1])
            if block is not None:
                return (source.section, (block,))
            if function:
                name = function
        if name.endswith("_throw"):
            name = name[:-len("_throw")]
        entry = self._functions.get(name)
        return (entry[0], tuple(entry[1])) if entry and entry[1] else None

    def solver_key(self, frame):
        """The one block of a multi-block chunk that calls a solver, when there is
        exactly one -- where a sample taken inside that solver belongs."""
        name, _ = split_frame(frame)
        entry = self._functions.get(name)
        ids = self._solver_blocks.get(name) or ()
        return (entry[0], (next(iter(ids)),)) if entry and len(ids) == 1 else None

    short_class = staticmethod(bd.short_class)

    def blocks_of(self, key):
        section, ids = key
        return [self._blocks[(section, i)] for i in ids
                if (section, i) in self._blocks]

    def variables_for_key(self, key):
        return [v for b in self.blocks_of(key) for v in b.variables]

    def component_shares(self, key):
        """How a row's time divides between components, as fractions summing to 1
        (empty when none of its variables belongs to a component)."""
        counts = {}
        for v in self.variables_for_key(key):
            component = component_of(v)
            if component:
                counts[component] = counts.get(component, 0) + 1
        named = sum(counts.values())
        return {c: n / float(named) for c, n in counts.items()} if named else {}

    def describe_key(self, key):
        """Where the block is, and how hard it is to solve."""
        section, ids = key
        where = ("%s block %d" % (section, ids[0]) if len(ids) == 1 else
                 "%s: %d blocks evaluated together (%d-%d)"
                 % (section, len(ids), ids[0], ids[-1]))
        blocks = self.blocks_of(key)
        if not blocks:
            return "%s -- not described in the block report" % where
        equations = sum(b.equations for b in blocks)
        detail = "%d equation%s" % (equations, "" if equations == 1 else "s")
        if len(ids) > 1:
            return "%s -- %s" % (where, detail)
        system = blocks[0].system
        if system:
            kind, jacobian, torn = system
            if torn:
                detail += ", torn to %d iteration variable%s" % (
                    torn, "" if torn == 1 else "s")
            detail += ", %s Jacobian" % jacobian
        elif equations == 1:
            detail += ", solved directly"
        return "%s -- %s" % (where, detail)

    def components_of(self, key):
        return sorted({c for c in map(component_of, self.variables_for_key(key))
                       if c})

    def sources_of(self, key):
        """{class path: (lines, equation count)} the block's equations come from,
        so a hot block can be looked up in the model text."""
        merged = {}
        for block in self.blocks_of(key):
            for path, (lines, count) in block.sources.items():
                have_lines, have_count = merged.get(path, (set(), 0))
                have_lines.update(lines)
                merged[path] = (have_lines, have_count + count)
        return {p: (sorted(l), c) for p, (l, c) in merged.items()}


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _scan_source(path, section, functions, calls, solver_blocks):
    """Record, for one generated file, the blocks each chunk evaluates, which
    block each solver function is called from, and the line spans of both."""
    src = _read(path)
    source = _Source(section)
    newlines = [m.start() for m in re.finditer("\n", src)]
    line_of = lambda pos: bisect.bisect_left(newlines, pos) + 1
    hits = [(m.start(), m.group(1), int(m.group(2))) for m in _FUNC_RE.finditer(src)]
    for i, (start, kind, index) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(src)
        name = "%s_%d" % (kind, index)
        ids = functions.setdefault(name, (section, set()))[1]
        source.starts.append(line_of(start))
        source.spans.append((name, None))
        if kind != "chunkFunction":
            for m in _CALL_RE.finditer(src, start, end):
                callee = "%s_%s" % (m.group(1), m.group(2))
                if callee != name:
                    calls.setdefault(name, set()).add(callee)
            continue
        marks = list(_BLOCK_RE.finditer(src, start, end))
        for j, m in enumerate(marks):
            block = int(m.group(1))
            ids.add(block)
            seg_end = marks[j + 1].start() if j + 1 < len(marks) else end
            source.starts.append(line_of(m.start()))
            source.spans.append((name, block))
            for c in _CALL_RE.finditer(src, m.end(), seg_end):
                callee = "%s_%s" % (c.group(1), c.group(2))
                functions.setdefault(callee, (section, set()))[1].add(block)
                solver_blocks.setdefault(name, set()).add(block)
    return source


def _propagate(functions, calls):
    """A solver function called only from another one inherits its blocks."""
    changed = True
    while changed:
        changed = False
        for caller, callees in calls.items():
            ids = functions.get(caller, (None, set()))[1]
            for callee in callees:
                target = functions.get(callee)
                if target and not ids <= target[1]:
                    target[1].update(ids)
                    changed = True


def _block_record(block):
    equations = block.get("equations") or []
    sources = bd.block_sources(block)
    systems = bd.find_solver_systems(block)
    system = None
    if systems:
        biggest = max(systems, key=lambda s: s.get("torn-size") or 0)
        system = (biggest.get("system-type"),
                  bd.classify_jacobian(biggest.get("Jacobian")),
                  biggest.get("torn-size"))
    return Block(bd.block_var_names(block), len(equations), sources, system)


def load(tempdir, stem):
    """Build the map for the model named by `stem` from its --mode diagnose
    temp dir. Returns an empty BlockMap when that model's
    artifacts are not there -- a temp dir reused across models holds several
    sets, and guessing between them would attribute the profile to the wrong
    model."""
    debug_path = os.path.join(tempdir, stem + "_blockdebug.json")
    if not os.path.isfile(debug_path):
        return BlockMap({}, {})

    functions, calls, solver_blocks, sources = {}, {}, {}, {}
    for suffix, section in _PART_SECTIONS.items():
        path = os.path.join(tempdir, stem + suffix)
        if os.path.isfile(path):
            sources[os.path.basename(path)] = _scan_source(
                path, section, functions, calls, solver_blocks)
    _propagate(functions, calls)

    data = bd.load(debug_path)
    blocks = {}
    for section, section_blocks in data.items():
        if not isinstance(section_blocks, list):
            continue
        for block in section_blocks:
            if isinstance(block, dict) and "block-index" in block:
                blocks[(section, block["block-index"])] = _block_record(block)

    # A function whose body named no block cannot be charged to one; keeping it
    # would make it look like a block with nothing in it.
    return BlockMap({n: (s, sorted(ids)) for n, (s, ids) in functions.items()
                     if ids},
                    blocks, sources, solver_blocks)
