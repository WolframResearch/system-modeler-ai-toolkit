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

With --block SECTION:INDEX it reports one block instead: the classes and lines
its equations were flattened from, the variables it solves and the equations
themselves. That is how a block named by the profiler is followed back to the
model text.
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


def print_block_detail(data, section, index, equations_shown):
    """Everything about one block, for following a profile back to the model."""
    blocks = [b for b in data.get(section) or ()
              if isinstance(b, dict) and b.get("block-index") == index]
    if not blocks:
        sys.exit("ERROR: no block %d in section '%s' (sections: %s)"
                 % (index, section, ", ".join(k for k in data if data.get(k))))
    block = blocks[0]
    variables = bd.block_var_names(block)
    equations = block.get("equations") or []

    print("=" * 70)
    print("%s block %d  --  %s" % (section, index, bd.section_label(section)))
    print("=" * 70)
    print("  %d equation(s), %d variable(s), %s"
          % (len(equations), len(variables), block.get("variability", "?")))
    for system in bd.find_solver_systems(block):
        print("  system %s: %s, Jacobian %s%s"
              % (system["system-id"], system["system-type"],
                 bd.classify_jacobian(system["Jacobian"]),
                 ", torn to %d iteration variable(s)" % system["torn-size"]
                 if system["torn-size"] else ""))

    sources = bd.block_sources(block)
    print()
    print("--- Where these equations come from ---")
    if not sources:
        print("  (the build recorded no source spans for this block)")
    for path, (lines, count) in sorted(sources.items(), key=lambda x: -x[1][1]):
        print("  %4d eq  %s  line%s %s"
              % (count, path, "" if len(lines) == 1 else "s",
                 ", ".join(str(l) for l in lines[:12])
                 + (", ..." if len(lines) > 12 else "")))

    print()
    print("--- Variables solved here ---")
    by_component = {}
    for name in variables:
        component = bd.component_of(name) or "(compiler-generated)"
        by_component.setdefault(component, []).append(name)
    for component, names in sorted(by_component.items(), key=lambda x: -len(x[1])):
        print("  %4d  %s   e.g. %s" % (len(names), component, names[0]))

    print()
    print("--- Equations (%d of %d) ---"
          % (min(equations_shown, len(equations)), len(equations)))
    for equation in equations[:equations_shown]:
        origin = bd.equation_source(equation)
        print("  [%s]" % ("%s:%d" % origin if origin else "no source"))
        print("    " + " ".join(equation.get("text", "").split())[:300])


def _artifacts(tempdir):
    """The newest build's (blockdebug, header, res.log) in a diagnose temp dir. A
    temp dir reused across models holds several sets, so the stem of the newest
    _blockdebug.json picks the matching header and log."""
    debug = [os.path.join(tempdir, f) for f in os.listdir(tempdir)
             if f.endswith("_blockdebug.json")]
    if not debug:
        sys.exit("ERROR: no *_blockdebug.json in %s -- run wsm_run.py --mode "
                 "diagnose first" % tempdir)
    debug.sort(key=os.path.getmtime)
    newest = debug[-1]
    stem = os.path.basename(newest)[:-len("_blockdebug.json")]
    optional = lambda suffix: (
        os.path.join(tempdir, stem + suffix)
        if os.path.isfile(os.path.join(tempdir, stem + suffix)) else None)
    return newest, optional("_header.h"), optional("_res.log")


def main():
    parser = argparse.ArgumentParser(
        description="Generate structural report from Modelica blockdebug JSON"
    )
    parser.add_argument("blockdebug_json", nargs="?",
                        help="Path to _blockdebug.json file (or use --tempdir)")
    parser.add_argument("--tempdir", metavar="DIR",
                        help="A --mode diagnose temp dir: find the newest model's "
                             "_blockdebug.json, _header.h and _res.log in it "
                             "instead of naming all three")
    parser.add_argument("--header", help="Path to _header.h file for variable counts")
    parser.add_argument("--reslog", help="Path to _res.log file for runtime stats")
    parser.add_argument("--summary", action="store_true",
                        help="Print only the key metrics (a few lines), not the full report")
    parser.add_argument("--json", action="store_true",
                        help="Emit the key metrics as JSON")
    parser.add_argument("--block", metavar="SECTION:INDEX",
                        help="Print everything about one block instead of the full "
                             "report -- its equations, the classes and lines they "
                             "were flattened from, and the variables it solves. "
                             "Takes a block named by the profile, e.g. ode:366.")
    parser.add_argument("--equations", type=int, default=10, metavar="N",
                        help="--block: how many of the block's equations to print "
                             "(default 10)")

    args = parser.parse_args()
    if args.tempdir:
        args.blockdebug_json, args.header, args.reslog = _artifacts(args.tempdir)
    elif not args.blockdebug_json:
        parser.error("give a _blockdebug.json path, or --tempdir")
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    if args.block:
        section, _, index = args.block.partition(":")
        if not index.strip().isdigit():
            sys.exit("ERROR: --block wants SECTION:INDEX, e.g. ode:366")
        print_block_detail(data, section.strip(), int(index), args.equations)
        return

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
