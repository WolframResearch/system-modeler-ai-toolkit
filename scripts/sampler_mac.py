"""
macOS sampling backend for profile_sim.py.

Runs the built simulation under /usr/bin/sample and turns its call graph into
self time per call stack. The call graph is used rather than sample's own
"Sort by top of stack" summary because that summary drops every entry below five
samples, which would leave the percentages short of 100%.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter

import sampler_common

SAMPLE_TOOL = os.environ.get("WSM_PROFILER") or "/usr/bin/sample"

# "   +   ! : 730 someFunc(int)  (in Slow.exe) + 2428  [0x100954950]  Slow_ode.cpp:41"
# The tree is drawn with spaces and the characters + ! : | before the count, so
# the count's column is the node's depth.
_NODE_RE = re.compile(r"^(?P<indent>[ +!:|]*?)(?P<count>\d+) (?P<rest>\S.*)$")
_IMAGE_RE = re.compile(r"\s{2}\(in .*")
_LINE_RE = re.compile(r"\]\s+(\S+:\d+)\s*$")


def _strip_signature(name):
    """Drop a trailing C++ parameter list so names read like the other backends'."""
    if not name.endswith(")"):
        return name
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        if name[i] == ")":
            depth += 1
        elif name[i] == "(":
            depth -= 1
            if depth == 0:
                return name[:i] or name
    return name


def _normalize(rest):
    line = _LINE_RE.search(rest)
    name = _strip_signature(_IMAGE_RE.sub("", rest).strip())
    if name.startswith("DYLD-STUB$$"):
        name = name[len("DYLD-STUB$$"):]
    if name == "???":
        return "(unsymbolicated)"
    name = sampler_common.normalize(name)
    return "%s@%s" % (name, line.group(1)) if line else name


def parse_stacks(text):
    """Samples per call stack, from the busiest thread of a `sample` report.

    Each key is the stack outermost-frame first; the count is that stack's self
    samples, so the report can charge a sample either to its innermost frame or
    to the nearest enclosing frame it recognises."""
    nodes = []
    in_graph = False
    for line in text.splitlines():
        if not in_graph:
            in_graph = line.startswith("Call graph:")
            continue
        if line and not line[0].isspace():
            break                                  # "Total number in stack ..."
        m = _NODE_RE.match(line)
        if m:
            nodes.append((len(m.group("indent")), int(m.group("count")),
                          m.group("rest")))

    if not nodes:
        return Counter()
    root_depth = min(d for d, _, _ in nodes)

    # Each thread is one root node; mirror the Windows backend and keep the
    # busiest one, so idle threads do not dilute the shares.
    threads, current = [], None
    for node in nodes:
        if node[0] == root_depth:
            current = []
            threads.append(current)
        if current is not None:
            current.append(node)
    busiest = max(threads, key=lambda t: t[0][1])

    self_counts = [c for _, c, _ in busiest]
    ancestors = []                                 # (depth, index) of open frames
    paths = [()] * len(busiest)
    for i, (depth, count, rest) in enumerate(busiest):
        while ancestors and ancestors[-1][0] >= depth:
            ancestors.pop()
        if ancestors:
            parent = ancestors[-1][1]
            self_counts[parent] -= count
            paths[i] = paths[parent] + (_normalize(rest),)
        ancestors.append((depth, i))

    counts = Counter()
    for i in range(1, len(busiest)):               # 0 is the thread line itself
        if self_counts[i] > 0 and paths[i]:
            counts[paths[i]] += self_counts[i]
    return counts


def sample(exe, sim, hz, seconds, result=False):
    workdir = tempfile.mkdtemp(prefix="wsm_profile_")
    report = os.path.join(workdir, "sample.txt")
    interval_ms = max(1, int(round(1000.0 / max(hz, 1))))
    proc, log = sampler_common.launch(exe, sim, result)
    started = time.time()
    try:
        sampler = subprocess.Popen(
            [SAMPLE_TOOL, str(proc.pid), str(max(1, int(round(seconds)))),
             str(interval_ms), "-mayDie", "-f", report],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wall, ended_early = sampler_common.wait_for_sampler(
            sampler, proc, started, seconds)
    finally:
        sampler_common.stop(proc)

    try:
        with open(report, "r", encoding="utf-8", errors="replace") as fh:
            counts = parse_stacks(fh.read())
    except OSError:
        counts = Counter()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return counts, wall, (ended_early, sampler_common.tail_log(log))
