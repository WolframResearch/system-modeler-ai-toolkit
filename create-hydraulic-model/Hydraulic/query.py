"""Graph query and RAG context generation.

Provides functions to traverse the knowledge graph and produce
structured context suitable for LLM-assisted model creation.
"""

from __future__ import annotations  # `dict | None` annotations on Python < 3.10

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx is required. Run Hydraulic.main (it auto-provisions networkx "
                      "into the managed venv), or `python3 <scripts>/bootstrap_env.py networkx`.")


def _get_node(G, node_id):
    """Safely get node attributes."""
    if G.has_node(node_id):
        return G.nodes[node_id]
    return None


def _edges_of_type(G, node, edge_type, direction="out"):
    """Get edges of a specific type from/to a node."""
    if direction == "out":
        return [(u, v, d) for u, v, d in G.out_edges(node, data=True)
                if d.get("edge_type") == edge_type]
    else:
        return [(u, v, d) for u, v, d in G.in_edges(node, data=True)
                if d.get("edge_type") == edge_type]


def _walk_extends(G, start_node):
    """BFS the local extends chain from start_node outward.

    Yields (current_class, depth) starting with (start_node, 0). Skips
    external_ref nodes since they hold no ports/parameters in our graph.
    """
    visited = set()
    queue = [(start_node, 0)]
    while queue:
        current, depth = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        node = G.nodes.get(current, {})
        if node.get("node_type") == "external_ref":
            continue
        yield current, depth
        for _, parent, _ in _edges_of_type(G, current, "extends"):
            if parent not in visited:
                queue.append((parent, depth + 1))


def _collect_inherited_ports(G, component_name):
    """Collect ports from component_name and all ancestors via extends.

    Deduplicates by port name — the most-derived (lowest depth) wins.
    """
    by_name = {}
    for cls, _ in _walk_extends(G, component_name):
        for _, port_node, _ in _edges_of_type(G, cls, "has_port"):
            port_attrs = G.nodes[port_node]
            name = port_attrs.get("name", "")
            if name in by_name:
                continue
            port_type_edges = _edges_of_type(G, port_node, "port_type_is")
            port_type = port_type_edges[0][1] if port_type_edges else ""
            by_name[name] = {
                "name": name,
                "type": port_type,
                "from": cls,
            }
    return list(by_name.values())


def _collect_inherited_parameters(G, component_name):
    """Collect parameters from component_name and all ancestors via extends."""
    by_name = {}
    for cls, _ in _walk_extends(G, component_name):
        for _, param_node, _ in _edges_of_type(G, cls, "has_parameter"):
            pa = G.nodes[param_node]
            name = pa.get("name", "")
            if name in by_name:
                continue
            by_name[name] = {
                "name": name,
                "type": pa.get("param_type", ""),
                "default": pa.get("default", ""),
                "description": pa.get("description", ""),
                "from": cls,
            }
    return list(by_name.values())


def search_entities(G, keyword: str) -> list:
    """Search for entities by keyword in name or description.

    Returns list of dicts with node_id, name, node_type, description.
    """
    if not keyword or not keyword.strip():
        return []  # an empty/whitespace query must match nothing, not everything
    keyword_lower = keyword.strip().lower()
    results = []
    for node_id, attrs in G.nodes(data=True):
        nt = attrs.get("node_type", "")
        if nt in ("port_instance", "parameter_def"):
            continue  # Skip internal nodes
        name = attrs.get("name", "")
        desc = attrs.get("description", "")
        score = 0
        if keyword_lower == name.lower():
            score = 100
        elif keyword_lower in name.lower():
            score = 50
        elif keyword_lower in desc.lower():
            score = 20
        elif keyword_lower in node_id.lower():
            score = 10
        if score > 0:
            results.append({
                "node_id": node_id,
                "name": name,
                "node_type": nt,
                "description": desc,
                "score": score,
            })
    results.sort(key=lambda x: (-x["score"], _node_type_rank(x["node_type"]), x["node_id"]))
    return results


# Lower rank wins on ties. Components/blocks/connectors are the things an LLM
# would actually instantiate; classes/packages/types are scaffolding.
_NODE_TYPE_RANK = {
    "component": 0,
    "block": 0,
    "connector": 0,
    "function": 1,
    "record": 1,
    "class": 2,
    "type": 3,
    "package": 4,
    "external_ref": 5,
}


def _node_type_rank(nt: str) -> int:
    return _NODE_TYPE_RANK.get(nt, 6)


def _resolve_exact(G, name: str):
    """Resolve a user-supplied name to a node id via a direct node id or an exact
    (score==100) name match only. Returns None for a partial/substring hit, so a
    typo/partial name is reported as "not found" instead of silently resolving to
    an unrelated entity (e.g. "por" -> FourPort)."""
    if name and G.has_node(name):
        return name
    exact = [m for m in search_entities(G, name) if m["score"] == 100]
    return exact[0]["node_id"] if exact else None


def get_component_details(G, component_name: str) -> dict | None:
    """Get full details for a component: ports, parameters, parents, examples."""
    # Try to find the node
    node = _get_node(G, component_name)
    if not node:
        # resolve only on an exact match — never a partial/substring guess
        resolved = _resolve_exact(G, component_name)
        if resolved:
            component_name = resolved
            node = _get_node(G, component_name)
    if not node:
        return None

    ports = _collect_inherited_ports(G, component_name)
    params = _collect_inherited_parameters(G, component_name)

    # Extends (parents)
    parents = []
    for _, parent, d in _edges_of_type(G, component_name, "extends"):
        parents.append(parent)

    # What extends this (children)
    children = []
    for child, _, d in _edges_of_type(G, component_name, "extends", direction="in"):
        children.append(child)

    # Sub-components
    sub_components = []
    for _, target, d in _edges_of_type(G, component_name, "instantiates"):
        sub_components.append({
            "instance_name": d.get("instance_name", ""),
            "type": target,
        })

    # Examples that instantiate this component
    examples = []
    for source, _, d in _edges_of_type(G, component_name, "instantiates", direction="in"):
        src = _get_node(G, source)
        if src and "Example" in source:
            examples.append(source)

    return {
        "qualified_name": component_name,
        "name": node.get("name", ""),
        "description": node.get("description", ""),
        "entity_type": node.get("entity_type", ""),
        "is_partial": node.get("is_partial", False),
        "ports": ports,
        "parameters": params,
        "parents": parents,
        "children": children,
        "sub_components": sub_components,
        "used_in_examples": examples,
    }


def find_components_by_interface(G, interface_name: str) -> list:
    """Find all components that extend a given interface (transitively)."""
    # Resolve name on an exact match only; a partial name returns nothing rather
    # than the descendants of an unrelated node.
    resolved = _resolve_exact(G, interface_name)
    if resolved is None:
        return []
    interface_name = resolved

    # BFS to find all descendants via extends edges (incoming)
    descendants = set()
    queue = [interface_name]
    while queue:
        current = queue.pop(0)
        for child, _, d in _edges_of_type(G, current, "extends", direction="in"):
            if child not in descendants:
                descendants.add(child)
                queue.append(child)

    results = []
    for d in sorted(descendants):
        node = _get_node(G, d)
        if node and node.get("node_type") in ("component", "connector"):
            results.append({
                "qualified_name": d,
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "is_partial": node.get("is_partial", False),
            })
    return results


def find_compatible_connections(G, port_type: str) -> list | None:
    """Find all components that have ports compatible with the given connector type.

    Short names (e.g. ``Port_a``) are resolved to qualified node ids the same way
    the other queries do. Returns None when the name cannot be resolved at all.
    """
    # Resolve short names to a qualified node id on an exact match only
    resolved = _resolve_exact(G, port_type)
    if resolved is None:
        return None
    port_type = resolved

    # Find compatible connector types
    compatible_types = {port_type}
    for _, target, d in _edges_of_type(G, port_type, "compatible_with"):
        compatible_types.add(target)

    # Also include the type itself and any that extend it
    for child, _, d in _edges_of_type(G, port_type, "extends", direction="in"):
        compatible_types.add(child)

    # Find all port instances of compatible types
    results = []
    seen_owners = set()
    for node_id, attrs in G.nodes(data=True):
        if attrs.get("node_type") != "port_instance":
            continue
        # Check port type
        for _, type_node, _ in _edges_of_type(G, node_id, "port_type_is"):
            if type_node in compatible_types:
                owner = attrs.get("owner", "")
                if owner and owner not in seen_owners:
                    seen_owners.add(owner)
                    owner_node = _get_node(G, owner)
                    if owner_node:
                        # Get all ports of this owner
                        owner_ports = []
                        for _, pn, _ in _edges_of_type(G, owner, "has_port"):
                            pa = G.nodes[pn]
                            pt_edges = _edges_of_type(G, pn, "port_type_is")
                            pt = pt_edges[0][1] if pt_edges else ""
                            owner_ports.append({"name": pa.get("name", ""), "type": pt})
                        results.append({
                            "qualified_name": owner,
                            "name": owner_node.get("name", ""),
                            "description": owner_node.get("description", ""),
                            "ports": owner_ports,
                        })
    return results


def find_example_circuits(G, component_names: list = None) -> list:
    """Find example models, optionally filtered to those using specific components."""
    examples = []
    for node_id, attrs in G.nodes(data=True):
        if ".Examples." not in node_id:
            continue
        if attrs.get("node_type") != "component":
            continue

        # Get instantiated components
        instantiated = []
        for _, target, d in _edges_of_type(G, node_id, "instantiates"):
            instantiated.append({
                "instance_name": d.get("instance_name", ""),
                "type": target,
            })

        # Get connections
        connections = []
        for u, v, d in G.edges(data=True):
            if d.get("edge_type") == "connects_to" and d.get("example") == node_id:
                connections.append({"from": u, "to": v})

        if component_names:
            inst_types = {i["type"] for i in instantiated}
            if not any(cn in inst_types or any(cn in t for t in inst_types) for cn in component_names):
                continue

        examples.append({
            "qualified_name": node_id,
            "name": attrs.get("name", ""),
            "description": attrs.get("description", ""),
            "components": instantiated,
            "connections": connections,
        })
    return examples


def get_connection_patterns(G, from_type: str, to_type: str) -> list:
    """Find examples where two component types are connected, showing which ports."""
    patterns = []
    # Find all connects_to edges
    for u, v, d in G.edges(data=True):
        if d.get("edge_type") != "connects_to":
            continue
        u_attrs = _get_node(G, u)
        v_attrs = _get_node(G, v)
        if not u_attrs or not v_attrs:
            continue

        u_owner = u_attrs.get("owner", "")
        v_owner = v_attrs.get("owner", "")

        match_fwd = (from_type in u_owner and to_type in v_owner)
        match_rev = (from_type in v_owner and to_type in u_owner)

        if match_fwd or match_rev:
            patterns.append({
                "from_port": u,
                "to_port": v,
                "from_component": u_owner,
                "to_component": v_owner,
                "example": d.get("example", ""),
            })
    return patterns


def format_rag_context(G, query: str, max_results: int = 20) -> str:
    """Generate structured RAG context for an LLM based on a natural language query.

    Tries multiple query strategies and assembles a markdown context string.
    """
    sections = []
    query_lower = query.lower()

    # Strategy 1: Direct entity search
    matches = search_entities(G, query)
    if matches:
        top = matches[:max_results]
        section = "## Matching Entities\n\n"
        for m in top:
            section += f"- **{m['name']}** (`{m['node_id']}`) — {m['node_type']}"
            if m["description"]:
                section += f": {m['description']}"
            section += "\n"
        sections.append(section)

        # Get details for top match
        details = get_component_details(G, top[0]["node_id"])
        if details:
            sections.append(_format_component_details(details))

    # Strategy 2: Check for interface queries
    interface_keywords = ["twoport", "fourport", "threeport", "oneport", "chamber"]
    for kw in interface_keywords:
        if kw in query_lower:
            descendants = find_components_by_interface(G, kw)
            if descendants:
                section = f"## Components extending {kw}\n\n"
                for d in descendants[:max_results]:
                    partial_tag = " (partial)" if d["is_partial"] else ""
                    section += f"- **{d['name']}**{partial_tag}: {d['description']}\n"
                sections.append(section)
                break

    # Strategy 3: Check for connection/circuit queries
    circuit_words = ["connect", "circuit", "example", "pattern", "wire", "hook up"]
    if any(w in query_lower for w in circuit_words):
        examples = find_example_circuits(G)
        if examples:
            section = "## Example Circuits\n\n"
            for ex in examples[:10]:
                section += f"### {ex['name']} (`{ex['qualified_name']}`)\n"
                if ex["description"]:
                    section += f"{ex['description']}\n"
                section += "\n**Components:**\n"
                for c in ex["components"]:
                    section += f"- `{c['instance_name']}`: {c['type']}\n"
                if ex["connections"]:
                    section += "\n**Connections:**\n"
                    for conn in ex["connections"]:
                        section += f"- `{conn['from']}` -> `{conn['to']}`\n"
                section += "\n"
            sections.append(section)

    if not sections:
        return f"No results found for query: {query}"

    return "\n".join(sections)


def _format_component_details(details: dict) -> str:
    """Format component details as markdown."""
    lines = [f"## Component: {details['name']}"]
    lines.append(f"**Qualified name:** `{details['qualified_name']}`")
    if details["description"]:
        lines.append(f"**Description:** {details['description']}")
    lines.append(f"**Type:** {details['entity_type']}")
    lines.append("")

    if details["parents"]:
        lines.append("### Extends")
        for p in details["parents"]:
            lines.append(f"- `{p}`")
        lines.append("")

    own = details["qualified_name"]

    if details["ports"]:
        lines.append("### Ports (effective interface — direct + inherited)")
        for p in details["ports"]:
            origin = p.get("from", own)
            origin_tag = "" if origin == own else f"  _(from `{origin}`)_"
            lines.append(f"- `{p['name']}` -> `{p['type']}`{origin_tag}")
        lines.append("")

    if details["parameters"]:
        lines.append("### Parameters (effective — direct + inherited)")
        for p in details["parameters"]:
            default_str = f" = {p['default']}" if p['default'] else ""
            origin = p.get("from", own)
            origin_tag = "" if origin == own else f"  _(from `{origin}`)_"
            lines.append(f"- `{p['name']}` ({p['type']}{default_str}): {p['description']}{origin_tag}")
        lines.append("")

    if details["sub_components"]:
        lines.append("### Sub-components")
        for c in details["sub_components"]:
            lines.append(f"- `{c['instance_name']}`: {c['type']}")
        lines.append("")

    if details["children"]:
        lines.append("### Extended by")
        for c in details["children"]:
            lines.append(f"- `{c}`")
        lines.append("")

    if details["used_in_examples"]:
        lines.append("### Used in examples")
        for ex in details["used_in_examples"]:
            lines.append(f"- `{ex}`")
        lines.append("")

    return "\n".join(lines)
