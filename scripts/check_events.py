"""
Analyze zero crossings and event structure in Modelica models.

Reports:
- All zero crossing variables ($eventState) and their source equations
- Classification by type (time events, state events, flow direction, phase checks)
- Blocks containing multiple event states (chattering risk)
- Zero crossing counts from the header
- Runtime event statistics from res.log

Usage:
    python check_events.py <blockdebug.json> [--header <header.h>] [--reslog <res.log>]

Examples:
    python check_events.py Model_blockdebug.json
    python check_events.py Model_blockdebug.json --header Model_header.h --reslog Model_res.log
"""

import os
import re
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockdebug as bd


def find_event_states(data, section_name):
    """Find all $eventState variables and their defining equations."""
    events = []

    for b in data.get(section_name, []):
        for eq in b.get('equations', []):
            text = eq['text'].strip()
            # Look for eventState assignments
            if '$eventState' in text and ':=' in text:
                # Extract event state name
                m = re.match(r'(\$eventState\d+)\s*:=\s*(.*)', text)
                if m:
                    events.append({
                        'name': m.group(1),
                        'expression': m.group(2).rstrip(),
                        'block': b['block-index'],
                        'source': eq.get('source', ''),
                        'eq_index': eq.get('eq-index'),
                    })

    return events


def classify_event(event):
    """Classify an event by its expression pattern."""
    expr = event['expression']

    if 'time <' in expr or 'time >' in expr:
        return 'time-event'
    elif 'regularFlow' in expr or 'inFlow' in expr or '.s[' in expr:
        return 'flow-direction'
    elif '< valve' in expr or '< pump' in expr or 'm_flow' in expr:
        return 'flow-rate'
    elif 'phase' in expr or 'hvl_p' in expr or '22064000' in expr:
        return 'phase-boundary'
    elif 'w_rel' in expr or 'w_small' in expr:
        return 'friction-slip'
    elif '.active' in expr or 'transition' in expr:
        return 'state-machine'
    elif '< 0' in expr or '> 0' in expr or '0.0 <' in expr:
        return 'sign-check'
    else:
        return 'other'


def find_event_blocks(data, section_name):
    """Find blocks that are of type 'event'."""
    event_blocks = []
    for b in data.get(section_name, []):
        if bd.get_system_type(b) == 'event':
            block_vars = bd.block_var_names(b)
            event_blocks.append({
                'block': b['block-index'],
                'variables': block_vars,
            })
    return event_blocks


def count_events_in_mixed_blocks(data, section_name):
    """Count $eventState variables in mixed blocks (chattering risk)."""
    mixed_events = []
    for b in data.get(section_name, []):
        if bd.get_system_type(b) != 'mixed':
            continue

        block_vars = bd.block_var_names(b)
        event_vars = [v for v in block_vars if '$eventState' in v]
        if event_vars:
            mixed_events.append({
                'block': b['block-index'],
                'total_vars': len(block_vars),
                'event_vars': event_vars,
            })
    return mixed_events


def main():
    parser = argparse.ArgumentParser(
        description="Analyze zero crossings and events in Modelica models"
    )
    parser.add_argument("blockdebug_json", help="Path to _blockdebug.json file")
    parser.add_argument("--header", help="Path to _header.h for zero crossing counts")
    parser.add_argument("--reslog", help="Path to _res.log for runtime event stats")

    args = parser.parse_args()
    bd.enable_utf8_console()

    data = bd.load(args.blockdebug_json)

    print("=" * 70)
    print("Zero Crossing & Event Analysis")
    print("=" * 70)

    # Header ZC counts
    if args.header:
        print()
        print("--- Zero Crossing Counts (compile-time) ---")
        zc = bd.parse_header(args.header)
        total = 0
        for name in ['NZC_LESS', 'NZC_FLOOR', 'NZC_CEIL', 'NZC_DIV', 'NZC_DELAY']:
            val = zc.get(name, (0, ''))[0]
            total += val
            if val > 0:
                label = name.replace('NZC_', '').lower()
                print(f"  {label:10s}: {val}")
        print(f"  {'total':10s}: {total}")

    # Runtime events
    if args.reslog:
        print()
        print("--- Runtime Event Statistics ---")
        stats = bd.parse_reslog(args.reslog)
        if stats.get('events') is not None:
            print(f"  Total events:     {stats['events']}")
        if stats.get('step_events') is not None:
            print(f"  Step events:      {stats['step_events']}")
        if stats.get('events', 0) > 50:
            print(f"  ** High event count - consider smoothing discontinuities")

    # Event state variables in ODE
    print()
    print("--- Event State Variables (ODE) ---")
    events = find_event_states(data, 'ode')

    if not events:
        print("  No $eventState variables found.")
    else:
        # Classify
        by_class = defaultdict(list)
        for e in events:
            cls = classify_event(e)
            by_class[cls].append(e)

        print(f"  Total: {len(events)} event state variables")
        print()
        print("  By category:")
        for cls in ['time-event', 'flow-direction', 'flow-rate', 'phase-boundary',
                     'friction-slip', 'state-machine', 'sign-check', 'other']:
            items = by_class.get(cls, [])
            if items:
                print(f"    {cls} ({len(items)}):")
                for e in items:
                    expr = e['expression']
                    if len(expr) > 80:
                        expr = expr[:80] + "..."
                    print(f"      {e['name']}: {expr}")

    # Event blocks
    print()
    print("--- Dedicated Event Blocks (ODE) ---")
    event_blocks = find_event_blocks(data, 'ode')
    if event_blocks:
        for eb in event_blocks:
            print(f"  Block {eb['block']}: {eb['variables']}")
    else:
        print("  None")

    # Events inside mixed blocks (chattering risk)
    print()
    print("--- Event States in Mixed Blocks (chattering risk) ---")
    mixed = count_events_in_mixed_blocks(data, 'ode')
    if mixed:
        for m in mixed:
            print(f"  Block {m['block']} ({m['total_vars']} total vars, {len(m['event_vars'])} event states):")
            for v in m['event_vars']:
                print(f"    {v}")
        print()
        print("  ** Event states coupled with continuous variables in mixed blocks")
        print("     can cause event chattering if flow directions oscillate rapidly.")
    else:
        print("  None — all event states are in separate blocks (good)")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
