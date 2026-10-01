"""Orthogonal (Manhattan) routing of connection lines between connector pins.

Each line starts and ends exactly on a pin — the instance origin plus the connector's
icon offset, mirrored and rotated with the instance — and leaves the pin in the direction
the pin faces, away from its component. Between the two pins a handful of candidate
paths (straight, L, Z, and detours around the placed components) are scored on bends,
length and crossings of component bodies, and the cheapest is drawn.
"""

from __future__ import annotations

from . import colors
from . import pins
from .parser import ClassSpan, Connect

GRID = 2
BOX = 10     # half-extent of an instance Placement box (extent={{-10,-10},{10,10}})
STUB = 4     # shortest straight run out of a pin before a line may turn
CLEAR = 8    # distance a detour keeps from the components it passes
LABEL = 16   # reach of the name above an icon and the parameter text below it
GAP = 6      # closest two lines of different nets may run side by side or end on each other
BODY = 5000  # cost of crossing a component, above any detour
DETOUR = 40  # how far beyond its two pins a line looks for a gap to pass through

_DIRS = {"L": (-1, 0), "R": (1, 0), "T": (0, 1), "B": (0, -1)}


def _round(v: float) -> int:
    return int(round(v / GRID)) * GRID


def transform(px: float, py: float, rot: int, mirror: bool) -> tuple:
    """Map an icon-frame point through a Placement: mirror first, then rotate."""
    if mirror:
        px = -px
    rot %= 360
    if rot == 90:
        return -py, px
    if rot == 180:
        return -px, -py
    if rot == 270:
        return py, -px
    return px, py


def pin_point(placement: tuple, pin: tuple) -> tuple:
    """Diagram point and outward direction of ``pin`` on an instance at ``placement``."""
    ox, oy, rot, mirror = placement
    px, py = transform(pin[0], pin[1], rot, mirror)
    point = (int(round(ox + px * BOX / 100.0)), int(round(oy + py * BOX / 100.0)))
    edge = pins.side(px, py)
    return point, (_DIRS[edge] if edge else None)


def _anchor(inst: str, port: str, layout: dict):
    """``(point, outward direction)`` of one connect endpoint, or ``(None, None)``."""
    connectors = layout.get("connectors", {})
    instances = layout.get("instances", {})
    if inst in instances and port:
        ttype = layout.get("inst_types", {}).get(inst, "")
        return pin_point(instances[inst], pins.resolve(ttype, port, layout.get("type_ports")))
    if inst in connectors:
        x, y = connectors[inst]
        return (x, y), layout.get("connector_dirs", {}).get(inst)
    return None, None


def _crosses(p, q, box) -> bool:
    """True if segment p-q passes through the interior of ``box``."""
    x1, y1, x2, y2 = box
    (ax, ay), (bx, by) = p, q
    if ay == by:
        return y1 < ay < y2 and min(ax, bx) < x2 and max(ax, bx) > x1
    return x1 < ax < x2 and min(ay, by) < y2 and max(ay, by) > y1


def _simplify(pts: list) -> list:
    out = []
    for p in pts:
        if out and p == out[-1]:
            continue
        if len(out) >= 2 and (out[-2][0] == out[-1][0] == p[0] or out[-2][1] == out[-1][1] == p[1]):
            out[-1] = p
            continue
        out.append(p)
    return out


def _heading(p, q) -> tuple:
    return ((q[0] > p[0]) - (q[0] < p[0]), (q[1] > p[1]) - (q[1] < p[1]))


def _meets(p, q, r, t) -> str | None:
    """How two orthogonal segments of different nets meet: 'overlap' if they share a
    stretch or one continues the other, 'touch' if they run or end close enough to read
    as joined, 'cross' if they cross."""
    if (p[1] == q[1]) == (r[1] == t[1]):                   # parallel
        axis = 1 if p[1] == q[1] else 0
        if abs(p[axis] - r[axis]) >= GAP:
            return None
        o = 1 - axis
        lo = max(min(p[o], q[o]), min(r[o], t[o]))
        hi = min(max(p[o], q[o]), max(r[o], t[o]))
        if p[axis] == r[axis]:
            return "overlap" if hi > lo - GAP else None
        return "touch" if hi > lo else None
    h, v = ((p, q), (r, t)) if p[1] == q[1] else ((r, t), (p, q))
    x, y = v[0][0], h[0][1]
    hx = min(h[0][0], h[1][0]), max(h[0][0], h[1][0])
    vy = min(v[0][1], v[1][1]), max(v[0][1], v[1][1])
    if hx[0] < x < hx[1] and vy[0] < y < vy[1]:
        return "cross"
    if hx[0] - GAP < x < hx[1] + GAP and vy[0] - GAP < y < vy[1] + GAP:
        return "touch"
    return None


def _over_label(p, q, labels) -> int:
    """Number of icon labels a horizontal segment runs through."""
    if p[1] != q[1]:
        return 0
    lo, hi = min(p[0], q[0]), max(p[0], q[0])
    return sum(1 for x1, y1, x2, y2 in labels
               if lo < x2 and hi > x1 and (y2 < p[1] < y2 + LABEL - BOX or y1 - LABEL + BOX < p[1] < y1))


def path_cost(pts: list, da, db, boxes, own=(None, None), channels=(), wires=(),
              bound=float("inf")) -> float:
    """Length plus penalties for bends, a pin left the wrong way, bodies and labels
    crossed, and lines of other nets crossed, touched or run along; less a bonus for each
    horizontal run along one of the layout's ``channels``. ``wires`` holds the segments
    already drawn for other nets. Infinite once the cost can no longer stay below ``bound``.

    ``boxes`` is ``[(name, box)]``; the first and last segments may run inside the box of
    their own component, since some pins sit inside the icon's frame, and across its labels.
    """
    if len(pts) < 2:
        return 0.0
    cost = 0.0
    if da and _heading(pts[0], pts[1]) != da:
        cost += 500
    if db and _heading(pts[-1], pts[-2]) != db:
        cost += 500
    last = len(pts) - 2
    for i, (p, q) in enumerate(zip(pts, pts[1:])):
        if p[0] != q[0] and p[1] != q[1]:
            return float("inf")
        cost += abs(p[0] - q[0]) + abs(p[1] - q[1])
        skip = {own[0] if i == 0 else None, own[1] if i == last else None}
        cost += BODY * sum(_crosses(p, q, b) for n, b in boxes if n not in skip)
        cost += 150 * _over_label(p, q, [b for n, b in boxes if n not in skip])
        if p[1] == q[1] and p[0] != q[0] and p[1] in channels:
            cost -= 20
        x1, x2 = min(p[0], q[0]) - GAP, max(p[0], q[0]) + GAP
        y1, y2 = min(p[1], q[1]) - GAP, max(p[1], q[1]) + GAP
        for r, t in wires:
            if (max(r[0], t[0]) > x1 and min(r[0], t[0]) < x2
                    and max(r[1], t[1]) > y1 and min(r[1], t[1]) < y2):
                cost += _PENALTY.get(_meets(p, q, r, t), 0)
        if cost - 20 * (last - i) >= bound:
            return float("inf")
    return cost + 25 * (len(pts) - 2)


_PENALTY = {"cross": 60, "touch": 300, "overlap": 1000}


def _detours(a, b, boxes, channels) -> tuple:
    """Vertical and horizontal channel coordinates that pass beside the boxes between a and
    b: around all of them, and along the gaps beside each one, clear of its labels."""
    boxes = [bx for _, bx in boxes]
    lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
    lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
    in_x = [bx for bx in boxes if bx[0] < hi_x + CLEAR and bx[2] > lo_x - CLEAR]
    in_y = [bx for bx in boxes if bx[1] < hi_y + CLEAR and bx[3] > lo_y - CLEAR]
    pad = LABEL - BOX + 2
    ys = {_round(min([bx[1] - pad for bx in in_x] + [lo_y]) - CLEAR),
          _round(max([bx[3] + pad for bx in in_x] + [hi_y]) + CLEAR)}
    xs = {_round(min([bx[0] for bx in in_y] + [lo_x]) - CLEAR),
          _round(max([bx[2] for bx in in_y] + [hi_x]) + CLEAR)}
    ys |= {_round(y) for bx in in_x if lo_y - DETOUR < bx[1] and bx[3] < hi_y + DETOUR
           for y in (bx[1] - pad - 2, bx[3] + pad + 2)}
    xs |= {_round(x) for bx in in_y if lo_x - DETOUR < bx[0] and bx[2] < hi_x + DETOUR
           for x in (bx[0] - CLEAR, bx[2] + CLEAR)}
    return xs, ys | set(channels)


def route(a: tuple, da, b: tuple, db, boxes=(), channels=(), own=(None, None),
          wires=()) -> list:
    """Cheapest orthogonal polyline from pin ``a`` (facing ``da``) to pin ``b`` (facing ``db``).

    ``boxes`` is ``[(name, box)]`` of the placed components; ``own`` names the components
    the two pins belong to.
    """
    if a == b:
        return [a, b]
    a1 = (a[0] + STUB * da[0], a[1] + STUB * da[1]) if da else a
    b1 = (b[0] + STUB * db[0], b[1] + STUB * db[1]) if db else b
    chan = {_round(c) for c in channels}
    xs, ys = _detours(a, b, boxes, chan)
    # the midpoints come first, so a tie between equally long paths turns halfway
    xs = [_round((a[0] + b[0]) / 2.0)] + sorted(xs | {a1[0], b1[0]})
    ys = [_round((a[1] + b[1]) / 2.0)] + sorted(ys | {a1[1], b1[1]})
    middles = [[(b1[0], a1[1])], [(a1[0], b1[1])]]
    middles += [[(x, a1[1]), (x, b1[1])] for x in xs]
    middles += [[(a1[0], y), (b1[0], y)] for y in ys]
    # every candidate stays inside this rectangle, so nothing outside it can change a cost
    x_lo, x_hi = min(xs + [a[0], b[0]]), max(xs + [a[0], b[0]])
    y_lo, y_hi = min(ys + [a[1], b[1]]), max(ys + [a[1], b[1]])
    boxes = [(n, bx) for n, bx in boxes
             if bx[0] <= x_hi and bx[2] >= x_lo and bx[1] <= y_hi and bx[3] >= y_lo]
    wires = [(r, t) for r, t in wires
             if min(r[0], t[0]) <= x_hi and max(r[0], t[0]) >= x_lo
             and min(r[1], t[1]) <= y_hi and max(r[1], t[1]) >= y_lo]
    best, best_cost = [a, b], float("inf")

    def search(candidates):
        nonlocal best, best_cost
        for mid in candidates:
            for start in ([a], [a, a1]):
                for end in ([b], [b1, b]):
                    pts = _simplify(start + mid + end)
                    c = path_cost(pts, da, db, boxes, own, chan, wires, best_cost)
                    if c < best_cost:
                        best, best_cost = pts, c

    search(middles)
    # only a line that found no clean path pays for the paths turning four times
    if best_cost > abs(a[0] - b[0]) + abs(a[1] - b[1]) + 200:
        search([[(x, a1[1]), (x, y), (b1[0], y)] for x in xs for y in ys]
               + [[(a1[0], y), (x, y), (x, b1[1])] for x in xs for y in ys])
    return best


def _points_str(pts: list) -> str:
    return "{" + ",".join("{%d,%d}" % (x, y) for (x, y) in pts) + "}"


def route_connect(cn: Connect, layout: dict, drawn: list) -> tuple:
    """``(points, cost)`` of one connect's line, or ``(None, 0)`` when an end is not placed.

    ``drawn`` holds ``(net, segment)`` for the lines routed so far and is extended with
    this one, so each line avoids the ones before it.
    """
    a, da = _anchor(cn.from_inst, cn.from_port, layout)
    b, db = _anchor(cn.to_inst, cn.to_port, layout)
    if a is None or b is None:
        return None, 0.0
    if a == b:
        # the two pins coincide (e.g. diode-connected to itself): a small visible loop
        x, y = a
        return [(x, y), (x + 25, y), (x + 25, y + 20), (x, y + 20)], 0.0
    net = layout.get("nets", {}).get((cn.from_inst, cn.from_port))
    wires = [seg for n, seg in drawn if n != net or net is None]
    boxes = list(layout.get("boxes", {}).items())
    channels = layout.get("channels", ())
    own = (cn.from_inst, cn.to_inst)
    pts = route(a, da, b, db, boxes, channels, own, wires)
    drawn += [(net, seg) for seg in zip(pts, pts[1:])]
    return pts, path_cost(pts, da, db, boxes, own, {_round(c) for c in channels}, wires)


def line_for(cn: Connect, cls: ClassSpan, layout: dict) -> str:
    """Return the ``Line(...)`` annotation body for one connect, or a minimal stub."""
    rgb = _color_for(cn, cls, layout)
    pts, _ = route_connect(cn, layout, layout.setdefault("drawn", []))
    if pts is None:
        # endpoint not placed (e.g. an inherited class connector) — emit a harmless stub
        return "Line(points={{0,0},{0,0}}, color=%s)" % colors.fmt(rgb)
    return "Line(points=%s, color=%s, thickness=0.5)" % (_points_str(pts), colors.fmt(rgb))


def _color_for(cn: Connect, cls: ClassSpan, layout: dict) -> tuple:
    # Prefer the declared connector type of a class-level connector endpoint.
    conn_types = {c.name: c.type_name for c in cls.connectors}
    for end in (cn.from_inst, cn.to_inst):
        if end in conn_types:
            return colors.color_for_type(conn_types[end])
    # else from the kind of each pin and the type of the component that owns it
    inst_types = layout.get("inst_types", {})
    for inst, port in ((cn.from_inst, cn.from_port), (cn.to_inst, cn.to_port)):
        owner = inst_types.get(inst, "")
        kind = pins.resolve(owner, port, layout.get("type_ports"))[2] if owner and port else ""
        rgb = colors.color_for_pin(kind, port or "", owner)
        if rgb is not None:
            return rgb
    return colors.DEFAULT
