"""
Generate a structural report from Modelica Block Debug JSON and Header files.

Usage:
    python report_blocks.py <blockdebug.json> [--header <header.h>] [--reslog <res.log>]

Examples:
    python report_blocks.py BatchProcessModel_blockdebug.json
    python report_blocks.py BatchProcessModel_blockdebug.json --header BatchProcessModel_header.h
    python report_blocks.py BatchProcessModel_blockdebug.json --header BatchProcessModel_header.h --reslog BatchProcessModel_res.log

The script produces a structured diagnostic report covering:
- Variable counts (from header)
- Equation block summary per section (init, ode, output, clocked)
- Coupled equation systems with Jacobian type, tearing, and linearity
- Non-trivial blocks with solvability details
- Eliminated variable aliases
- Runtime performance (from res.log)
"""

import json
import os
import sys
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd
from blockdebug import get_system_type, find_solver_systems, classify_jacobian


def print_section_summary(data, section_name):
    """Print block summary for a section."""
    blocks = data.get(section_name, [])
    if not blocks:
        print(f"  (empty)")
        return

    counts = Counter()
    max_vars = 0
    max_block_idx = None
    total_eqs = 0

    for b in blocks:
        sys_type = get_system_type(b)
        counts[sys_type] += 1
        n_vars = len(b.get('variables', []))
        n_eqs = len(b.get('equations', []))
        total_eqs += n_eqs
        if n_vars > max_vars:
            max_vars = n_vars
            max_block_idx = b.get('block-index')

    print(f"  Blocks: {len(blocks)}, Equations: {total_eqs}")
    print(f"  Types: ", end="")
    parts = []
    order = ['solved', 'mixed', 'continuous', 'linear', 'nonlinear', 'event', 'unknown']
    for t in order:
        if counts[t] > 0:
            parts.append(f"{t}={counts[t]}")
    # include any other system-type string the kernel emits, so it isn't counted-but-hidden
    for t in sorted(counts):
        if t not in order and counts[t] > 0:
            parts.append(f"{t}={counts[t]}")
    print(", ".join(parts))
    print(f"  Largest block: #{max_block_idx} ({max_vars} variables)")


def print_coupled_systems(data, section_name):
    """Print coupled equation systems (linear, nonlinear, torn) with Jacobian info."""
    blocks = data.get(section_name, [])
    found = False

    for b in blocks:
        sys_type = get_system_type(b)
        if sys_type == 'solved':
            continue

        systems = find_solver_systems(b.get('systems', {}))
        if not systems:
            continue

        if not found:
            found = True

        block_vars = [v['name'] for v in b.get('variables', [])]
        print(f"  Block {b.get('block-index')} [{sys_type}] ({len(block_vars)} block vars):")

        for s in systems:
            sid = s['system-id']
            stype = s['system-type']
            jac_raw = s['Jacobian']
            jac_class = classify_jacobian(jac_raw)
            torn = s.get('torn-size')
            n_vars = len(s['variables'])
            variability = s.get('variability', '')
            domain = s.get('value-domain', '')

            parts = [f"System {sid}"]
            parts.append(f"[{stype}]")
            if torn:
                parts.append(f"torn-size={torn}")
            parts.append(f"vars={n_vars}")
            parts.append(f"jacobian={jac_class}")
            if variability and variability != stype:
                parts.append(f"variability={variability}")

            print(f"    {', '.join(parts)}")

            # Show the iteration (tearing) variables
            if torn and s['variables']:
                if len(s['variables']) <= 8:
                    print(f"      Variables: {s['variables']}")
                else:
                    print(f"      Variables: {s['variables'][:6]}... ({n_vars} total)")
        print()

    if not found:
        print("  (no coupled systems)")


def print_nontrivial_blocks(data, section_name):
    """Print details of non-trivial blocks in a section."""
    blocks = data.get(section_name, [])
    found = False

    for b in blocks:
        sys_type = get_system_type(b)
        if sys_type == 'solved':
            continue

        found = True
        block_vars = [v['name'] for v in b.get('variables', [])]
        n_eqs = len(b.get('equations', []))

        print(f"  Block {b.get('block-index')}: [{sys_type}] {n_eqs} eqs, {len(block_vars)} vars")

        if len(block_vars) <= 6:
            print(f"    Variables: {block_vars}")
        else:
            print(f"    Variables: {block_vars[:4]}... ({len(block_vars)} total)")

        # Show equations with non-trivial solvability
        has_nontrivial = False
        for eq in b.get('equations', []):
            non_trivial = bd.nontrivial_incidences(eq)
            if non_trivial:
                if not has_nontrivial:
                    print(f"    Non-trivial solvabilities:")
                    has_nontrivial = True
                text = eq['text'].strip()
                if len(text) > 90:
                    text = text[:90] + "..."
                solvabilities = ", ".join(f"{v}:{s}" for v, s in non_trivial)
                print(f"      {text}")
                print(f"        -> {solvabilities}")
        print()

    if not found:
        print("  (all blocks are explicitly solved)")


def print_solver_summary(data):
    """Print a high-level summary of all solver types across all sections."""
    totals = Counter()
    jac_counts = Counter()

    for section in ['init', 'ode', 'output']:
        for b in data.get(section, []):
            sys_type = get_system_type(b)
            if sys_type == 'solved':
                continue
            systems = find_solver_systems(b.get('systems', {}))
            for s in systems:
                jac_class = classify_jacobian(s['Jacobian'])
                torn = s.get('torn-size')
                if torn:
                    totals['torn'] += 1
                    totals[f'torn-{jac_class}'] += 1
                    jac_counts[jac_class] += 1
                else:
                    totals['direct'] += 1
                    jac_counts[jac_class] += 1

    if not totals:
        print("  No coupled equation systems found.")
        return

    total = totals['torn'] + totals['direct']
    print(f"  Total coupled systems: {total}")
    if totals['torn']:
        print(f"  Torn (iteration) systems: {totals['torn']}")
    if totals['direct']:
        print(f"  Direct systems: {totals['direct']}")
    print()
    print(f"  Jacobian breakdown:")
    for jac_type in ['numeric', 'analytic-linear', 'analytic-nonlinear']:
        if jac_counts[jac_type]:
            label = {
                'numeric': 'Numeric (finite diff)',
                'analytic-linear': 'Analytic linear',
                'analytic-nonlinear': 'Analytic nonlinear',
            }.get(jac_type, jac_type)
            print(f"    {label}: {jac_counts[jac_type]}")


def print_eliminated(data):
    """Print eliminated variable aliases."""
    elim = data.get('eliminated', [])
    if not elim:
        print("  (none)")
        return

    print(f"  {len(elim)} aliases:")
    for e in elim:
        rep = e.get('representative', '?')
        for eq in e.get('solved-equations', []):
            alias = eq.get('variable', {}).get('name', '?')
            print(f"    {alias} -> {rep}")


def compute_summary(data, defines, stats):
    """Condense the whole report into the handful of metrics that matter."""
    s = {}
    for k in ['NX', 'NDX', 'NY', 'NP', 'NI', 'NO']:
        if k in defines:
            s[k] = defines[k][0]
    s['total_zc'] = sum(defines.get(k, (0,))[0]
                        for k in ['NZC_LESS', 'NZC_FLOOR', 'NZC_CEIL', 'NZC_DIV', 'NZC_DELAY'])
    s['init_blocks'] = len(data.get('init', []))
    s['ode_blocks'] = len(data.get('ode', []))
    torn = direct = max_vars = max_torn = 0
    for section in ['init', 'ode', 'output']:
        for b in data.get(section, []):
            if get_system_type(b) == 'solved':
                continue
            for sysm in find_solver_systems(b.get('systems', {})):
                max_vars = max(max_vars, len(sysm.get('variables', []) or []))
                ts = sysm.get('torn-size')
                if ts:
                    torn += 1
                    max_torn = max(max_torn, ts)
                else:
                    direct += 1
    s['coupled_systems'] = torn + direct
    s['torn_systems'] = torn
    s['max_coupled_vars'] = max_vars
    s['max_torn_size'] = max_torn
    s['aliases'] = len(data.get('eliminated', []))
    for k in ['init_time', 'integration_time', 'function_evals', 'events', 'step_events']:
        if k in (stats or {}):
            s[k] = stats[k]
    return s


def print_summary(s):
    def g(k, d='-'):
        return s.get(k, d)
    print("states NX=%s NDX=%s | algebraic NY=%s | params NP=%s | zero-crossings=%s"
          % (g('NX'), g('NDX'), g('NY'), g('NP'), g('total_zc')))
    print("blocks: init=%s ode=%s | eliminated aliases=%s"
          % (g('init_blocks'), g('ode_blocks'), g('aliases')))
    print("coupled nonlinear systems=%s (torn=%s) | largest block=%s vars (Newton size %s)"
          % (g('coupled_systems'), g('torn_systems'), g('max_coupled_vars'), g('max_torn_size')))
    if 'integration_time' in s or 'function_evals' in s:
        print("runtime: int=%ss func-evals=%s events=%s"
              % (g('integration_time'), g('function_evals'), g('events')))


def main():
    parser = argparse.ArgumentParser(
        description="Generate structural report from Modelica blockdebug JSON"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("--header", help="Path to _header.h file for variable counts")
    parser.add_argument("--reslog", help="Path to _res.log file for runtime stats")
    parser.add_argument("--summary", action="store_true",
                        help="Print only the key metrics (a few lines), not the full report")
    parser.add_argument("--json", action="store_true",
                        help="Emit the key metrics as JSON")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    if args.summary or args.json:
        defines = bd.parse_header(args.header) if args.header else {}
        stats = bd.parse_reslog(args.reslog) if args.reslog else {}
        summ = compute_summary(data, defines, stats)
        if args.json:
            print(json.dumps(summ, indent=2))
        else:
            print_summary(summ)
        return

    print("=" * 70)
    print("Modelica Model Structural Report")
    print("=" * 70)

    # Header info
    if args.header:
        print()
        print("--- Variable Counts ---")
        defines = bd.parse_header(args.header)
        important = ['NX', 'NDX', 'NY', 'NP', 'NYSTR', 'NPSTR',
                      'NI', 'NO', 'NZC_LESS', 'NZC_FLOOR', 'NZC_CEIL',
                      'NZC_DIV', 'NZC_DELAY', 'NR', 'NEXT', 'N_CLOCKS']
        for name in important:
            if name in defines:
                val, comment = defines[name]
                if val > 0 or name in ('NX', 'NDX', 'NY', 'NP'):
                    print(f"  {name:20s} = {val:5d}  ({comment})")

        total_zc = sum(defines.get(k, (0,))[0]
                       for k in ['NZC_LESS', 'NZC_FLOOR', 'NZC_CEIL', 'NZC_DIV', 'NZC_DELAY'])
        if total_zc > 0:
            print(f"  {'Total ZC':20s} = {total_zc:5d}")

    # Section summaries
    for section in ['init', 'ode', 'output', 'clocked']:
        print()
        label = bd.section_label(section)
        print(f"--- {label} ---")
        print_section_summary(data, section)

    # Solver summary
    print()
    print("--- Coupled Systems Summary ---")
    print_solver_summary(data)

    # Coupled systems detail per section
    for section in ['ode', 'init']:
        label = bd.section_label(section)
        print()
        print(f"--- Coupled Systems Detail: {label} ---")
        print_coupled_systems(data, section)

    # Non-trivial blocks detail
    print()
    print("--- Non-Trivial ODE Blocks (solvability) ---")
    print_nontrivial_blocks(data, 'ode')

    print("--- Non-Trivial Init Blocks (solvability) ---")
    print_nontrivial_blocks(data, 'init')

    # Eliminated
    print("--- Eliminated Variables ---")
    print_eliminated(data)

    # Runtime stats
    if args.reslog:
        print()
        print("--- Runtime Performance ---")
        stats = bd.parse_reslog(args.reslog)
        if 'init_time' in stats:
            print(f"  Initialization time:  {stats['init_time']:.3f} s")
        if 'homotopy_steps' in stats:
            print(f"  Homotopy init steps:  {stats['homotopy_steps']}")
        if 'integration_time' in stats:
            print(f"  Integration time:     {stats['integration_time']:.3f} s")
        if 'function_evals' in stats:
            print(f"  Function evaluations: {stats['function_evals']}")
        if 'events' in stats:
            print(f"  Events:               {stats['events']}")
        if 'step_events' in stats:
            print(f"  Step events:          {stats['step_events']}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
