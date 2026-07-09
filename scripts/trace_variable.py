"""
Trace Variable Dependency Chain in Modelica Block Debug JSON

Usage:
    python trace_variable.py <blockdebug.json> <variable_name> [--section init|ode|both]

Examples:
    python trace_variable.py CoupledClutches_blockdebug.json clutch1.w_rel
    python trace_variable.py CoupledClutches_blockdebug.json "der(clutch1.w_rel)" --section ode
    python trace_variable.py CoupledClutches_blockdebug.json clutch1.w_rel --section both

Sections:
    init  - Initialization phase (how the variable gets its starting value)
    ode   - Integration step (how the variable is computed each time step)
    both  - Show both init and ode traces (default)

The script walks backwards through the block dependency graph starting from the
block that solves the target variable, following predecessors all the way to the
leaf nodes (blocks with no predecessors). This reveals every equation and variable
involved in computing the target.
"""

import os
import sys
import argparse
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd
from blockdebug import get_system_type


def find_target_block(blocks, variable_name):
    """Find the block that solves a given variable."""
    for b in blocks:
        for v in b.get('variables', []):
            if v['name'] == variable_name:
                return b['block-index']
    return None


def trace_dependencies(blocks, start_block_idx):
    """BFS backwards through predecessors to collect the full dependency chain."""
    blocks_by_idx = {b['block-index']: b for b in blocks}

    visited = set()
    queue = deque([start_block_idx])
    trace = []

    while queue:
        idx = queue.popleft()
        if idx in visited:
            continue
        visited.add(idx)

        b = blocks_by_idx.get(idx)
        if b is None:
            continue

        trace.append(b)
        for pred in b.get('predecessors', []):
            if pred not in visited:
                queue.append(pred)

    # Reverse so leaves come first
    trace.reverse()
    return trace


def find_eliminated_aliases(data, variable_name):
    """Find any eliminated variable aliases involving the target variable."""
    aliases = []
    for e in data.get('eliminated', []):
        rep = e.get('representative', '')
        solved_vars = [eq.get('variable', {}).get('name', '')
                       for eq in e.get('solved-equations', [])]
        all_names = [rep] + solved_vars
        if any(variable_name in n for n in all_names):
            aliases.append(e)
    return aliases


def format_block(block, indent=""):
    """Format a single block for display."""
    sys_type = get_system_type(block)
    block_vars = bd.block_var_names(block)
    preds = block.get('predecessors', [])
    is_leaf = len(preds) == 0

    lines = []

    # Block header
    leaf_tag = " [LEAF]" if is_leaf else ""
    if len(block_vars) <= 5:
        lines.append(f"{indent}Block {block['block-index']}: [{sys_type}]{leaf_tag}")
        lines.append(f"{indent}  Solves: {block_vars}")
    else:
        lines.append(f"{indent}Block {block['block-index']}: [{sys_type}]{leaf_tag} ({len(block_vars)} variables)")
        lines.append(f"{indent}  Solves: {block_vars[:5]}...")
        lines.append(f"{indent}         ...and {len(block_vars) - 5} more")

    if preds:
        lines.append(f"{indent}  Depends on blocks: {preds}")

    # Equations
    for eq in block.get('equations', []):
        text = eq['text'].strip()
        source = eq.get('source', '')

        if len(text) > 120:
            lines.append(f"{indent}  Eq: {text[:120]}...")
        else:
            lines.append(f"{indent}  Eq: {text}")

        if source:
            lines.append(f"{indent}      Source: {source}")

        # Flag non-trivial solvability
        non_trivial = bd.nontrivial_incidences(eq)
        if non_trivial:
            lines.append(f"{indent}      ** {non_trivial}")

    return "\n".join(lines)


def print_trace(data, variable_name, section_name):
    """Print the full dependency trace for a variable in a given section."""
    blocks = data.get(section_name, [])
    if not blocks:
        print(f"  No blocks in '{section_name}' section.")
        return False

    start_idx = find_target_block(blocks, variable_name)
    if start_idx is None:
        print(f"  Variable '{variable_name}' not found in '{section_name}' section.")
        return False

    trace = trace_dependencies(blocks, start_idx)

    # Summarize
    sys_types = {}
    for b in trace:
        st = get_system_type(b)
        sys_types[st] = sys_types.get(st, 0) + 1
    leaves = sum(1 for b in trace if len(b.get('predecessors', [])) == 0)

    print(f"  {len(trace)} blocks in chain, {leaves} leaf nodes")
    print(f"  System types: {sys_types}")
    print()

    for b in trace:
        print(format_block(b, indent="  "))
        print()

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Trace variable dependency chain in Modelica blockdebug JSON"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("variable", help="Variable name to trace (e.g. clutch1.w_rel)")
    parser.add_argument("--section", choices=["init", "ode", "both"], default="both",
                        help="Which section to trace: init, ode, or both (default: both)")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)
    variable = args.variable

    # Check eliminated aliases
    aliases = find_eliminated_aliases(data, variable)

    sections = ["init", "ode"] if args.section == "both" else [args.section]

    print(f"{'=' * 70}")
    print(f"Variable Trace: {variable}")
    print(f"{'=' * 70}")

    if aliases:
        print()
        print("Aliases (eliminated variables):")
        for e in aliases:
            rep = e.get('representative', '?')
            for eq in e.get('solved-equations', []):
                alias_var = eq.get('variable', {}).get('name', '?')
                print(f"  {alias_var} -> {rep}")
        print()

    for section in sections:
        print(f"--- {bd.section_label(section)} ---")
        print()
        found = print_trace(data, variable, section)
        if not found:
            # Try der() variant in ode
            if section == "ode" and not variable.startswith("der("):
                der_var = f"der({variable})"
                print(f"  Trying derivative: {der_var}")
                print()
                print_trace(data, der_var, section)
        print()


if __name__ == "__main__":
    main()
