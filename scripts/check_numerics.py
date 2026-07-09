"""
Analyze numeric vs analytic Jacobian systems in Modelica models.

Reports:
- All coupled equation systems with their Jacobian type
- Numeric Jacobian systems (expensive — require finite differencing)
- Analytic Jacobian systems (efficient — symbolic derivatives)
- Cost estimate per system (torn-size determines Newton iteration cost)
- Summary showing total numeric cost vs analytic cost

Usage:
    python check_numerics.py <blockdebug.json> [--reslog <res.log>] [--section ode|init|both]

Examples:
    python check_numerics.py Model_blockdebug.json
    python check_numerics.py Model_blockdebug.json --reslog Model_res.log
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd
from blockdebug import find_solver_systems, classify_jacobian
from blockdebug import is_numeric_jacobian as is_numeric


def collect_systems(data, section_name):
    """Collect all solver systems from a section, grouped by block."""
    block_systems = []
    for b in data.get(section_name, []):
        block_idx = b['block-index']
        block_vars = [v['name'] for v in b.get('variables', [])]
        systems = find_solver_systems(b.get('systems', {}))
        if systems:
            block_systems.append({
                'block': block_idx,
                'block_vars': len(block_vars),
                'systems': systems,
            })
    return block_systems


def main():
    parser = argparse.ArgumentParser(
        description="Analyze numeric vs analytic Jacobian systems"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("--reslog", help="Path to _res.log for cost estimates")
    parser.add_argument("--section", choices=["init", "ode", "both"], default="both")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    sections = ["init", "ode"] if args.section == "both" else [args.section]
    stats = bd.parse_reslog(args.reslog) if args.reslog else {}

    print("=" * 70)
    print("Numeric vs Analytic Jacobian Analysis")
    print("=" * 70)

    all_numeric = []
    all_analytic = []

    for section in sections:
        label = bd.section_label(section)
        print()
        print(f"--- {label} ---")

        block_systems = collect_systems(data, section)
        if not block_systems:
            print("  No coupled systems found.")
            continue

        for bs in block_systems:
            print(f"  Block {bs['block']} ({bs['block_vars']} block vars):")
            for s in bs['systems']:
                jac_class = classify_jacobian(s['Jacobian'])
                torn = s.get('torn-size')
                n_vars = len(s['variables'])
                marker = "**" if is_numeric(s['Jacobian']) and torn else "  "

                parts = [f"System {s['system-id']}"]
                if torn:
                    parts.append(f"torn-size={torn}")
                parts.append(f"vars={n_vars}")
                parts.append(f"jacobian={jac_class}")

                print(f"  {marker}{', '.join(parts)}")

                if torn and s['variables']:
                    if len(s['variables']) <= 6:
                        print(f"      Iteration vars: {s['variables']}")
                    else:
                        print(f"      Iteration vars: {s['variables'][:4]}... ({n_vars} total)")

                if is_numeric(s['Jacobian']):
                    all_numeric.append({
                        'section': section,
                        'block': bs['block'],
                        'system': s['system-id'],
                        'torn_size': torn or n_vars,
                        'total_vars': n_vars,
                        'variables': s['variables'],
                    })
                else:
                    all_analytic.append({
                        'section': section,
                        'block': bs['block'],
                        'system': s['system-id'],
                        'torn_size': torn or n_vars,
                        'total_vars': n_vars,
                    })
            print()

    # Summary
    print()
    print("--- Summary ---")
    print(f"  Numeric Jacobian systems:  {len(all_numeric)}")
    print(f"  Analytic Jacobian systems: {len(all_analytic)}")

    if all_numeric:
        print()
        print("--- Numeric Jacobian Cost Analysis ---")
        print("  Each numeric Jacobian requires (torn_size + 1) function evaluations")
        print("  per Newton iteration for finite differencing.")
        print()

        total_numeric_cost = 0
        ode_numeric = [s for s in all_numeric if s['section'] == 'ode']
        if ode_numeric:
            print("  ODE systems (evaluated every time step):")
            for s in sorted(ode_numeric, key=lambda x: x['torn_size'], reverse=True):
                cost = s['torn_size'] + 1
                total_numeric_cost += cost
                print(f"    System {s['system']}: torn_size={s['torn_size']}, "
                      f"cost={cost} evals/Newton step")

            print()
            print(f"  Total numeric cost per Newton iteration: {total_numeric_cost} extra function evals")

            if stats.get('function_evals'):
                fevals = stats['function_evals']
                print(f"  Total function evaluations (runtime):    {fevals}")
                # Rough estimate: each event or stiff region triggers multiple Newton iterations
                print(f"  Estimated numeric Jacobian overhead:     ~{total_numeric_cost}/{fevals} "
                      f"per step ({100*total_numeric_cost/max(fevals,1):.1f}% per Newton step)")

            if stats.get('integration_time'):
                print(f"  Integration time: {stats['integration_time']:.3f} s")

    if all_numeric:
        print()
        print("--- Recommendations ---")
        # Find the most expensive numeric system
        ode_numeric = [s for s in all_numeric if s['section'] == 'ode']
        if ode_numeric:
            worst = max(ode_numeric, key=lambda x: x['torn_size'])
            print(f"  Largest numeric system: System {worst['system']} "
                  f"(torn_size={worst['torn_size']}, {worst['total_vars']} vars)")
            print(f"  Iteration variables: {worst['variables'][:5]}")
            print()
            print("  To reduce numeric Jacobian cost:")
            print("  - Simplify medium model (ConstantPropertyLiquidWater vs IF97)")
            print("  - Add mixing volumes to break algebraic loops")
            print("  - Check if external function calls prevent symbolic differentiation")
            print("  - Use smooth() or noEvent() to simplify expressions where safe")

    print()
    print("=" * 70)
    print()
    print("Legend:")
    print("  ** = numeric Jacobian (expensive)")
    print("  torn-size = number of iteration variables after tearing")
    print("  vars = total variables in the system (including explicitly solved)")


if __name__ == "__main__":
    main()
