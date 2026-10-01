#!/usr/bin/env python3
"""Reduce a Modelica model to the smallest one that still hits the same compiler failure.

The model is copied into a work directory and never modified in place. The
script first runs it to capture the failure (an internal error, generated code
that does not compile, or a simulator internal error), then repeatedly tries
smaller variants: without comments and annotations, without whole classes,
statements, modifiers and bindings, and with if-statements replaced by one of
their branches. A variant is kept only when it fails with the same signature.
The smallest model found so far is always in ``<tempdir>/best.mo``.

    python3 minimize_mo.py --model Model.mo --name Pkg.Model [--stage auto] [-j 4]

A directory-form library is first packed into one file. Exit status: 0 when a
failure was reproduced and reduced, 1 when the reduced model no longer shows the
original failure (or on an error), 2 when the model does not show a compiler
failure (or bad arguments).
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kernel_failure
import mo_edit
import modelica_parser as mp
import wsm_run

WSM_RUN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wsm_run.py")
WSM_RUN_TIMED_OUT = 3
STAGES = ("instantiate", "check", "build", "sim")


# ---------------------------------------------------------------------------
# Packing a directory-form library into one file
# ---------------------------------------------------------------------------

def _read_source(path):
    text, eol = mo_edit.read_for_edit(path)
    return text.lstrip("\ufeff"), eol


def _strip_within(text):
    m = re.match(r"\s*within\b[^;]*;", mp.mask_code(text))
    return text[m.end():] if m else text


def _pack_dir(directory):
    package_mo = os.path.join(directory, "package.mo")
    text, _ = _read_source(package_mo)
    order_file = os.path.join(directory, "package.order")
    entries = sorted(os.listdir(directory))
    if os.path.isfile(order_file):
        with open(order_file, encoding="utf-8") as fh:
            order = [line.strip() for line in fh if line.strip()]
        rest = [e for e in entries if os.path.splitext(e)[0] not in order]
        names = order + sorted({os.path.splitext(e)[0] for e in rest})
    else:
        names = sorted({os.path.splitext(e)[0] for e in entries})
    parts = []
    for name in names:
        sub_dir = os.path.join(directory, name)
        sub_file = os.path.join(directory, name + ".mo")
        if name == "package":
            continue
        if os.path.isfile(os.path.join(sub_dir, "package.mo")):
            parts.append(_strip_within(_pack_dir(sub_dir)))
        elif os.path.isfile(sub_file):
            child, _ = _read_source(sub_file)
            parts.append(_strip_within(child))
    mask = mp.mask_code(text)
    top = [c for c in mp.find_classes(text, mask) if c.parent == -1]
    if len(top) != 1:
        raise SystemExit("ERROR: %s must define exactly one class" % package_mo)
    insert = top[0].body_end
    # the class annotation has to stay last in the package body
    own = annotation_spans(mask, top[0].body_start, insert)
    if own and not mask[own[-1][1]:insert].strip(" \t\n;"):
        insert = own[-1][0]
        line_start = text.rfind("\n", 0, insert) + 1
        if not text[line_start:insert].strip():
            insert = line_start
    return text[:insert] + "\n" + "\n".join(p.strip("\n") + "\n" for p in parts) + text[insert:]


def load_model(model_arg):
    """``(text, eol, file_name)`` of the model as one self-contained file."""
    target = wsm_run.resolve_model_target(model_arg)
    if target is None:
        raise SystemExit("ERROR: model not found: %s" % model_arg)
    load_path, _, _, kind = target
    if kind == "package":
        text = _pack_dir(os.path.dirname(load_path))
        _, eol = mo_edit.read_for_edit(load_path)
        return text, eol, os.path.basename(os.path.dirname(load_path)) + ".mo"
    text, eol = _read_source(load_path)
    return text, eol, os.path.basename(load_path)


# ---------------------------------------------------------------------------
# Running one candidate
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, args, name, file_name, workdir):
        self.args = args
        self.name = name
        self.file_name = file_name
        self.workdir = workdir
        self.msl = args.msl
        self.stage = None
        self.timeout = args.timeout
        self.cache = {}
        self.runs = 0
        self.lock = threading.Lock()

    def _command(self, model_path, tempdir, stage):
        mode = "validate" if stage in ("instantiate", "check") else "simulate"
        cmd = [sys.executable, WSM_RUN, "--mode", mode, "--call", stage, "--model", model_path,
               "--name", self.name, "--tempdir", tempdir, "--json", "--msl", self.msl,
               "--timeout", str(self.timeout)]
        if self.args.wsm_home:
            cmd += ["--wsm-home", self.args.wsm_home]
        for lib in self.args.load_library:
            cmd += ["--load-library", lib]
        for extra in self.args.load:
            cmd += ["--load", os.path.abspath(extra)]
        return cmd

    def run(self, text, stage=None):
        """The run summary (with ``compiler_failure``) of ``text`` at ``stage``."""
        stage = stage or self.stage
        with self.lock:
            self.runs += 1
            run_dir = os.path.join(self.workdir, "run%05d" % self.runs)
        os.makedirs(run_dir)
        model_path = os.path.join(run_dir, self.file_name)
        with open(model_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        try:
            proc = subprocess.run(self._command(model_path, os.path.join(run_dir, "out"), stage),
                                  capture_output=True, text=True, timeout=self.timeout + 120)
            start = proc.stdout.find("{")
            summary = json.JSONDecoder().raw_decode(proc.stdout[start:])[0] if start >= 0 else {}
            summary["stderr"] = proc.stderr
            summary["timed_out"] = proc.returncode == WSM_RUN_TIMED_OUT
        except subprocess.TimeoutExpired:
            summary = {"timed_out": True}
        except ValueError:
            summary = {"stderr": proc.stderr}
        finally:
            if not self.args.keep_runs:
                shutil.rmtree(run_dir, ignore_errors=True)
        return summary

    def failure_of(self, text, stage=None):
        data = self.run(text, stage).get("compiler_failure")
        return kernel_failure.Failure(**data) if data else None

    def reproduces(self, text, target):
        key = hashlib.sha256((self.msl + text).encode("utf-8")).hexdigest()
        if key not in self.cache:
            self.cache[key] = target.matches(self.failure_of(text), strict=self.args.strict)
        return self.cache[key]


# ---------------------------------------------------------------------------
# Reduction units: each is a list of (start, end, replacement) edits
# ---------------------------------------------------------------------------

_PREFIX_WORDS = ("encapsulated", "partial", "final", "replaceable", "redeclare", "inner", "outer",
                 "expandable", "operator", "pure", "impure")


def _line_span(text, start, end):
    """Widen ``[start, end)`` to whole lines when nothing else shares them."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    if text[line_start:start].strip() == "" and text[end:line_end].strip() == "":
        return line_start, min(line_end + 1, len(text))
    return start, end


def _is_long(cls):
    return cls.full_end > cls.body_end + 1


def _class_start(mask, cls):
    start = cls.header_start
    while True:
        m = re.search(r"(\w+)\s*$", mask[:start])
        if not m or m.group(1) not in _PREFIX_WORDS:
            return start
        start = m.start(1)


class Model:
    """A parsed snapshot of the candidate text."""

    def __init__(self, text, target_name):
        self.text = text
        self.mask = mp.mask_code(text)
        self.classes = mp.find_classes(text, self.mask)
        self.protected = self._target_path(target_name)
        self.statements = [(ci, s) for ci, c in enumerate(self.classes) if _is_long(c)
                           for top in mp.class_statements(c, self.mask, self.classes) for s in top.walk()]

    def _target_path(self, dotted):
        path, parent = set(), -1
        for part in dotted.lstrip(".").split("."):
            match = [i for i, c in enumerate(self.classes) if c.parent == parent and c.name == part.strip("'")]
            if not match:
                return path
            parent = match[0]
            path.add(parent)
        return path

    def remove(self, start, end):
        s, e = _line_span(self.text, start, end)
        return [(s, e, "")]


_ANNOTATION_RE = re.compile(r"\bannotation\s*\(")


def annotation_spans(mask, start=0, end=None):
    """``(start, end)`` of every ``annotation(...)`` in ``mask[start:end]``, outermost only."""
    end = len(mask) if end is None else end
    spans = []
    pos = start
    while True:
        m = _ANNOTATION_RE.search(mask, pos, end)
        if not m:
            return spans
        close = mo_edit.balanced_close(mask, m.end() - 1)
        if close < 0:
            return spans
        spans.append((m.start(), close + 1))
        pos = close + 1


def units_cosmetic(model):
    units = []
    for s, e in mp.comment_spans(model.text, model.mask):
        units.append(model.remove(s, e))
    statement_annotations = set()
    for _, st in model.statements:
        if st.kind == "plain" and st.keyword == "annotation":
            statement_annotations.add(st.start)
            units.append(model.remove(st.start, st.end))
    for s, e in annotation_spans(model.mask):
        if s in statement_annotations:
            continue
        lead = s
        while lead > 0 and model.text[lead - 1] in " \t\n":
            lead -= 1
        units.append([(lead, e, "")])
    for c in model.classes:
        if c.description:
            quote = model.mask.rfind('"', 0, c.body_start - 1)
            units.append([(model.mask.rfind(c.name, 0, quote) + len(c.name), c.body_start, "")])
    within = re.match(r"\s*within\b[^;]*;[ \t]*\n?", model.mask)
    if within:
        units.append([(0, within.end(), "")])
    for _, st in model.statements:
        if st.kind != "plain" or st.keyword in ("annotation", "connect"):
            continue
        for m in re.finditer(r'\s*"[^"]*"', model.mask[st.start:st.end]):
            depth = model.mask[st.start:st.start + m.start()].count("(") - model.mask[st.start:st.start + m.start()].count(")")
            if depth == 0:
                units.append([(st.start + m.start(), st.start + m.end(), "")])
    return units


def _declared_name(model, st):
    """The component name a plain declaration statement declares, or None."""
    if st.kind != "plain" or st.keyword in _NOT_DECLARATIONS:
        return None
    m = _DECLARATION_RE.match(model.mask[st.start:st.end])
    if not m or m.group(2) in _NOT_DECLARATIONS:
        return None
    return m.group(3), m.group(2)


def _uses(model, ci, name, exclude):
    """Statements of class ``ci`` that refer to component ``name``."""
    pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"\b")
    return [st for cj, st in model.statements
            if cj == ci and st is not exclude and st.kind != "section"
            and pat.search(model.mask, st.start, st.end)]


def _component_unit(model, ci, st, name):
    unit = model.remove(st.start, st.end)
    for use in _uses(model, ci, name, st):
        unit += model.remove(use.start, use.end)
    return unit


def units_classes(model):
    units = []
    declarations = [(ci, st, _declared_name(model, st)) for ci, st in model.statements]
    for i, c in enumerate(model.classes):
        if i in model.protected or c.parent == -1 and not model.protected:
            continue
        unit = model.remove(_class_start(model.mask, c), c.full_end)
        for ci, st, decl in declarations:
            if decl and (decl[1] == c.name or decl[1].endswith("." + c.name)):
                unit += _component_unit(model, ci, st, decl[0])
            elif st.keyword == "extends" and re.match(r"extends\s+(?:[\w.]*\.)?" + re.escape(c.name) + r"\b",
                                                      model.mask[st.start:st.end]):
                unit += model.remove(st.start, st.end)
        units.append(unit)
    return units


def units_components(model):
    units = []
    for ci, st in model.statements:
        decl = _declared_name(model, st)
        if decl:
            units.append(_component_unit(model, ci, st, decl[0]))
    return units


def units_statements(model):
    units = []
    for _, st in model.statements:
        if st.kind != "section":
            units.append(model.remove(st.start, st.end))
    for ci, c in enumerate(model.classes):
        tops = mp.class_statements(c, model.mask, model.classes) if _is_long(c) else []
        for k, st in enumerate(tops):
            following = tops[k + 1] if k + 1 < len(tops) else None
            if st.kind == "section" and (following is None or following.kind == "section"):
                units.append(model.remove(st.start, st.end))
    return units


def _paren_after(mask, pos, limit):
    pos = re.compile(r"\s*").match(mask, pos, limit).end()
    if pos < limit and mask[pos] == "(":
        close = mo_edit.balanced_close(mask, pos)
        if close > 0:
            return pos, close + 1
    return None


def _split_args(mask, open_idx, close_idx):
    args, depth, start = [], 0, open_idx + 1
    for i in range(open_idx + 1, close_idx):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            args.append((start, i))
            start = i + 1
    args.append((start, close_idx))
    return [(s, e) for s, e in args if mask[s:e].strip()]


_NOT_DECLARATIONS = ("annotation", "connect", "import", "external", "extends", "der", "reinit", "assert",
                     "terminate", "when", "if", "for", "while", "return", "break")
_NOT_EQUATIONS = ("annotation", "connect", "import", "external", "extends", "assert", "terminate", "reinit",
                  "return", "break")
_DECLARATION_RE = re.compile(
    r"((?:(?:parameter|constant|discrete|input|output|flow|stream|inner|outer|replaceable|redeclare|final|each)\s+)*)"
    r"([A-Za-z_][\w.]*)\s+('[^']*'|\w+)(\s*\[[^\]]*\])?")


_BINDING_END_RE = re.compile(r'"|\bannotation\b|;')


def _declaration_parts(model, st):
    """``(prefixes, modifier span, binding span)`` of a declaration or extends clause, or None.
    The spans are None when absent; the binding span starts at its ``=``."""
    if st.kind != "plain" or st.keyword in ("annotation", "connect", "import", "external"):
        return None
    body = model.mask[st.start:st.end]
    if st.keyword == "extends":
        word = re.match(r"(extends\s+)()([A-Za-z_][\w.]*)()", body)
    else:
        word = _DECLARATION_RE.match(body)
    if not word:
        return None
    mods = _paren_after(model.mask, st.start + word.end(), st.end)
    after = mods[1] if mods else st.start + word.end()
    binding = None
    if st.keyword != "extends" and re.match(r"\s*=", model.mask[after:st.end]):
        stop = _BINDING_END_RE.search(model.mask, after, st.end)
        end = stop.start() if stop else st.end - 1
        while end > after and model.mask[end - 1].isspace():
            end -= 1
        binding = (after, end)
    return word.group(1), mods, binding


def units_modifiers(model):
    units = []
    for _, st in model.statements:
        parts = _declaration_parts(model, st)
        if not parts:
            continue
        prefixes, mods, binding = parts
        if mods:
            units.append([(mods[0], mods[1], "")])
            args = _split_args(model.mask, mods[0], mods[1] - 1)
            if len(args) > 1:
                for k, (s, e) in enumerate(args):
                    units.append([(args[k - 1][1], e, "")] if k else [(s, args[1][0], "")])
        # a parameter or constant left without a value only adds a warning to the reproducer
        if binding and not re.search(r"\b(?:parameter|constant)\b", prefixes):
            units.append([(binding[0], binding[1], "")])
    return units


def units_branches(model):
    units = []
    for _, st in model.statements:
        if st.kind == "block" and st.keyword in ("if", "when"):
            for k, (kw_start, body_start, body_end, stmts) in enumerate(st.branches):
                units.append([(st.start, st.end, model.text[body_start:body_end].strip())])
                if k and not stmts:
                    units.append([(kw_start, body_end, "")])
    return units


def _right_hand_side(model, st):
    """``(start, end)`` of the right-hand side of an equation or assignment, or None."""
    if st.kind != "plain" or st.keyword in _NOT_EQUATIONS or _declared_name(model, st):
        return None
    depth = 0
    for i in range(st.start, st.end - 1):
        c = model.mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c == "=" and model.mask[i - 1] not in "<>=" and model.mask[i + 1] != "=":
            return i + 1, st.end - 1
    return None


def _terms(mask, start, end):
    """Spans of the top-level additive terms of ``mask[start:end]``, each with its leading operator."""
    if re.search(r"\bif\b", mask[start:end]):
        return []
    cuts, depth = [], 0
    for i in range(start, end):
        c = mask[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c in "+-":
            before = mask[start:i].rstrip()
            if before and (before[-1].isalnum() or before[-1] in ")]_'") and not re.search(r"\d[eE]$", before):
                cuts.append(i)
    bounds = [start] + cuts + [end]
    return [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]


def units_terms(model):
    units = []
    for _, st in model.statements:
        rhs = _right_hand_side(model, st)
        terms = _terms(model.mask, *rhs) if rhs else []
        if len(terms) < 2:
            continue
        for k, (s, e) in enumerate(terms):
            if k:
                units.append([(s, e, "")])
            else:
                nxt = model.mask[terms[1][0]]
                units.append([(s, terms[1][0] + 1, " ")] if nxt == "+" else [(s, terms[1][0], " ")])
    return units


_REFERENCE_RE = re.compile(r"(?<![\w.'])[A-Za-z_]\w*(?:\[[^\]]*\])?(?:\.[A-Za-z_]\w*(?:\[[^\]]*\])?)+(?![\w(.\[])")


def units_references(model):
    units = []
    for _, st in model.statements:
        parts = _declaration_parts(model, st)
        for span in (_right_hand_side(model, st), parts and parts[2]):
            if span:
                units += [[(m.start(), m.end(), "0")] for m in _REFERENCE_RE.finditer(model.mask, *span)]
    return units


PASSES = (("cosmetic", units_cosmetic), ("classes", units_classes), ("components", units_components),
          ("statements", units_statements), ("terms", units_terms), ("references", units_references),
          ("modifiers", units_modifiers), ("branches", units_branches))


def _apply(text, units):
    edits, last = [], -1
    for s, e, rep in sorted((ed for u in units for ed in u), key=lambda x: (x[0], -x[1])):
        if s < last:
            continue
        edits.append(mo_edit.Edit(s, e, rep))
        last = e
    return mo_edit.splice(text, edits)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _meaningful_lines(text):
    return sum(1 for line in text.splitlines() if line.strip())


_TIDY_RE = re.compile(r"[ \t]+(?=[\n;,)])|(?<=\()[ \t]+|(?<=[^\s(])(?P<gap>[ \t]{2,})(?=\S)")


def _tidy(text):
    mask = mp.mask_code(text)
    edits = [mo_edit.Edit(m.start(), m.end(), " " if m.group("gap") else "")
             for m in _TIDY_RE.finditer(mask) if text[m.start():m.end()] == m.group(0)]
    text = mo_edit.splice(text, edits)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n") + "\n"


class Minimizer:
    def __init__(self, args, runner, target, text, eol, best_path):
        self.args = args
        self.runner = runner
        self.target = target
        self.text = text
        self.eol = eol
        self.best_path = best_path
        self.deadline = time.time() + args.budget
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=args.j)

    def _out_of_time(self):
        return time.time() > self.deadline

    def _accept(self, text, label):
        self.text = text
        mo_edit.write_atomic(self.best_path, self.text, self.eol)
        print("  %-10s -> %d lines" % (label, _meaningful_lines(self.text)), file=sys.stderr, flush=True)
        if self.runner.msl == "yes" and not re.search(r"\b(?:Modelica|Complex)\b", mp.mask_code(self.text)):
            self.runner.msl = "no"
            if self.runner.reproduces(self.text, self.target):
                print("  (the model no longer needs the Modelica Standard Library)", file=sys.stderr)
            else:
                self.runner.msl = "yes"

    def _first_success(self, candidates):
        """Index of the first candidate text that reproduces the failure, or None."""
        for base in range(0, len(candidates), self.args.j):
            if self._out_of_time():
                return None
            batch = candidates[base:base + self.args.j]
            results = list(self.pool.map(lambda t: self.runner.reproduces(t, self.target), batch))
            for k, ok in enumerate(results):
                if ok:
                    return base + k
        return None

    def reduce_pass(self, label, make_units):
        progressed = False
        parts = 2
        while not self._out_of_time():
            try:
                units = make_units(Model(self.text, self.runner.name))
            except mp.ParseError as e:
                print("  %-10s skipped: cannot parse the model (%s)" % (label, e),
                      file=sys.stderr, flush=True)
                return progressed
            if not units:
                return progressed
            parts = min(parts, len(units))
            size = math.ceil(len(units) / parts)
            chunks = [units[i:i + size] for i in range(0, len(units), size)]
            candidates = []
            for chunk in chunks:
                cand = _apply(self.text, chunk)
                if cand != self.text:
                    candidates.append(cand)
            hit = self._first_success(candidates)
            if hit is not None:
                self._accept(candidates[hit], label)
                progressed = True
                parts = max(parts - 1, 2)
            elif size == 1:
                return progressed
            else:
                parts = min(parts * 2, len(units))
        return progressed

    def run(self):
        while not self._out_of_time():
            progressed = False
            for label, make_units in PASSES:
                progressed |= self.reduce_pass(label, make_units)
            if not progressed:
                break
        tidy = _tidy(self.text)
        if tidy != self.text and self.runner.reproduces(tidy, self.target):
            self._accept(tidy, "tidy")
        self.pool.shutdown()
        return self.text


def capture_failure(runner, text, stage):
    stages = STAGES if stage == "auto" else (stage,)
    last = {}
    for st in stages:
        t0 = time.time()
        summary = runner.run(text, st)
        last = summary
        data = summary.get("compiler_failure")
        if data:
            return st, kernel_failure.Failure(**data), time.time() - t0, summary
        if summary.get("failed") or summary.get("timed_out"):
            break
    return None, None, 0.0, last


_TEMPDIR_MARKER = ".wsm_minimize"


def claim_tempdir(tempdir):
    """Create ``tempdir`` or reuse one this script made before; True when it is new.
    Refuses any other non-empty directory, whose files the run would overwrite."""
    marker = os.path.join(tempdir, _TEMPDIR_MARKER)
    existing = os.path.isdir(tempdir) and bool(os.listdir(tempdir))
    if existing and not os.path.isfile(marker):
        raise SystemExit("ERROR: %s is not empty and was not created by minimize_mo.py; "
                         "pass a new --tempdir" % tempdir)
    os.makedirs(tempdir, exist_ok=True)
    open(marker, "w").close()
    return not existing


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help=".mo file, or a directory-form library")
    ap.add_argument("--name", required=True, help="full dotted name of the failing model")
    ap.add_argument("--stage", default="auto", choices=("auto",) + STAGES,
                    help="stage that shows the failure (auto: the first of instantiate, check, build, sim)")
    ap.add_argument("--strict", action="store_true",
                    help="require the full failure message to match, not just the failing step")
    ap.add_argument("-j", type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)),
                    help="candidates run in parallel")
    ap.add_argument("--budget", type=int, default=1800, help="total time limit in seconds")
    ap.add_argument("--timeout", type=int, default=300, help="time limit of one kernel run in seconds")
    ap.add_argument("--tempdir", help="work directory (default <model-dir>/_wsm_minimize_temp)")
    ap.add_argument("--msl", default="auto", choices=("auto", "yes", "no"))
    ap.add_argument("--wsm-home")
    ap.add_argument("--load-library", action="append", default=[], metavar="NAME[==VER]")
    ap.add_argument("--load", action="append", default=[], metavar="FILE")
    ap.add_argument("--keep-runs", action="store_true", help="keep every candidate's run directory")
    args = ap.parse_args()

    text, eol, file_name = load_model(args.model)
    base_dir = os.path.dirname(os.path.abspath(args.model.rstrip("/\\")))
    tempdir = os.path.abspath(args.tempdir or os.path.join(base_dir, "_wsm_minimize_temp"))
    created = claim_tempdir(tempdir)
    workdir = os.path.join(tempdir, "runs")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir)
    mo_edit.write_atomic(os.path.join(tempdir, "original.mo"), text, eol)
    best_path = os.path.join(tempdir, "best.mo")
    print("Working in %s" % tempdir, file=sys.stderr)

    runner = Runner(args, args.name, file_name, workdir)
    stage, target, seconds, summary = capture_failure(runner, text, args.stage)
    if target is None:
        if summary.get("timed_out"):
            outcome = "did not finish within %d seconds" % args.timeout
        elif "failed" not in summary:
            outcome = "could not be run (see below)"
        elif summary.get("failed"):
            outcome = "fails with an ordinary model error (see below)"
        else:
            outcome = "runs"
        print("No compiler failure: the model %s. Nothing to minimize." % outcome, file=sys.stderr)
        if summary.get("stderr"):
            print(summary["stderr"].strip()[-4000:], file=sys.stderr)
        shutil.rmtree(tempdir if created else workdir, ignore_errors=True)
        return 2
    runner.stage = stage
    runner.msl = "yes" if summary.get("msl_version") else "no"
    runner.timeout = min(args.timeout, max(60, int(seconds * 10)))
    print("Reproduced at stage '%s' (%.1fs): [%s] %s" % (stage, seconds, target.kind, target.head),
          file=sys.stderr, flush=True)

    mo_edit.write_atomic(best_path, text, eol)
    t0 = time.time()
    minimal = Minimizer(args, runner, target, text, eol, best_path).run()
    final = runner.failure_of(minimal)
    result = {
        "stage": stage,
        "failure": target.to_dict(),
        "reproduced_by_minimal": target.matches(final, strict=args.strict),
        "minimal_failure": final.to_dict() if final else None,
        "original_lines": _meaningful_lines(text),
        "minimal_lines": _meaningful_lines(minimal),
        "kernel_runs": runner.runs,
        "seconds": round(time.time() - t0, 1),
        "budget_exhausted": time.time() - t0 >= args.budget,
        "minimal": best_path,
        "msl": runner.msl == "yes",
        "kernel_version": summary.get("version"),
    }
    with open(os.path.join(tempdir, "minimize.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps(result, indent=2))
    return 0 if result["reproduced_by_minimal"] else 1


if __name__ == "__main__":
    sys.exit(main())
