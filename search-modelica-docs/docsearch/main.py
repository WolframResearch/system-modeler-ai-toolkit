"""CLI for searching the bundled Modelica / System Modeler documentation.

Examples:
    python -m docsearch.main --query "how do I write a when statement" --k 5
    python -m docsearch.main --query "fluid tank tutorial" --corpus systemmodeler
    python -m docsearch.main --show "https://reference.wolfram.com/system-modeler/..."
    python -m docsearch.main --eval --k 5
    python -m docsearch.main --corpora
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Bundled text is UTF-8 (curly quotes, em dashes, etc.). Make sure output is
# UTF-8 too, even on Windows consoles that default to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from .index import (
    ALIASES,
    CORPORA,
    CORPUS_LABEL,
    DATA_DIR,
    Index,
    resolve_corpora,
)


def _resolve_corpora(name):
    try:
        return resolve_corpora(name)
    except ValueError as e:
        sys.exit(f"Error: {e}")


def _preambles(corpora):
    path = os.path.join(DATA_DIR, "preambles.json")
    with open(path, encoding="utf-8") as fh:
        pre = json.load(fh)
    return {c: pre[c] for c in corpora if c in pre}


def cmd_query(args):
    corpora = _resolve_corpora(args.corpus)
    idx = Index(corpora)
    hits = idx.search(args.query, corpora=corpora, k=args.k)

    if args.json:
        out = [
            {
                "rank": r,
                "corpus": d["corpus"],
                "title": d["title"],
                "url": d["url"],
                "score": round(s, 4),
                "text": d["text"] if args.full else d["text"][:600],
            }
            for r, (d, s) in enumerate(hits, 1)
        ]
        print(json.dumps({"query": args.query, "results": out}, indent=2))
        return

    if not hits:
        print(f"No matches for: {args.query!r}")
        return

    # Citation guidance for the corpora that actually appear in the results.
    shown = []
    for c, text in _preambles({d["corpus"] for d, _ in hits}).items():
        shown.append(f"[{CORPUS_LABEL.get(c, c)}] {text}")
    if shown:
        print("=== How to use these excerpts ===")
        for s in shown:
            print(s)
        print()

    print(f"=== Top {len(hits)} results for: {args.query!r} ===\n")
    for r, (d, s) in enumerate(hits, 1):
        body = d["text"]
        snippet = body if args.full else body[:600].rstrip()
        more = "" if args.full or len(body) <= 600 else " […]"
        print(f"[{r}] ({d['corpus']}, score={s:.3f}) {d['title']}")
        print(f"    {d['url']}")
        print("    " + snippet.replace("\n", "\n    ") + more)
        print()
    if not args.full:
        print("(Use --full, or --show <url>, to read a full passage.)")


def cmd_show(args):
    idx = Index()
    doc = idx.get(args.show)
    if doc is None:
        print(f"No chunk with url: {args.show}")
        return
    pre = _preambles([doc["corpus"]]).get(doc["corpus"])
    if pre:
        print(f"=== {CORPUS_LABEL.get(doc['corpus'], doc['corpus'])} ===")
        print(pre)
        print()
    print(doc["text"])


def cmd_corpora(args):
    idx = Index()
    counts = {}
    for d in idx.docs:
        counts[d["corpus"]] = counts.get(d["corpus"], 0) + 1
    print("Corpora (chunks):")
    for c in CORPORA:
        print(f"  {c:5s} {counts.get(c,0):5d}  {CORPUS_LABEL[c]}")
    print("\nAliases for --corpus:")
    for a, members in ALIASES.items():
        print(f"  {a:14s} -> {', '.join(members)}")


def cmd_eval(args):
    """Recall@k and MRR against the bundled gold query->url sets."""
    corpora = _resolve_corpora(args.corpus)
    idx = Index(corpora)
    overall_hit = overall_n = 0
    overall_rr = 0.0
    no_gold = []
    print(f"Eval (k={args.k}, corpus={args.corpus}):")
    for c in corpora:
        path = os.path.join(DATA_DIR, "eval", f"{c}.jsonl")
        if not os.path.exists(path):
            no_gold.append(c)
            print(f"  {c:5s} (no gold set)")
            continue
        try:
            gold = [json.loads(l)
                    for l in open(path, encoding="utf-8") if l.strip()]
        except json.JSONDecodeError as e:
            sys.exit(f"Error: gold set {path} is not valid JSONL: {e}")
        if not gold:
            print(f"  {c:5s} (empty gold set, skipped)")
            continue
        hit = 0
        rr = 0.0
        for g in gold:
            results = idx.search(g["Text"], corpora=corpora, k=args.k)
            urls = [d["url"] for d, _ in results]
            if g["Value"] in urls:
                hit += 1
                rr += 1.0 / (urls.index(g["Value"]) + 1)
        n = len(gold)
        overall_hit += hit
        overall_n += n
        overall_rr += rr
        print(
            f"  {c:5s} recall@{args.k}={hit/n:.3f}  MRR@{args.k}={rr/n:.3f}"
            f"  ({hit}/{n})"
        )
    if overall_n:
        print(
            f"  TOTAL recall@{args.k}={overall_hit/overall_n:.3f}"
            f"  MRR@{args.k}={overall_rr/overall_n:.3f}  ({overall_hit}/{overall_n})"
        )
        return 0
    # Nothing was measured (every requested corpus lacks a gold set) — don't let
    # that read as a passing eval.
    print(f"  no gold sets available for: {', '.join(no_gold) or args.corpus} — nothing measured")
    return 1


def _pos_int(text):
    """argparse type for --k: a positive result count (0/negative slice oddly)."""
    val = int(text)
    if val < 1:
        raise argparse.ArgumentTypeError("must be >= 1, got %s" % text)
    return val


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--query", help="natural-language search query")
    p.add_argument("--show", help="print the full chunk for an exact url")
    p.add_argument("--corpora", action="store_true", help="list corpora and aliases")
    p.add_argument("--eval", action="store_true", help="run recall@k against gold sets")
    p.add_argument("--corpus", default="all",
                   help="corpus filter: all|modelica|systemmodeler|msl|spec|docs")
    p.add_argument("--k", type=_pos_int, default=5, help="number of results (default 5)")
    p.add_argument("--full", action="store_true", help="print full chunk text")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.corpora:
        return cmd_corpora(args)
    elif args.eval:
        return cmd_eval(args)
    elif args.show:
        return cmd_show(args)
    elif args.query is not None:   # an explicit empty query -> "no matches", not help
        return cmd_query(args)
    else:
        build_parser().print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
