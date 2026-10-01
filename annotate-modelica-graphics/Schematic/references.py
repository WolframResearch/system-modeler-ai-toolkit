"""Replicable reference (datum) components, and the pre-pass that un-shares them.

A component belongs in ``REFERENCE_TYPES`` only if it has a single connector on which it
prescribes the effort and leaves the flow free. That is what makes N separate instances
equivalent to one instance shared by N connections: each absorbs whatever flow reaches it,
so no connection can tell the difference. A component that prescribes a flow, or that also
forms a path between the connections it joins, does not qualify.

Class paths and connector names verified against MSL 4.1.0.
"""

from __future__ import annotations

import re

from . import pins
from .parser import QUALIFIERS
from mo_edit import Edit, balanced_close, find_call_open, indent_at, splice

# Below this many connections a shared reference costs nothing in the diagram, so leave
# the user's model alone.
SPLIT_FANOUT_MIN = 3

# fully-qualified type -> (its single connector, the icon side it leaves free for a
# connection to arrive on). The mechanical housings put their flange at the icon centre and
# draw the hatched wall below it, so their free side is the top.
REFERENCE_TYPES = {
    "Modelica.Electrical.Analog.Basic.Ground": ("p", "T"),
    "Modelica.Electrical.QuasiStatic.SinglePhase.Basic.Ground": ("pin", "T"),
    "Modelica.Mechanics.Rotational.Components.Fixed": ("flange", "T"),
    "Modelica.Mechanics.Translational.Components.Fixed": ("flange", "T"),
    "Modelica.Thermal.HeatTransfer.Sources.FixedTemperature": ("port", "R"),
    "Modelica.Magnetic.FluxTubes.Basic.Ground": ("port", "T"),
    "Modelica.Magnetic.QuasiStatic.FluxTubes.Basic.Ground": ("port", "T"),
    "Modelica.Magnetic.FundamentalWave.Components.Ground": ("port_p", "T"),
    "Modelica.Magnetic.QuasiStatic.FundamentalWave.Components.Ground": ("port_p", "T"),
}


def free_side(type_name: str) -> str | None:
    """The icon side ('L'/'R'/'T'/'B') a known reference leaves free, or None."""
    spec = REFERENCE_TYPES.get(type_name)
    return spec[1] if spec else None


def local_reference_types(classes: list) -> set:
    """Ground-like classes defined in the file itself: a model named ``Ground`` with
    exactly one connector. A domain outside the MSL still gets the same treatment."""
    return {c.name for c in classes
            if c.kind == "model" and c.name == "Ground" and len(c.connectors) == 1}


def is_reference(inst, local: set | None = None) -> bool:
    """True if ``inst`` is a replicable reference component."""
    t = pins.type_of(inst)
    if t in REFERENCE_TYPES:
        return True
    if t.startswith("Modelica."):
        return False          # an MSL path that is not on the list is not a reference
    return bool(local) and t.split(".")[-1] in local


# ---------------------------------------------------------------------------
# split pre-pass
# ---------------------------------------------------------------------------

def split_plan(mask: str, cls, local: set | None = None) -> list:
    """One ``(instance, connections, blocker)`` triple per reference component in ``cls``.

    ``blocker`` is None when the instance will be split, otherwise why it will not be.
    ``mask`` is ``mask_code(text)``.
    """
    plan = []
    for inst in cls.instances:
        if not is_reference(inst, local):
            continue
        uses = _uses(cls, inst)
        blocker = ("too few connections for a split to simplify anything"
                   if len(uses) < SPLIT_FANOUT_MIN else _blocker(mask, cls, inst))
        plan.append((inst, len(uses), blocker))
    return plan


def split_shared(text: str, mask: str, classes: list, targets: set | None = None) -> tuple:
    """Give each connection to a shared reference component its own instance.

    ``mask`` is ``mask_code(text)``; ``targets`` names the classes to rewrite (``None`` for
    all of them). Only classes that are about to be laid out belong in it -- splitting one
    that keeps its existing diagram would add instances nothing places. Returns
    ``(new_text, notes)`` with ``notes`` a ``{class_name: [message, ...]}`` map for the
    caller's per-class summary. The result flattens to the same behaviour as the input;
    re-running is a no-op, since afterwards no reference is shared any more.
    """
    local = local_reference_types(classes)
    edits: list = []
    notes: dict = {}
    for cls in classes:
        if targets is not None and cls.name not in targets:
            continue
        # every identifier already visible in the class, so a generated name cannot
        # collide with a parameter or variable the split pre-pass never looked at
        taken = ({c.name for c in classes}
                 | set(re.findall(r"[A-Za-z_]\w*", mask[cls.body_start:cls.body_end])))
        for inst, _, blocker in split_plan(mask, cls, local):
            if blocker:
                continue
            uses = _uses(cls, inst)
            clones = []
            for cn in uses[1:]:                       # the first use keeps the original
                edit = _rename_in_connect(mask, cn, inst.name, _fresh_name(inst.name, taken))
                if edit is None:
                    continue
                taken.add(edit.text)
                clones.append(edit.text)
                edits.append(edit)
            if not clones:
                continue
            edits.append(_clone_declarations(text, mask, inst, clones))
            notes.setdefault(cls.name, []).append(
                "split %s into %d references" % (inst.name, len(clones) + 1))
    return splice(text, edits), notes


def _uses(cls, inst) -> list:
    return [cn for cn in cls.connects if inst.name in (cn.from_inst, cn.to_inst)]


def _blocker(mask: str, cls, inst) -> str | None:
    """Why this instance may not be replicated, or None when it may."""
    if set(mask[inst.decl_start:inst.core_start].split()) & {"inner", "outer"}:
        return "declared inner/outer, so the language wants exactly one"
    if "[" in inst.decl_text:
        return "declared as an array"
    if inst.name.startswith("'"):
        return "a quoted identifier, which cannot be renamed safely"
    # Anything that reads the instance outside a connect — `ground.p.i` in an equation, a
    # modification referring to it — would see only one of the copies after the split.
    spans = [(cn.stmt_start, cn.semicolon + 1) for cn in cls.connects]
    spans.append((inst.decl_start, inst.decl_end))
    for m in _ident_re(inst.name).finditer(mask, cls.body_start, cls.body_end):
        if not any(s <= m.start() < e for s, e in spans):
            return "read outside its connect equations"
    return None


def _ident_re(name: str) -> re.Pattern:
    """Match ``name`` as a whole identifier, never as the tail of a dotted path."""
    return re.compile(r"(?<![\w.])%s\b" % re.escape(name))


def _fresh_name(base: str, taken: set) -> str:
    stem, digits = re.match(r"^(.*?)(\d*)$", base).groups()
    k = int(digits) + 1 if digits else 2
    while "%s%d" % (stem, k) in taken:
        k += 1
    return "%s%d" % (stem, k)


def _rename_in_connect(mask: str, cn, old: str, new: str) -> Edit | None:
    """Rewrite one ``connect`` argument to name a different instance.

    Edits only the identifier, so a second reference being split in the same statement gets
    its own non-overlapping edit and any ``annotation(Line(...))`` on the connect survives.
    """
    open_idx = find_call_open(mask, cn.stmt_start, cn.semicolon + 1, "connect")
    close = balanced_close(mask, open_idx) if open_idx != -1 else -1
    if close == -1:
        return None
    m = _ident_re(old).search(mask, open_idx, close)
    return Edit(m.start(), m.end(), new) if m else None


def _declarator_tail(inst) -> str:
    """The instance's own modification and subscript, without any trailing annotation.

    ``decl_text`` runs to the end of the declarator, so on an already-placed component it
    still carries ``annotation(Placement(...))``. Copying that into a clone would stack
    every copy on the original's coordinates, so it is cut here.
    """
    tail = inst.decl_text[len(inst.name):]
    depth = 0
    for i, c in enumerate(tail):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif (depth == 0 and tail.startswith("annotation", i)
              and (i == 0 or not (tail[i - 1].isalnum() or tail[i - 1] == "_"))):
            return tail[:i].rstrip()
    return tail.rstrip()


def _clone_declarations(text: str, mask: str, inst, names: list) -> Edit:
    """One extra declaration per new name, right after the original."""
    indent = indent_at(text, inst.core_start)
    prefix = " ".join(w for w in mask[inst.decl_start:inst.core_start].split() if w in QUALIFIERS)
    prefix = prefix + " " if prefix else ""
    desc = ' "%s"' % inst.description if inst.description else ""
    tail = _declarator_tail(inst)
    block = "".join("\n%s%s%s %s%s%s;" % (indent, prefix, inst.type_name, nm, tail, desc)
                    for nm in names)
    return Edit(inst.decl_end, inst.decl_end, block)
