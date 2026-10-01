"""Diagram auto-layout for composite models.

Pure-Python, no third-party dependency. The components are split into bands — groups
joined by connections — stacked top to bottom, and each band is laid out left to right:

* An electrical network of two-terminal components with a ground is drawn as a ladder:
  series components along a top wire, shunt components standing between it and the
  ground, the ground beneath the component it grounds.
* Anything else is layered by flow. Signal connections (output to input) set the
  direction, physical ones join their neighbours. A block that only feeds a signal back
  to an earlier one sits on a return row below the forward path, mirrored so its label
  stays upright. Each component is then moved up or down so its pins line up with its
  neighbours', which straightens chains and fans inputs out in the order of the pins
  they drive.

Last, each component is tried mirrored left to right, top to bottom and both, and a flip
is kept where it makes the wiring cheaper to route: shorter, with fewer bends, and no
line leaving its pin backwards or crossing a body.

A reference (ground, housing, fixed temperature — see ``references.py``) anchoring a
single component is parked beside the pin it connects to; one shared by several goes on
a rail along the bottom, and supplies rail along the top. After the flips, each reference
moves to the cheapest free spot beside or below its pins. Pin positions come from
``pins.py``; placements are on a 2-unit grid, and lines end wherever the pins are.
"""

from __future__ import annotations

from . import icon as icon_mod
from . import pins
from . import references
from .parser import ClassSpan
from .routing import BOX, GRID, path_cost, pin_point, route, route_connect, transform

DX = 40          # column pitch
DY = 40          # row pitch
DY_PARK = 70     # row pitch in a band whose references park beside their components
LABEL = 16       # room above and below an icon for its name and parameter text
BAND_GAP = 40    # space between the icons of two bands
PARK = 20        # distance from a pin to the reference parked on it
GROUND_RUN = 10  # drop from a ladder's shunt pins to the wire joining them along the bottom
FLIP_MARGIN = 20  # routing cost a flip has to save before it is taken
UPSIDE_DOWN = 30  # charged for a flip that turns an icon upside down, which swaps its labels


def _round(v: float) -> int:
    return int(round(v / GRID)) * GRID


def _is_source(inst) -> bool:
    t = pins.type_of(inst)
    return (".Sources." in t) or t.endswith("RealExpression") or ("Source" in t.split(".")[-1])


def _is_reference(inst, local_refs=None) -> bool:
    return (references.is_reference(inst, local_refs)
            or pins.type_of(inst).split(".")[-1] == "Ground"
            or inst.name.lower() in ("gnd", "ground"))


def _is_supply(inst) -> bool:
    t = pins.type_of(inst)
    n = inst.name.lower()
    return ("ConstantVoltage" in t and ("sup" in n or "vcc" in n or "vdd" in n or "batt" in n
                                        or "rail" in n or n in ("v", "vs"))) or n in ("supply",)


class _Net:
    """The connections among a class's instances, with each end's pin."""

    def __init__(self, cls: ClassSpan, type_ports, refs=()):
        self.types = {i.name: pins.type_of(i) for i in cls.instances}
        self.type_ports = type_ports or {}
        self.edges = []              # (inst, port, inst, port) between two instances
        self.ports = {n: [] for n in self.types}
        for cn in cls.connects:
            a, b = cn.from_inst, cn.to_inst
            for inst, port in ((a, cn.from_port), (b, cn.to_port)):
                if inst in self.ports and port and port not in self.ports[inst]:
                    self.ports[inst].append(port)
            if a in self.types and b in self.types and a != b and cn.from_port and cn.to_port:
                self.edges.append((a, cn.from_port, b, cn.to_port))
        self._parent = {}
        for a, pa, b, pb in self.edges:
            self._parent[self.net(a, pa)] = self.net(b, pb)
        self.ground = {self.net(g, p) for g in refs for p in self.ports.get(g, [])}

    def net(self, inst: str, port: str):
        """Representative pin of the set of pins joined by connections to this one."""
        k = (inst, port)
        self._parent.setdefault(k, k)
        while self._parent[k] != k:
            self._parent[k] = self._parent[self._parent[k]]
            k = self._parent[k]
        return k

    def nets(self, cls: ClassSpan) -> dict:
        """``{(inst, port): net}`` for both ends of every connection, class connectors
        included, so lines of one net may share a run."""
        for cn in cls.connects:
            self._parent[self.net(cn.from_inst, cn.from_port)] = self.net(cn.to_inst, cn.to_port)
        return {k: self.net(*k) for cn in cls.connects
                for k in ((cn.from_inst, cn.from_port), (cn.to_inst, cn.to_port))}

    def grounded(self, inst: str, port: str) -> bool:
        return self.net(inst, port) in self.ground

    def pin(self, inst: str, port: str) -> tuple:
        return pins.resolve(self.types[inst], port, self.type_ports)

    def direction(self, edge):
        """``(source, target)`` of a signal connection, or None for a physical one."""
        a, pa, b, pb = edge
        ka, kb = self.pin(a, pa)[2], self.pin(b, pb)[2]
        if ka == "o" and kb == "i":
            return a, b
        if ka == "i" and kb == "o":
            return b, a
        return None

    def neighbours(self, n: str, within) -> list:
        out = []
        for a, _, b, _ in self.edges:
            if a == n and b in within and b not in out:
                out.append(b)
            elif b == n and a in within and a not in out:
                out.append(a)
        return out


def compute_layout(cls: ClassSpan, type_ports: dict | None = None,
                   local_refs: set | None = None) -> dict:
    """Compute the diagram layout.

    Returns a dict with:
      'instances'      : {name: (ox, oy, rot, mirror)}  component placements
      'connectors'     : {name: (ox, oy)}               class connectors on the border
      'connector_dirs' : {name: (dx, dy)}               direction a line leaves each one
      'inst_types'     : {name: type_name}              so routing can locate each pin
      'type_ports'     : {leaf_type: {conn: pin}}       pins of the file's own classes
      'boxes'          : {name: (x1, y1, x2, y2)}       placed icon frames
      'channels'       : [y, ...]                        preferred horizontal wire runs
      'extent'         : ((x1,y1),(x2,y2))
    """
    inst_by_name = {i.name: i for i in cls.instances}
    names = [i.name for i in cls.instances]
    refs = [n for n in names if _is_reference(inst_by_name[n], local_refs)]
    net = _Net(cls, type_ports, refs)
    rails = {n for n in names if _is_supply(inst_by_name[n]) and n not in refs
             and _feeds_many(n, net)}
    live = [n for n in names if n not in refs]

    # A supply feeding several components is drawn as a rail along the top, unless its
    # band is a ladder: there it is one more shunt, and the ladder already reads as a rail.
    placements, channels, shared, supplies = {}, [], [], []
    top = 0
    pieces = []
    for band in _bands(live, net):
        band_refs = [g for g in refs if net.neighbours(g, live)
                     and set(net.neighbours(g, live)) <= set(band)]
        laid = _ladder(band, net, band_refs, inst_by_name)
        if laid is not None:
            pieces.append(laid)
            continue
        supplies += [n for n in band if n in rails]
        rest = [n for n in band if n not in rails]
        for sub in _bands(rest, net):
            sub_refs = [g for g in band_refs if set(net.neighbours(g, rest)) <= set(sub)
                        and net.neighbours(g, rest)]
            pieces.append(_ladder(sub, net, sub_refs, inst_by_name)
                          or _layered(sub, net, sub_refs, inst_by_name))
    for local, local_channels, leftover in pieces:
        shared += leftover
        (x1, y1), (x2, y2) = _bbox(local)
        dy = top - y2
        for n, (x, y, r, m) in local.items():
            placements[n] = (x - x1, y + dy, r, m)
        channels += [c + dy for c in local_channels]
        top = y1 + dy - BAND_GAP
    shared += [g for g in refs if g not in placements and g not in shared]

    _rail(shared, placements, net, below=True)
    _rail(supplies, placements, net, below=False)
    connectors, connector_dirs = _place_connectors(cls, placements, net)
    _center(placements, connectors, channels)

    boxes = {n: (x - BOX, y - BOX, x + BOX, y + BOX) for n, (x, y, _, _) in placements.items()}
    layout = {
        "instances": placements,
        "connectors": connectors,
        "connector_dirs": connector_dirs,
        "inst_types": dict(net.types),
        "type_ports": type_ports or {},
        "boxes": boxes,
        "channels": channels,
        "nets": net.nets(cls),
        "extent": _extent(placements, connectors),
    }
    _flip_for_routing(cls, layout, set(refs))
    _settle_references(cls, layout, refs, net)
    return layout


def _flips(rot: int, mirror: bool) -> list:
    """``(rotation, mirror)`` of a placement mirrored left to right, top to bottom, and both,
    about the diagram's axes."""
    return [((-rot) % 360, not mirror), ((180 - rot) % 360, not mirror), ((rot + 180) % 360, mirror)]


def _flip_for_routing(cls: ClassSpan, layout: dict, refs: set):
    """Keep each component's flip that makes its own lines cheaper to route.

    The diagram is routed once; each flip then re-routes only the lines of the component
    it turns, around everyone else's. References stay as parked. A flip is taken only when
    it saves ``FLIP_MARGIN``, so a symmetric component is never flipped for nothing, and
    one that turns an icon upside down pays ``UPSIDE_DOWN`` on top.
    """
    placed = layout["instances"]
    conns = cls.connects
    drawn, segs, costs = [], [], []
    for cn in conns:
        start = len(drawn)
        costs.append(route_connect(cn, layout, drawn)[1])
        segs.append(drawn[start:])

    def trial(n, idx, others):
        wires, total, new = list(others), 0.0, {}
        for i in idx:
            start = len(wires)
            cost = route_connect(conns[i], layout, wires)[1]
            total += cost
            new[i] = (wires[start:], cost)
        return total + UPSIDE_DOWN * (placed[n][2] == 180), new

    def clean(i):
        """True for a line that takes no detour, turns at most twice, and costs only its
        length and bends: no flip can shorten it."""
        if not segs[i]:
            return True
        length = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for _, (p, q) in segs[i])
        (a, _), (_, b) = segs[i][0][1], segs[i][-1][1]
        bends = len(segs[i]) - 1
        return (bends <= 2 and length == abs(a[0] - b[0]) + abs(a[1] - b[1])
                and costs[i] <= length + 25 * bends)

    lines_of = {n: [i for i, cn in enumerate(conns) if n in (cn.from_inst, cn.to_inst)]
                for n in placed}
    todo = [n for n in placed if n not in refs]
    for _ in range(2):
        flipped = set()
        for n in todo:
            idx = lines_of[n]
            if all(clean(i) for i in idx):
                continue
            others = [s for i, ss in enumerate(segs) if i not in idx for s in ss]
            x, y, rot, mirror = placed[n]
            best, new = trial(n, idx, others)
            keep = (placed[n], new)
            for r, m in _flips(rot, mirror):
                placed[n] = (x, y, r, m)
                cost, new = trial(n, idx, others)
                if cost < best - FLIP_MARGIN:
                    best, keep = cost, (placed[n], new)
            if keep[0][2:] != (rot, mirror):
                flipped.add(n)
            placed[n] = keep[0]
            for i, (ss, cost) in keep[1].items():
                segs[i], costs[i] = ss, cost
        # only the neighbours of what flipped have lines that changed
        todo = [m for m in placed if m not in refs and m not in flipped
                and any(set(lines_of[m]) & set(lines_of[f]) for f in flipped)]
        if not todo:
            break


def _settle_references(cls: ClassSpan, layout: dict, refs, net: _Net):
    """Move each reference to the cheapest free spot beside the pins it connects to, now
    that the flips have settled which way those pins face."""
    placed, conns = layout["instances"], cls.connects
    segs = []
    for cn in conns:
        drawn = []
        route_connect(cn, layout, drawn)
        segs.append(drawn)
    moved = False
    for g in refs:
        mine = [i for i, cn in enumerate(conns) if g in (cn.from_inst, cn.to_inst)]
        if len(net.ports.get(g, [])) != 1 or not mine or g not in placed:
            continue
        others = [s for i, ss in enumerate(segs) if i not in mine for s in ss]
        home = placed[g]

        def cost(spot):
            placed[g] = spot
            layout["boxes"][g] = (spot[0] - BOX, spot[1] - BOX, spot[0] + BOX, spot[1] + BOX)
            return sum(route_connect(conns[i], layout, list(others))[1] for i in mine)

        best, best_cost = home, cost(home) - FLIP_MARGIN
        for spot in _reference_spots(g, placed, net):
            c = cost(spot)
            if c < best_cost:
                best, best_cost = spot, c
        cost(best)
        moved |= best != home
        for i in mine:
            segs[i] = []
            route_connect(conns[i], layout, segs[i])
    if moved:
        layout["extent"] = _extent(placed, layout["connectors"])


def _reference_spots(g, placed, net: _Net) -> list:
    """Free placements for reference ``g`` below the pins it connects to, and the spot
    ``_park_spot`` finds beside a single one."""
    port = net.ports[g][0]
    q = net.pin(g, port)
    local = {n: p for n, p in placed.items() if n != g}
    ends = [(b, pb) if a == g else (a, pa) for a, pa, b, pb in net.edges
            if g in (a, b) and (b if a == g else a) in local]
    if not ends:
        return []
    spots = []
    if len(ends) == 1:
        spot = _park_spot(g, port, ends[0][0], net.pin(*ends[0]), local, net)
        if spot:
            spots.append(spot)
    pts = [pin_point(local[o], net.pin(o, op))[0] for o, op in ends]
    low = min(y for _, y in pts)
    qx, qy = q[0] * BOX / 100.0, q[1] * BOX / 100.0
    for x in {p[0] for p in pts} | {_round(sum(p[0] for p in pts) / len(pts))}:
        for drop in (PARK, PARK + DY // 2):
            ox, oy = _round(x - qx), _round(low - drop - qy)
            me = (ox - BOX, oy - BOX, ox + BOX, oy + BOX)
            if not any(me[0] < b[2] + 4 and me[2] > b[0] - 4
                       and me[1] < b[3] + LABEL and me[3] > b[1] - LABEL for _, b in _boxes(local)):
                spots.append((ox, oy, 0, False))
    return spots


def _feeds_many(n: str, net: _Net) -> bool:
    """True if a supply's live pin reaches three or more other components — a rail worth
    drawing along the top rather than one source in its own circuit."""
    live = {net.net(n, p) for p in net.ports[n] if not net.grounded(n, p)}
    ends = {(i, p) for a, pa, b, pb in net.edges for i, p in ((a, pa), (b, pb))}
    fed = {i for i, p in ends if i != n and net.net(i, p) in live}
    return len(fed) >= 3


def _bands(core: list, net: _Net) -> list:
    """Groups of core instances joined by connections, in declaration order."""
    seen, bands = set(), []
    for n in core:
        if n in seen:
            continue
        band, stack = [], [n]
        seen.add(n)
        while stack:
            u = stack.pop()
            band.append(u)
            for v in net.neighbours(u, core):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        bands.append(sorted(band, key=core.index))
    return bands


# ---------------------------------------------------------------------------
# ladder: electrical networks of two-terminal components
# ---------------------------------------------------------------------------

def _ladder(band, net: _Net, refs, inst_by_name):
    """Ladder layout of an electrical two-terminal network — ``(placements, channels,
    unparked references)`` — or None if it is not one."""
    if len(band) < 2 or not refs:
        return None
    ends = {}
    for n in band:
        ports = net.ports[n]
        if len(ports) != 2:
            return None
        pp = [net.pin(n, p) for p in ports]
        if any(p[2] != "e" for p in pp) or {pins.side(p[0], p[1]) for p in pp} != {"L", "R"}:
            return None
        ends[n] = ports if pp[0][0] < 0 else ports[::-1]      # (left port, right port)

    def find(k):
        return net.net(*k)

    ground = {find((g, p)) for g in refs for p in net.ports[g]}
    if not ground:
        return None

    shunts, series = {}, {}
    for n in band:
        la, ra = (find((n, p)) for p in ends[n])
        if la in ground and ra in ground:
            return None
        if la in ground or ra in ground:
            shunts.setdefault(ra if la in ground else la, []).append(n)
        else:
            series.setdefault(frozenset((la, ra)), []).append(n)
    if any(len(k) != 2 for k in series):
        return None
    order = _path_order(set(shunts) | {x for k in series for x in k}, series,
                        lambda k: any(_is_source(inst_by_name[s]) for s in shunts.get(k, [])))
    if order is None:
        return None

    local, x = {}, 0
    for i, node in enumerate(order):
        for s in sorted(shunts.get(node, []), key=lambda s: not _is_source(inst_by_name[s])):
            left_on_top = find((s, ends[s][0])) == node
            local[s] = (x, 0, 270 if left_on_top else 90, False)
            x += DX
        if i + 1 < len(order):
            for j, s in enumerate(series[frozenset((node, order[i + 1]))]):
                local[s] = (x, DY + j * DY, 0, find((s, ends[s][0])) != node)
            x += DX

    leftover = []
    under = {}                       # shunt -> the reference parked beneath it
    for g in refs:
        anchors = [b if a == g else a for a, _, b, _ in net.edges
                   if g in (a, b) and (b if a == g else a) in local]
        shunt_anchor = next((s for s in anchors if s in [v for vs in shunts.values() for v in vs]
                             and s not in under), None)
        if shunt_anchor is None:
            leftover.append(g)
            continue
        under[shunt_anchor] = g
        sx, sy, _, _ = local[shunt_anchor]
        q = net.pin(g, net.ports[g][0])
        local[g] = (sx, _round(sy - BOX - PARK - q[1] * BOX / 100.0), 0, False)
    return local, [-BOX - GROUND_RUN], leftover


def _path_order(nodes, series, prefer_start):
    """The nets in the order the series components chain them, or None if not a chain."""
    adj = {k: set() for k in nodes}
    for pair in series:
        a, b = tuple(pair)
        adj[a].add(b)
        adj[b].add(a)
    if any(len(v) > 2 for v in adj.values()) or len(series) != len(nodes) - 1:
        return None
    ends = [k for k in nodes if len(adj[k]) <= 1]
    if not ends:
        return None
    start = next((k for k in ends if prefer_start(k)), ends[0])
    order, prev = [start], None
    while len(order) < len(nodes):
        nxt = [k for k in adj[order[-1]] if k != prev]
        if not nxt:
            return None
        prev = order[-1]
        order.append(nxt[0])
    return order


# ---------------------------------------------------------------------------
# layered: flow left to right
# ---------------------------------------------------------------------------

def _layered(band, net: _Net, refs, inst_by_name):
    """Layered layout of one band: ``(placements, channels, unparked references)``."""
    succ = {n: [] for n in band}
    pred = {n: [] for n in band}
    und = {n: [] for n in band}
    inside = set(band)
    for edge in net.edges:
        a, _, b, _ = edge
        if a not in inside or b not in inside:
            continue
        d = net.direction(edge)
        if d:
            succ[d[0]].append(d[1])
            pred[d[1]].append(d[0])
        elif not net.grounded(a, edge[1]):          # a return wire says nothing of order
            und[a].append(b)
            und[b].append(a)

    layer = _layers(band, succ, pred, und, inst_by_name, net)
    back = {(u, v) for u in band for v in succ[u] if layer[v] <= layer[u]}
    returning = _return_chains(back, succ, pred, und, layer)
    on_return = {n for chain, _, _ in returning for n in chain}

    cols = sorted({layer[n] for n in band if n not in on_return})
    col = {n: cols.index(layer[n]) for n in band if n not in on_return}
    parked = any(len(net.neighbours(g, band)) == 1 for g in refs)
    turn = {n: _shunt_orientation(n, net, col) for n in col}
    turn = {n: t for n, t in turn.items() if t}
    ys = _align(band, col, net, DY_PARK if parked else DY, turn)
    local = {n: (col[n] * DX, ys[n]) + turn.get(n, (0, False)) for n in col}

    channels = []
    for chain, target, feeder in returning:
        x_lo, x_hi = sorted((local[target][0], local[feeder][0]))
        span = [y for n, (x, y, _, _) in local.items() if x_lo <= x <= x_hi]
        y_row = _round(min(span) - DY)
        k = len(chain)
        for i, n in enumerate(chain):               # chain[0] feeds the target
            x = _round(x_lo + (x_hi - x_lo) * (i + 1) / (k + 1))
            local[n] = (x, y_row, 0, True)
        channels.append(y_row)

    _orient_two_ports(local, net, set(refs) | {n for n in band if _is_source(inst_by_name[n])})
    leftover = _park_references(refs, local, net)
    return local, channels, leftover


def _layers(band, succ, pred, und, inst_by_name, net) -> dict:
    """Column of each instance: breadth-first from the sources, then longest-path over
    signal connections so each block sits right of every block feeding it."""
    # Signal sources start the flow, and so do sources driving a circuit across two
    # terminals; a one-connector source (a load torque, a heat flow) is left to the end
    # of its chain unless nothing else can start it.
    seeds = [n for n in band if not pred[n] and (
        (succ[n] and not und[n]) or (_is_source(inst_by_name[n]) and len(net.ports[n]) >= 2))]
    seeds = seeds or [n for n in band if not pred[n] and _is_source(inst_by_name[n])]
    layer = {}

    def spread(roots):
        frontier = list(roots)
        for r in roots:
            layer.setdefault(r, 0)
        while frontier:
            nxt = []
            for u in frontier:
                for v in succ[u] + und[u]:
                    if v not in layer:
                        layer[v] = layer[u] + 1
                        nxt.append(v)
            frontier = nxt

    spread(seeds)
    while len(layer) < len(band):
        rest = [n for n in band if n not in layer]
        # A chain with no source starts from one of its ends rather than its middle.
        start = min(rest, key=lambda n: (len(succ[n]) + len(und[n]) != 1, rest.index(n)))
        spread([start])

    back = _back_edges(band, succ, seeds, layer)
    for _ in range(len(band)):
        changed = False
        for u in band:
            for v in succ[u]:
                if (u, v) not in back and layer[v] < layer[u] + 1:
                    layer[v] = layer[u] + 1
                    changed = True
        if not changed:
            break
    # a source feeding only later columns moves up to sit just before its first consumer
    for n in band:
        if not pred[n] and not und[n] and succ[n]:
            ahead = [layer[v] for v in succ[n] if (n, v) not in back]
            if ahead:
                layer[n] = min(ahead) - 1
    low = min(layer.values())
    return {n: layer[n] - low for n in band}


def _back_edges(band, succ, seeds, layer) -> set:
    """Signal connections that close a loop, found by a depth-first walk from the sources.

    A walk that has to start elsewhere — at a sensor reached only through physical
    connections — also counts a connection back to a finished, earlier-column block as
    closing a loop, since the sensor is downstream of it.
    """
    state, back = {}, set()
    for root in seeds + sorted(band, key=lambda n: layer[n]):
        if root in state:
            continue
        from_seed = root in seeds
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                state[u] = 2
                stack.pop()
            elif state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                state[v] = 1
                stack.append((v, iter(succ[v])))
            elif not from_seed and layer[v] < layer[u]:
                back.add((u, v))
    return back


def _return_chains(back, succ, pred, und, layer) -> list:
    """``(chain, target, feeder)`` for each feedback loop with blocks on its return path.

    Walking back from the block that closes the loop, a block joins the return path while
    it has one input and one output and no physical connection; at most half the loop
    (less the two ends) is taken, so the forward path keeps the longer run.
    """
    chains, taken = [], set()
    for u, v in sorted(back):
        limit = (layer[u] - layer[v] + 1 - 2) // 2
        chain, n = [], u
        while (len(chain) < limit and n not in taken and len(pred[n]) == 1
               and len(succ[n]) == 1 and not und[n]):
            chain.append(n)
            n = pred[n][0]
        if chain:
            taken.update(chain)
            chains.append((chain, v, n))
    return chains


def _align(band, col, net: _Net, pitch, turn) -> dict:
    """Vertical position of each forward-path instance, lining its pins up with its
    neighbours' and keeping ``pitch`` between instances of one column.

    Two pins that face along the row line up exactly. Where a pin facing up or down meets
    one facing sideways, the sideways one sits a row away, so the wire between them turns
    once instead of doubling back.
    """
    y = {n: 0.0 for n in col}
    columns = {}
    for n in band:
        if n in col:
            columns.setdefault(col[n], []).append(n)

    def pin(n, port):
        rot, mirror = turn.get(n, (0, False))
        p = net.pin(n, port)
        px, py = transform(p[0], p[1], rot, mirror)
        return py * BOX / 100.0, pins.side(px, py)

    def wish(n, side):
        want = []
        for a, pa, b, pb in net.edges:
            for me, mp, other, op in ((a, pa, b, pb), (b, pb, a, pa)):
                if me != n or other not in col or (col[other] - col[n]) * side <= 0:
                    continue
                if net.grounded(me, mp):
                    continue
                d = net.direction((a, pa, b, pb))
                if d and col[d[0]] >= col[d[1]]:
                    continue                    # a feedback connection
                (my, mine), (oy, theirs) = pin(n, mp), pin(other, op)
                gap = 0
                if mine in ("L", "R") and theirs in ("T", "B"):
                    gap = DY - BOX if theirs == "T" else BOX - DY
                elif theirs in ("L", "R") and mine in ("T", "B"):
                    gap = BOX - DY if mine == "T" else DY - BOX
                want.append(y[other] + oy - my + gap)
        return sum(want) / len(want) if want else None

    keys = sorted(columns)
    # how much of the diagram lies downstream of each instance: at a branch, the one
    # carrying the longer chain keeps the row and the side branch moves off it
    reach = {n: {n} for n in col}
    for c in keys[::-1]:
        for n in columns[c]:
            for other in net.neighbours(n, col):
                if col[other] > c:
                    reach[n] |= reach[other]
    weight = {n: len(r) for n, r in reach.items()}
    for _ in range(3):
        for sweep, side in ((keys, -1), (keys[::-1], 1)):
            for c in sweep:
                desired = {}
                for n in columns[c]:
                    # the backward sweep only places what has nothing to its left
                    w = None if side == 1 and wish(n, -1) is not None else wish(n, side)
                    desired[n] = y[n] if w is None else w
                y.update(_pack(columns[c], desired, pitch, weight))
    return {n: _round(v) for n, v in y.items()}


def _shunt_orientation(n, net: _Net, col):
    """``(rotation, mirror)`` standing an electrical two-terminal component up with its
    grounded pin at the bottom, or None when it has no pin on a ground.

    Of the two ways to do that, the one turning its other pins toward their neighbours
    wins, which puts a controlled source's signal input on the side its signal comes from.
    """
    ports = net.ports[n]
    two = [p for p in ports if net.pin(n, p)[2] == "e"]
    if len(two) != 2 or not any(net.grounded(n, p) for p in two):
        return None
    if all(net.grounded(n, p) for p in two):
        return None
    if {pins.side(*net.pin(n, p)[:2]) for p in two} != {"L", "R"}:
        return None
    low = next(p for p in two if net.grounded(n, p))
    best, best_score = None, None
    for rot in (90, 270):
        for mirror in (False, True):
            gx, gy = transform(*net.pin(n, low)[:2], rot, mirror)
            if pins.side(gx, gy) != "B":
                continue
            score = 0
            for a, pa, b, pb in net.edges:
                for me, mp, other in ((a, pa, b), (b, pb, a)):
                    if me == n and other in col and mp not in two:
                        face = pins.side(*transform(*net.pin(n, mp)[:2], rot, mirror))
                        toward = "L" if col[other] < col[n] else "R"
                        score += face != toward
            if best_score is None or score < best_score:
                best, best_score = (rot, mirror), score
    return best


def _pack(names, desired, pitch, weight=None) -> dict:
    """Positions as near ``desired`` as possible, top to bottom, ``pitch`` apart.

    Where instances crowd each other, the heaviest keeps its own position and the others
    shift around it; among equals they split the difference.
    """
    weight = weight or {}
    order = sorted(names, key=lambda n: (-desired[n], names.index(n)))

    def first(members):
        w = [weight.get(m, 1) for m in members]
        if w.count(max(w)) == 1:
            i = w.index(max(w))
            return desired[members[i]] + i * pitch
        return sum(desired[m] + i * pitch for i, m in enumerate(members)) / len(members)

    blocks = []                      # [first_y, [names]]
    for n in order:
        blocks.append([desired[n], [n]])
        while len(blocks) > 1 and blocks[-2][0] - pitch * len(blocks[-2][1]) < blocks[-1][0]:
            members = blocks.pop(-2)[1] + blocks.pop()[1]
            blocks.append([first(members), members])
    out = {}
    for top, members in blocks:
        for i, m in enumerate(members):
            out[m] = top - i * pitch
    return out


def _orient_two_ports(local, net: _Net, skip):
    """Turn a physical two-terminal component so its pins face their neighbours.

    Signal blocks are never turned. A component whose two connected pins sit on its left
    and right edges is mirrored when its neighbours are the other way round. An electrical
    one is stood up (pins top and bottom) when both neighbours are on the same horizontal
    side, or further apart vertically than horizontally.
    """
    for name, (cx, cy, rot, mirror) in list(local.items()):
        ports = net.ports[name]
        if name in skip or rot or mirror or len(ports) not in (1, 2):
            continue
        pp = {p: net.pin(name, p) for p in ports}
        if any(v[2] in ("i", "o") for v in pp.values()):
            continue
        electrical = all(v[2] == "e" for v in pp.values())
        sides = [pins.side(v[0], v[1]) for v in pp.values()]
        if sorted(sides) != ["L", "R"][:len(ports)] and sides not in (["L"], ["R"]):
            continue
        where = {}
        for a, pa, b, pb in net.edges:
            for me, mp, other in ((a, pa, b), (b, pb, a)):
                if me == name and other in local:
                    where.setdefault(mp, []).append(local[other][:2])
        if len(where) == 1:
            (port, pts), = where.items()
            x = sum(p[0] for p in pts) / len(pts)
            if (pp[port][0] < 0 and x > cx) or (pp[port][0] > 0 and x < cx):
                local[name] = (cx, cy, 0, True)
            continue
        if len(where) != 2:
            continue                    # its pins lead only to connectors or references
        port_l = next(p for p in ports if pp[p][0] < 0)
        port_r = next(p for p in ports if pp[p][0] > 0)
        lx, ly = (sum(v) / len(where[port_l]) for v in zip(*where[port_l]))
        rx, ry = (sum(v) / len(where[port_r]) for v in zip(*where[port_r]))
        same_side = (lx < cx and rx < cx) or (lx > cx and rx > cx)
        if electrical and (same_side or abs(ly - ry) > abs(lx - rx)):
            local[name] = (cx, cy, 90 if ly <= ry else 270, False)
        elif lx > rx:
            local[name] = (cx, cy, 0, True)


# ---------------------------------------------------------------------------
# references, rails, class connectors
# ---------------------------------------------------------------------------

def _boxes(local) -> list:
    return [(n, (x - BOX, y - BOX, x + BOX, y + BOX)) for n, (x, y, _, _) in local.items()]


def _park_references(refs, local, net: _Net) -> list:
    """Park each reference with a single connection beside the pin it connects to.

    The reference keeps its upright orientation (or turns 180 degrees) so a ground still
    reads as a ground: the line either runs straight into its pin, or leaves the anchor's
    pin, turns once, and arrives on the side the reference leaves free. Returns the
    references with no such place.
    """
    leftover = []
    for g in sorted(refs):
        ends = [(b, pb, pa) if a == g else (a, pa, pb) for a, pa, b, pb in net.edges
                if g in (a, b) and (b if a == g else a) in local]
        if len(ends) != 1 or len(net.ports[g]) != 1:
            leftover.append(g)
            continue
        anchor, anchor_port, my_port = ends[0]
        spot = _park_spot(g, my_port, anchor, net.pin(anchor, anchor_port), local, net)
        if spot is None:
            leftover.append(g)
        else:
            local[g] = spot
    return leftover


def _park_spot(g, port, anchor, anchor_pin, local, net: _Net):
    p, d = pin_point(local[anchor], anchor_pin)
    if d is None:
        d = (0, -1)
    q = net.pin(g, port)
    free = references.free_side(net.types[g]) or pins.side(q[0], q[1]) or "T"
    fdir = {"L": (-1, 0), "R": (1, 0), "T": (0, 1), "B": (0, -1)}[free]
    boxes = _boxes(local)
    for rot in (0, 180):
        fd = (fdir[0], fdir[1]) if rot == 0 else (-fdir[0], -fdir[1])
        if fd == d:
            continue
        if fd == (-d[0], -d[1]):
            targets = [(p[0] + d[0] * PARK, p[1] + d[1] * PARK)]
        else:
            targets = [(p[0] + d[0] * k - fd[0] * PARK, p[1] + d[1] * k - fd[1] * PARK)
                       for k in (PARK // 2, PARK, 0)]
        for t in targets:
            qx, qy = transform(q[0], q[1], rot, False)
            ox, oy = _round(t[0] - qx * BOX / 100.0), _round(t[1] - qy * BOX / 100.0)
            me = (ox - BOX, oy - BOX, ox + BOX, oy + BOX)
            if any(me[0] < b[2] + 4 and me[2] > b[0] - 4 and me[1] < b[3] + 4 and me[3] > b[1] - 4
                   for _, b in boxes):
                continue
            path = route(p, d, pin_point((ox, oy, rot, False), q)[0], fd, boxes,
                         own=(anchor, None))
            if path_cost(path, d, fd, boxes, (anchor, None)) < 500:
                return ox, oy, rot, False
    return None


def _rail(names, placements, net: _Net, below: bool):
    """Line references or supplies up under (or over) the components they connect to."""
    if not names:
        return
    if placements:
        ys = [y for _, y, _, _ in placements.values()]
        y = _round(min(ys) - DY - LABEL) if below else _round(max(ys) + DY + LABEL)
    else:
        y = 0
    desired = {}
    for g in names:
        xs = [placements[o][0] for o in net.neighbours(g, placements)]
        desired[g] = sum(xs) / len(xs) if xs else 0
    for g, x in _pack(list(names), desired, DX).items():
        placements[g] = (_round(x), y, 0, False)


def _place_connectors(cls: ClassSpan, placements, net: _Net):
    """Class connectors on the diagram border, level with the pin each one connects to."""
    if not cls.connectors:
        return {}, {}
    sides = icon_mod.assign_connector_edges(cls.connectors, "block")
    (x1, y1), (x2, y2) = _bbox(placements) if placements else ((0, 0), (0, 0))
    x_left, x_right = x1 - DX, x2 + DX
    y_top, y_bottom = y2 + DY, y1 - DY
    points, dirs = {}, {}
    groups = {}
    for c in cls.connectors:
        px, py = sides[c.name]
        edge = pins.side(px, py) or "L"
        linked = []
        for cn in cls.connects:
            for me, other, op in ((cn.from_inst, cn.to_inst, cn.to_port),
                                  (cn.to_inst, cn.from_inst, cn.from_port)):
                if me == c.name and other in placements and op:
                    linked.append(pin_point(placements[other], net.pin(other, op))[0])
        groups.setdefault(edge, []).append((c.name, px, py, linked))
    for edge, members in groups.items():
        horizontal = edge in ("L", "R")
        desired = {}
        for name, px, py, linked in members:
            if linked:
                desired[name] = linked[0][1] if horizontal else linked[0][0]
            elif horizontal:
                desired[name] = (y1 + y2) / 2.0 + py / 100.0 * (y2 - y1) / 2.0
            else:
                desired[name] = (x1 + x2) / 2.0 + px / 100.0 * (x2 - x1) / 2.0
        for name, v in _pack([m[0] for m in members], desired, 2 * BOX + 10).items():
            if horizontal:
                points[name] = (x_left if edge == "L" else x_right, _round(v))
                dirs[name] = (1, 0) if edge == "L" else (-1, 0)
            else:
                points[name] = (_round(v), y_top if edge == "T" else y_bottom)
                dirs[name] = (0, -1) if edge == "T" else (0, 1)
    return points, dirs


def _bbox(placements) -> tuple:
    xs = [p[0] for p in placements.values()] or [0]
    ys = [p[1] for p in placements.values()] or [0]
    return (min(xs) - BOX, min(ys) - BOX), (max(xs) + BOX, max(ys) + BOX)


def _center(placements, connectors, channels):
    pts = [p[:2] for p in placements.values()] + list(connectors.values())
    if not pts:
        return
    cx = _round((min(x for x, _ in pts) + max(x for x, _ in pts)) / 2.0)
    cy = _round((min(y for _, y in pts) + max(y for _, y in pts)) / 2.0)
    for n, (x, y, r, m) in placements.items():
        placements[n] = (x - cx, y - cy, r, m)
    for n, (x, y) in connectors.items():
        connectors[n] = (x - cx, y - cy)
    channels[:] = [c - cy for c in channels]


def _extent(placements, connectors) -> tuple:
    xs = [p[0] for p in placements.values()] + [x for x, _ in connectors.values()]
    ys = [p[1] for p in placements.values()] + [y for _, y in connectors.values()]
    if not xs:
        return ((-100, -100), (100, 100))
    pad = BOX + LABEL
    return ((_round(min(min(xs) - pad, -100)), _round(min(min(ys) - pad, -100))),
            (_round(max(max(xs) + pad, 100)), _round(max(max(ys) + pad, 100))))


def instance_placement(ox: int, oy: int, rot: int = 0, mirror: bool = False) -> str:
    if rot % 360 == 180:
        # a half turn is written as a mirrored extent, which keeps the icon's text readable
        extent = "{{-10,10},{10,-10}}" if mirror else "{{10,10},{-10,-10}}"
        rot = 0
    else:
        extent = "{{10,-10},{-10,10}}" if mirror else "{{-10,-10},{10,10}}"
    return ("Placement(transformation(extent=%s, origin={%d,%d}, rotation=%d))"
            % (extent, ox, oy, rot))
