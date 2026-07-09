"""
Detect structural singularity issues in Modelica models.

Analyzes the blockdebug JSON and out.json for:
- Variables with conditioned/relaxed/independent solvability (potential singularities)
- Blocks where solvability depends on which if-branch is active
- Tautological assumptions (e.g. "A or not A") in error messages
- Equations where variables become unsolvable under certain conditions

Usage:
    python check_singularity.py <blockdebug.json> [--outjson <out.json>] [--section ode|init|both]

Examples:
    python check_singularity.py Model_blockdebug.json
    python check_singularity.py Model_blockdebug.json --outjson diagnose.out.json
    python check_singularity.py Model_blockdebug.json --section init
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd


def find_solvability_issues(data, section_name):
    """Find all variables with non-trivial solvability in a section."""
    issues = []

    for b in data.get(section_name, []):
        block_idx = b['block-index']
        block_vars = [v['name'] for v in b.get('variables', [])]

        for eq in b.get('equations', []):
            incidences = eq.get('incidences', [])
            non_trivial = [i for i in incidences if i['solvability'] != 'solvable']
            if non_trivial:
                issues.append({
                    'block': block_idx,
                    'equation': eq['text'].strip(),
                    'source': eq.get('source', ''),
                    'incidences': [(i['variable'], i['solvability']) for i in non_trivial],
                    'all_vars': [i['variable'] for i in incidences],
                })

    return issues


def classify_issues(issues):
    """Group issues by solvability type."""
    by_type = defaultdict(list)
    for issue in issues:
        for var, solv in issue['incidences']:
            by_type[solv].append({
                'variable': var,
                'block': issue['block'],
                'equation': issue['equation'],
                'source': issue['source'],
            })
    return by_type


def find_at_risk_variables(issues):
    """Find variables that appear with different solvability types across equations.
    These are the most likely to cause runtime singularities."""
    var_solvabilities = defaultdict(set)
    var_blocks = defaultdict(set)
    var_equations = defaultdict(list)

    for issue in issues:
        for var, solv in issue['incidences']:
            var_solvabilities[var].add(solv)
            var_blocks[var].add(issue['block'])
            var_equations[var].append(issue['equation'][:80])

    at_risk = {}
    for var, solvs in var_solvabilities.items():
        if len(solvs) > 1 or 'relaxed' in solvs or 'conditioned' in solvs:
            at_risk[var] = {
                'solvabilities': solvs,
                'blocks': var_blocks[var],
                'equations': var_equations[var][:3],
            }
    return at_risk


def parse_outjson_errors(outjson_path):
    """Parse structural errors and warnings from the test output JSON."""
    results = bd.load(outjson_path)

    messages = []
    if isinstance(results, list) and len(results) > 0:
        msg_data = results[0].get('messages', {})
        for category in ['errors', 'warnings']:
            for msg in msg_data.get(category, []):
                if msg.get('type') == 'SYMBOLIC':
                    messages.append({
                        'category': category.rstrip('s'),
                        'id': msg.get('id', '?'),
                        'message': msg.get('message', ''),
                    })
    return messages


def main():
    parser = argparse.ArgumentParser(
        description="Detect structural singularity issues in Modelica models"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("--outjson", help="Path to .out.json for error messages")
    parser.add_argument("--section", choices=["init", "ode", "both"], default="both")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    sections = ["init", "ode"] if args.section == "both" else [args.section]

    print("=" * 70)
    print("Structural Singularity Analysis")
    print("=" * 70)

    # Parse error messages if available
    if args.outjson:
        print()
        print("--- Compiler Messages (SYMBOLIC) ---")
        messages = parse_outjson_errors(args.outjson)
        if messages:
            for msg in messages:
                print(f"  [{msg['category'].upper()}] ID {msg['id']}:")
                # Print first 200 chars of message
                text = msg['message'].replace('\\n', '\n').replace('\\;`', '').strip()
                for line in text.split('\n')[:8]:
                    print(f"    {line.strip()}")
                if text.count('\n') > 8:
                    print(f"    ... ({text.count(chr(10))} lines total)")
                print()
        else:
            print("  No symbolic errors or warnings found.")

    for section in sections:
        label = bd.section_label(section)
        print()
        print(f"--- {label}: Solvability Issues ---")

        issues = find_solvability_issues(data, section)

        if not issues:
            print("  No solvability issues found.")
            continue

        # Summary by type
        by_type = classify_issues(issues)
        print()
        print(f"  Summary:")
        for solv_type in ['relaxed', 'conditioned', 'independent']:
            entries = by_type.get(solv_type, [])
            if entries:
                unique_vars = set(e['variable'] for e in entries)
                unique_blocks = set(e['block'] for e in entries)
                print(f"    {solv_type}: {len(unique_vars)} variables in {len(unique_blocks)} blocks")

        # At-risk variables
        at_risk = find_at_risk_variables(issues)
        if at_risk:
            print()
            print(f"  At-risk variables (conditioned/relaxed — solvability depends on branch):")
            for var, info in sorted(at_risk.items()):
                solvs = ", ".join(sorted(info['solvabilities']))
                blocks = ", ".join(str(b) for b in sorted(info['blocks']))
                print(f"    {var}")
                print(f"      Solvability: {solvs}")
                print(f"      Blocks: {blocks}")
                for eq in info['equations']:
                    print(f"      Eq: {eq}...")

        # Detail per block
        print()
        print(f"  Detail by block:")
        blocks_seen = set()
        for issue in issues:
            if issue['block'] not in blocks_seen:
                blocks_seen.add(issue['block'])
                # Count issues in this block
                block_issues = [i for i in issues if i['block'] == issue['block']]
                n_relaxed = sum(1 for i in block_issues
                                for _, s in i['incidences'] if s == 'relaxed')
                n_conditioned = sum(1 for i in block_issues
                                    for _, s in i['incidences'] if s == 'conditioned')
                n_independent = sum(1 for i in block_issues
                                    for _, s in i['incidences'] if s == 'independent')
                parts = []
                if n_relaxed: parts.append(f"{n_relaxed} relaxed")
                if n_conditioned: parts.append(f"{n_conditioned} conditioned")
                if n_independent: parts.append(f"{n_independent} independent")
                print(f"    Block {issue['block']}: {', '.join(parts)}")

    print()
    print("=" * 70)
    print()
    print("Legend:")
    print("  relaxed     = variable solved via relaxation (not direct inversion)")
    print("  conditioned = solvability depends on which if-branch is active")
    print("  independent = variable appears but is not solved in this equation")


if __name__ == "__main__":
    main()
