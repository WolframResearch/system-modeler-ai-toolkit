"""CLI: query the prebuilt Hydraulic Modelica knowledge graph.

By default this loads the prebuilt graph from ``data/graph.json`` and answers
queries — **no Modelica library and no re-parsing required**. This is what the
``create-hydraulic-model`` skill calls at query time, and it works regardless of
where the skill is installed.

    python -m Hydraulic.main --query "Pump"             # keyword search
    python -m Hydraulic.main --details "CylinderDouble"  # full effective interface
    python -m Hydraulic.main --interface "FourPort"      # components by interface
    python -m Hydraulic.main --examples                  # list example circuits
    python -m Hydraulic.main --rag "pressure control"    # RAG context for an LLM
    python -m Hydraulic.main --interactive               # interactive REPL
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Output (search results, em dashes, arrows) may contain non-ASCII; force UTF-8
# so it doesn't crash on a legacy Windows console that defaults to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def _ensure_deps():
    """Self-provision networkx into the shared managed venv (never system Python).

    Locates the sibling ``scripts/`` the same way the skills' ``parser.py`` shims do, then
    re-execs ``python -m Hydraulic.main`` under the managed venv if networkx is missing. If
    ``scripts/`` can't be found, fall through to the ImportError below.
    """
    here = os.path.abspath(__file__)
    skill_dir = os.path.dirname(os.path.dirname(here))  # .../create-hydraulic-model
    cands = [os.environ.get("WSM_SKILLS_SCRIPTS")]
    for base in (here, os.path.realpath(here)):
        cands.append(os.path.join(os.path.dirname(os.path.dirname(base)), "..", "scripts"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "_env.py")):
            sys.path.insert(0, os.path.abspath(c))
            import _env
            _env.reexec_module_under_managed_venv(
                "Hydraulic.main", ["networkx"], package_root=skill_dir)
            return


_ensure_deps()

try:
    import networkx as nx
except ImportError:
    raise ImportError(
        "networkx is required. It auto-installs into the managed venv when scripts/ is "
        "alongside this skill; otherwise provision it with "
        "`python3 <scripts>/bootstrap_env.py networkx`.")

from .query import (
    search_entities, get_component_details, find_components_by_interface,
    find_compatible_connections, find_example_circuits, get_connection_patterns,
    format_rag_context, _format_component_details,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
GRAPH_PATH = DATA_DIR / "graph.json"


def load_graph() -> "nx.DiGraph":
    """Load the prebuilt knowledge graph from data/graph.json.

    No Modelica library or re-parsing required — this is the normal query path.
    """
    if not GRAPH_PATH.exists() or GRAPH_PATH.stat().st_size == 0:
        sys.exit(
            f"Error: prebuilt graph not found (or empty) at {GRAPH_PATH}.\n"
            f"Reinstall the skill to restore the bundled graph."
        )
    try:
        with open(GRAPH_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        sys.exit(
            f"Error: prebuilt graph at {GRAPH_PATH} is corrupt (invalid JSON).\n"
            f"Reinstall the skill to restore the bundled graph."
        )
    if not isinstance(data, dict) or not data.get("nodes"):
        sys.exit(
            f"Error: prebuilt graph at {GRAPH_PATH} is empty or malformed.\n"
            f"Reinstall the skill to restore the bundled graph."
        )
    # node-link format: the shipped graph.json keys its edge list as "edges" (networkx
    # >=3.4 convention); older files/networkx use "links". Normalize to "links" so either
    # spelling loads on any networkx version.
    if "edges" in data and "links" not in data:
        data["links"] = data.pop("edges")
    try:
        try:
            G = nx.node_link_graph(data, edges="links")
        except TypeError:  # networkx < 3.4: no edges= kwarg; reads "links" by default
            G = nx.node_link_graph(data)
    except Exception as exc:  # malformed node-link data (missing "id" keys, wrong types, ...)
        sys.exit(
            f"Error: prebuilt graph at {GRAPH_PATH} is malformed ({exc}).\n"
            f"Reinstall the skill to restore the bundled graph."
        )
    if not all(isinstance(n, str) for n in G.nodes):
        sys.exit(
            f"Error: prebuilt graph at {GRAPH_PATH} is malformed (non-string node ids).\n"
            f"Reinstall the skill to restore the bundled graph."
        )
    return G


def interactive_loop(G):
    """Interactive query loop."""
    print("\n=== Interactive Query Mode ===")
    print("Commands:")
    print("  search <keyword>       — Search entities by name/description")
    print("  details <name>         — Show component details")
    print("  interface <name>       — Find components extending an interface")
    print("  compatible <port_type> — Find compatible connections")
    print("  examples [comp1 comp2] — List example circuits")
    print("  patterns <from> <to>   — Find connection patterns between types")
    print("  rag <query>            — Generate RAG context")
    print("  quit                   — Exit")
    print()

    while True:
        try:
            line = input("query> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "quit" or cmd == "exit":
            break
        elif cmd == "search":
            results = search_entities(G, arg)
            for r in results[:20]:
                print(f"  [{r['node_type']:12s}] {r['name']:30s} — {r['description'][:60]}")
        elif cmd == "details":
            d = get_component_details(G, arg)
            if d:
                print(_format_component_details(d))
            else:
                print(f"  Not found: {arg}")
        elif cmd == "interface":
            results = find_components_by_interface(G, arg)
            for r in results:
                tag = " (partial)" if r["is_partial"] else ""
                print(f"  {r['qualified_name']}{tag}: {r['description'][:60]}")
        elif cmd == "compatible":
            results = find_compatible_connections(G, arg)
            if results is None:
                print(f"  Not found: {arg}")
                continue
            for r in results[:20]:
                ports_str = ", ".join(f"{p['name']}:{p['type'].split('.')[-1]}" for p in r["ports"])
                print(f"  {r['name']:30s} ports: {ports_str}")
        elif cmd == "examples":
            comp_names = arg.split() if arg else None
            results = find_example_circuits(G, comp_names)
            for ex in results:
                print(f"  {ex['name']}: {ex['description'][:60]}")
                for c in ex["components"][:5]:
                    print(f"    - {c['instance_name']}: {c['type'].split('.')[-1]}")
                if ex["connections"]:
                    print(f"    ({len(ex['connections'])} connections)")
        elif cmd == "patterns":
            parts = arg.split()
            if len(parts) >= 2:
                results = get_connection_patterns(G, parts[0], parts[1])
                for p in results:
                    print(f"  {p['from_port']} → {p['to_port']}  (example: {p['example'].split('.')[-1]})")
            else:
                print("  Usage: patterns <from_type> <to_type>")
        elif cmd == "rag":
            ctx = format_rag_context(G, arg)
            print(ctx)
        else:
            print(f"  Unknown command: {cmd}")


def main():
    ap = argparse.ArgumentParser(description="Graph RAG for the Hydraulic Modelica Library")
    ap.add_argument("--query", "-q", help="Single keyword search")
    ap.add_argument("--details", "-d", help="Show full effective interface for a component")
    ap.add_argument("--interface", "-i", help="Find components extending an interface")
    ap.add_argument("--examples", "-e", action="store_true", help="List example circuits")
    ap.add_argument("--rag", help="Generate RAG context for a natural-language query")
    ap.add_argument("--interactive", action="store_true", help="Interactive query mode")
    ap.add_argument("--stats", action="store_true", help="Print graph statistics and exit")
    args = ap.parse_args()

    G = load_graph()

    if args.stats:
        from collections import Counter
        nt = Counter(a.get("node_type", "?") for _, a in G.nodes(data=True))
        et = Counter(d.get("edge_type", "?") for _, _, d in G.edges(data=True))
        print(f"Total nodes: {G.number_of_nodes()}")
        print(f"Total edges: {G.number_of_edges()}")
        print("Node types:", dict(nt))
        print("Edge types:", dict(et))

    if args.query is not None:   # an explicit empty query -> no results, not a silent skip
        results = search_entities(G, args.query)
        print(f"Search results for '{args.query}':")
        for r in results[:20]:
            print(f"  [{r['node_type']:12s}] {r['name']:30s} — {r['description'][:60]}")

    if args.details:
        d = get_component_details(G, args.details)
        if d:
            print("\n" + _format_component_details(d))
        else:
            print(f"Not found: {args.details}")

    if args.interface:
        results = find_components_by_interface(G, args.interface)
        print(f"Components extending '{args.interface}':")
        for r in results:
            print(f"  {r['qualified_name']}: {r['description'][:60]}")

    if args.examples:
        results = find_example_circuits(G)
        print(f"Example circuits ({len(results)}):")
        for ex in results:
            print(f"  {ex['name']}: {ex['description'][:60]}")

    if args.rag:
        print(format_rag_context(G, args.rag))

    if args.interactive:
        interactive_loop(G)


if __name__ == "__main__":
    main()
