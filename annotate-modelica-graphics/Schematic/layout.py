"""Diagram auto-layout for composite models.

Pure-Python layered layout (no third-party dependency): build a connectivity graph from
the ``connect`` equations, layer the instances left-to-right by graph distance from the
source components (handling feedback loops, which are simply non-tree edges in the
undirected graph), order within layers by a barycenter sweep to reduce crossings, and pin
ground/supply nodes to the bottom/top. Coordinates are grid-snapped.
"""

from __future__ import annotations

from . import icon as icon_mod
from .parser import ClassSpan
from .routing import GRID

DX = 50          # horizontal spacing between layers
DY = 40          # vertical spacing within a layer


def _round(v: float) -> int:
    return int(round(v / GRID)) * GRID


def _is_source(inst) -> bool:
    t = inst.type_name
    return (".Sources." in t) or t.endswith("RealExpression") or ("Source" in t.split(".")[-1])


def _is_ground(inst) -> bool:
    return inst.type_name.split(".")[-1] == "Ground" or inst.name.lower() in ("gnd", "ground")


def _is_supply(inst) -> bool:
    t = inst.type_name
    n = inst.name.lower()
    return ("ConstantVoltage" in t and ("sup" in n or "vcc" in n or "vdd" in n or "batt" in n
                                        or "rail" in n or n in ("v", "vs"))) or n in ("supply",)


def compute_layout(cls: ClassSpan, type_ports: dict | None = None) -> dict:
    """Compute the diagram layout.

    Returns a dict with:
      'instances'  : {name: (ox, oy, rot)}             component origins
      'connectors' : {name: (ox, oy)}                  class connectors on the border
      'inst_types' : {name: type_name}                 so routing can locate each pin
      'type_ports' : {leaf_type: {conn: (px,py)}}      connector edges of the model's own
                                                        leaf/sub-circuit icons (±100 frame)
      'extent'     : ((x1,y1),(x2,y2))
    """
    instances = cls.instances
    names = [i.name for i in instances]
    inst_by_name = {i.name: i for i in instances}
    name_set = set(names)

    # adjacency among instances (undirected), from connects whose both ends are instances
    adj = {n: set() for n in names}
    for cn in cls.connects:
        a, b = cn.from_inst, cn.to_inst
        if a in name_set and b in name_set and a != b:
            adj[a].add(b)
            adj[b].add(a)

    grounds = [n for n in names if _is_ground(inst_by_name[n])]
    supplies = [n for n in names if _is_supply(inst_by_name[n])]
    rails = set(grounds) | set(supplies)
    core = [n for n in names if n not in rails]

    # BFS layering from sources (fallback: highest-degree node)
    sources = [n for n in core if _is_source(inst_by_name[n])]
    roots = sources or ([max(core, key=lambda n: len(adj[n]))] if core else [])
    layer = {}
    frontier = list(roots)
    for r in roots:
        layer[r] = 0
    while frontier:
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if v in rails:
                    continue
                if v not in layer:
                    layer[v] = layer[u] + 1
                    nxt.append(v)
        frontier = nxt
    # any unreached core nodes -> trailing layer
    if core:
        maxl = max((layer.get(n, 0) for n in core), default=0)
        for n in core:
            layer.setdefault(n, maxl + 1)

    # group by layer, order within layer by barycenter of neighbors (2 sweeps)
    layers = {}
    for n in core:
        layers.setdefault(layer[n], []).append(n)
    layer_keys = sorted(layers)
    pos_in_layer = {}
    for lk in layer_keys:
        for idx, n in enumerate(layers[lk]):
            pos_in_layer[n] = idx
    for _ in range(3):
        for lk in layer_keys:
            def bary(n):
                neigh = [pos_in_layer[v] for v in adj[n] if v in pos_in_layer and layer.get(v) != lk]
                return sum(neigh) / len(neigh) if neigh else pos_in_layer[n]
            layers[lk].sort(key=bary)
            for idx, n in enumerate(layers[lk]):
                pos_in_layer[n] = idx

    # assign coordinates
    nL = len(layer_keys)
    maxrows = max((len(v) for v in layers.values()), default=1)
    placements = {}
    for li, lk in enumerate(layer_keys):
        col = layers[lk]
        m = len(col)
        x = _round((li - (nL - 1) / 2.0) * DX) if nL > 1 else 0
        for j, n in enumerate(col):
            y = _round(((m - 1) / 2.0 - j) * DY)
            placements[n] = (x, y, 0)

    # rails: ground along the bottom, supply along the top
    span = max(_round((nL - 1) * DX / 2.0), 40)
    _place_rail(grounds, placements, y=_round(-(maxrows / 2.0) * DY - DY), span=span, inst_by_name=inst_by_name)
    _place_rail(supplies, placements, y=_round((maxrows / 2.0) * DY + DY), span=span, inst_by_name=inst_by_name)

    # class connectors (for sub-circuit building blocks) placed on the diagram border
    conn_points = {}
    if cls.connectors:
        pts = icon_mod.assign_connector_edges(cls.connectors, "block")
        # scale icon-boundary points (±100) out to the diagram border
        bx = span + DX
        by = _round((maxrows / 2.0) * DY + DY)
        for nm, (px, py) in pts.items():
            cx = _round(px / 100.0 * bx)
            cy = _round(py / 100.0 * by)
            conn_points[nm] = (cx, cy)

    # rotate two-terminal components so their pins face their neighbours: when both
    # connections would otherwise leave the same (left/right) side, stand the component
    # up (pins top/bottom) so the two lines fan out instead of one wrapping around it.
    skip_rot = set(grounds) | set(supplies) | set(sources)
    _orient_two_ports(cls, placements, conn_points, type_ports, skip_rot)

    extent = _bounding_extent(placements, conn_points)
    return {
        "instances": placements,
        "connectors": conn_points,
        "inst_types": {i.name: i.type_name for i in instances},
        "type_ports": type_ports or {},
        "extent": extent,
    }


def _pos(name, placements, conn_points):
    """Diagram position of an instance origin or a class connector, or None."""
    if name in placements:
        return placements[name][0], placements[name][1]
    if name in conn_points:
        return conn_points[name]
    return None


def _port_edge(type_name, port, type_ports):
    """Icon edge ('L'/'R'/'T'/'B') a connector sits on, at rotation 0."""
    from . import routing  # local import: routing has no layout dependency
    edges = type_ports.get(type_name.split(".")[-1]) if type_ports else None
    if edges and port in edges:
        px, py = edges[port]
    else:
        px, py = routing._EDGE_PT[routing._lib_edge(type_name, port)]
    if px < 0:
        return "L"
    if px > 0:
        return "R"
    return "T" if py > 0 else "B"


def _orient_two_ports(cls, placements, conn_points, type_ports, skip):
    """Rotate horizontal (left/right-pin) two-terminal components to reduce wrap-around.

    A component is reoriented only if it has exactly two connected ports sitting on opposite
    left/right edges (resistors, capacitors, inductors, …). The component stands up (pins
    top/bottom) when both neighbours are on the same horizontal side or are separated more
    vertically than horizontally; otherwise it stays horizontal. In each case the pin whose
    own neighbour is nearer a given side is placed toward that side, so neither line crosses.
    """
    inst_type = {i.name: i.type_name for i in cls.instances}
    ports = {}                       # inst -> {port: [neighbour positions]}
    for cn in cls.connects:
        for me, mp, other in ((cn.from_inst, cn.from_port, cn.to_inst),
                              (cn.to_inst, cn.to_port, cn.from_inst)):
            if me in inst_type and other != me:
                p = _pos(other, placements, conn_points)
                if p:
                    ports.setdefault(me, {}).setdefault(mp, []).append(p)

    for name, port_neigh in ports.items():
        if name in skip or name not in placements or len(port_neigh) != 2:
            continue
        edges = {p: _port_edge(inst_type[name], p, type_ports) for p in port_neigh}
        if set(edges.values()) != {"L", "R"}:
            continue
        port_l = next(p for p, e in edges.items() if e == "L")
        port_r = next(p for p, e in edges.items() if e == "R")

        def _avg(pts):
            return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

        lx, ly = _avg(port_neigh[port_l])
        rx, ry = _avg(port_neigh[port_r])
        cx, cy, _ = placements[name]
        same_side = (lx < cx and rx < cx) or (lx > cx and rx > cx)
        if same_side or abs(ly - ry) > abs(lx - rx):
            rot = 90 if ly <= ry else 270      # vertical: left-pin toward the lower neighbour
        else:
            rot = 0 if lx <= rx else 180        # horizontal: left-pin toward the left neighbour
        placements[name] = (cx, cy, rot)


def _place_rail(rail_names, placements, y, span, inst_by_name):
    m = len(rail_names)
    if m == 0:
        return
    for j, n in enumerate(sorted(rail_names)):
        x = _round((-span + 2 * span * (j + 1) / (m + 1))) if m > 1 else 0
        placements[n] = (x, y, 0)


def _bounding_extent(placements, conn_points):
    xs, ys = [], []
    for p in placements.values():
        xs.append(p[0]); ys.append(p[1])
    for (x, y) in conn_points.values():
        xs.append(x); ys.append(y)
    if not xs:
        return ((-100, -100), (100, 100))
    pad = 30
    x1 = min(min(xs) - pad, -100)
    y1 = min(min(ys) - pad, -100)
    x2 = max(max(xs) + pad, 100)
    y2 = max(max(ys) + pad, 100)
    return ((_round(x1), _round(y1)), (_round(x2), _round(y2)))


def instance_placement(ox: int, oy: int, rot: int = 0) -> str:
    return ("Placement(transformation(extent={{-10,-10},{10,10}}, origin={%d,%d}, rotation=%d))"
            % (ox, oy, rot))


def connector_diagram_placement(ox: int, oy: int) -> str:
    ext = "extent={{%d,%d},{%d,%d}}" % (ox - 10, oy - 10, ox + 10, oy + 10)
    return "Placement(transformation(%s), iconTransformation(%s))" % (ext, ext)
