"""
Analyze tearing structure in Modelica equation systems.

For each torn system, shows:
- Iteration (tearing) variables — what the Newton solver iterates on
- Residual equations — the equations being solved
- Causal chain — explicitly solved variables that depend on iteration variables
- Tearing efficiency — how much tearing reduced the Newton system size

Usage:
    python check_tearing.py <blockdebug.json> [--section ode|init|both]

Examples:
    python check_tearing.py Model_blockdebug.json
    python check_tearing.py Model_blockdebug.json --section ode
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd


def find_torn_systems(obj, results=None, path='', solver=None):
    """Recursively find all torn equation systems with their h (causal) and g (residual) equations.

    Each result carries the solver info from the enclosing tree node's 'system'
    sibling, so torn partitionings are paired with their own solver system (not
    with whatever unrelated system happens to share a document-order index)."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        # A tree node holds the solver info in 'system' next to its 'equations';
        # remember the nearest enclosing one while descending.
        sib = obj.get('system')
        if isinstance(sib, dict) and 'system-type' in sib:
            solver = sib
        # Check for torn partitioning
        if obj.get('partitioning-type') == 'torn':
            # h = causal equations, g = residual equations
            h_eqs = obj.get('h', [])
            g_eqs = obj.get('g', [])
            results.append({
                'h_equations': h_eqs,
                'g_equations': g_eqs,
                'path': path,
                'solver': solver or {},
            })
        for k, v in obj.items():
            find_torn_systems(v, results, f'{path}.{k}' if path else k, solver)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            find_torn_systems(item, results, f'{path}[{i}]', solver)
    return results


def format_equation(eq, max_len=100):
    """Format an equation text, truncating if needed."""
    text = eq.get('text', '').strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Analyze tearing structure in Modelica equation systems"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("--section", choices=["init", "ode", "both"], default="both")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    sections = ["init", "ode"] if args.section == "both" else [args.section]

    print("=" * 70)
    print("Tearing Analysis")
    print("=" * 70)

    total_torn = 0
    total_full_size = 0
    total_torn_size = 0

    for section in sections:
        label = bd.section_label(section)
        print()
        print(f"--- {label} ---")

        blocks = data.get(section, [])
        found_any = False

        for b in blocks:
            block_idx = b['block-index']
            block_vars = [v['name'] for v in b.get('variables', [])]

            # Find torn systems in this block
            torn_systems = find_torn_systems(b.get('systems', {}))

            if not torn_systems:
                continue

            found_any = True

            for ts in torn_systems:
                h_eqs = ts['h_equations']
                g_eqs = ts['g_equations']

                # Solver info captured from the torn system's own tree node
                solver = ts['solver']
                torn_size = solver.get('torn-size', len(g_eqs))
                jac = solver.get('Jacobian')
                sys_id = solver.get('system-id', '?')
                sys_vars = solver.get('variables', [])
                full_size = len(sys_vars)

                jac_label = 'NUMERIC' if jac is None else f'ANALYTIC ({jac})'

                total_torn += 1
                total_full_size += full_size
                total_torn_size += torn_size

                print()
                print(f"  Block {block_idx}, System {sys_id}:")
                print(f"    Full size: {full_size} vars -> Torn size: {torn_size} iteration vars")
                print(f"    Reduction: {full_size - torn_size} vars solved explicitly ({100*(full_size-torn_size)/max(full_size,1):.0f}% reduction)")
                print(f"    Jacobian: {jac_label}")

                # Show iteration variables (from g equations)
                if g_eqs:
                    print(f"    Residual equations ({len(g_eqs)}) — what Newton solves:")
                    for eq in g_eqs:
                        text = format_equation(eq)
                        source = eq.get('source', '')
                        print(f"      {text}")
                        if source:
                            print(f"        Source: {source}")

                        # Show incidences with derivative info if available
                        incidences = eq.get('incidences', [])
                        deriv_info = [(i.get('variable', ''), i.get('derivative', ''), i.get('solvability', ''))
                                      for i in incidences if i.get('derivative')]
                        if deriv_info:
                            print(f"        Derivatives: {deriv_info}")

                # Show causal equations (h — explicitly solved given iteration vars)
                if h_eqs:
                    print(f"    Causal equations ({len(h_eqs)}) — solved explicitly:")
                    for eq in h_eqs[:5]:
                        text = format_equation(eq)
                        print(f"      {text}")
                    if len(h_eqs) > 5:
                        print(f"      ... and {len(h_eqs) - 5} more")

        if not found_any:
            print("  No torn systems found.")

    # Summary
    if total_torn > 0:
        print()
        print("--- Tearing Summary ---")
        print(f"  Total torn systems: {total_torn}")
        print(f"  Total variables before tearing: {total_full_size}")
        print(f"  Total iteration variables after tearing: {total_torn_size}")
        print(f"  Overall reduction: {total_full_size - total_torn_size} vars "
              f"({100*(total_full_size - total_torn_size)/max(total_full_size,1):.0f}%)")
        print()
        print("  Tearing converts large nonlinear systems into smaller Newton problems")
        print("  by identifying which variables to iterate on and solving the rest")
        print("  explicitly. Lower torn-size = faster Newton convergence.")
        print()
        print("  If a system has a numeric Jacobian with torn-size N, the solver needs")
        print("  N+1 function evaluations per Newton step for finite differencing.")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
