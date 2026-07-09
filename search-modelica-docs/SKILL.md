---
name: search-modelica-docs
description: "Search the bundled Modelica and Wolfram System Modeler documentation for authoritative answers, then cite the source. Use this skill whenever the user asks a how-to, what-is, or why question about the Modelica language (syntax, semantics, equations, when/if, arrays, connectors, annotations, the language specification), about Wolfram System Modeler (the tool: building/simulating models, the GUI, tutorials, release/what's-new notes), OR about the Modelica Standard Library (which MSL component/block to use, its exact parameter names and defaults, example models). Triggers on phrases like 'how do I write a when statement', 'what does the Modelica spec say about ...', 'how do I simulate this in System Modeler', 'is this valid Modelica', 'which MSL block does ...', 'what are the parameters of Modelica.X.Y', 'find an example model that ...', 'look it up in the docs'. Also use it while WRITING a model that uses MSL components, to ground parameter names and wiring instead of recalling them. Prefer this over answering Modelica/System Modeler/MSL questions from memory."
---

# Search Modelica & System Modeler Documentation (BM25)

A self-contained, **offline** documentation search. It ranks passages with BM25
(pure Python standard library — **no third-party packages, no network, no API**)
over three prebuilt corpora and returns the matching chunks with their citation
URLs. Use it to ground answers in real documentation instead of recalling from
memory.

## The three corpora (and how to route)

The content covers the Modelica *language*, the System Modeler *tool*, and the
*Modelica Standard Library* — pick the corpus by what the user means:

| `--corpus` value | Covers | Backing corpora |
|---|---|---|
| `modelica` | The **Modelica language** — syntax, semantics, the normative specification | `spec` |
| `systemmodeler` (or `sm`) | **Wolfram System Modeler**, the tool — building/simulating models, GUI, tutorials, what's-new | `docs` |
| `msl` (or `library`) | The **Modelica Standard Library** — component/block docs, exact parameter names, example models, annotation-stripped source | `msl` |
| `all` (default) | Everything | `spec` + `docs` + `msl` |
| `spec` | *Modelica Language Specification* (normative) | `spec` |
| `docs` | System Modeler documentation | `docs` |

Routing guidance:
- Language questions ("how does `when` work", "is this valid Modelica", "what's
  the rule for...") → `--corpus modelica`.
- Tool questions ("how do I simulate / plot / use the GUI in System Modeler",
  "what's new in 15") → `--corpus systemmodeler`.
- Library questions ("which block gives me an anti-windup PID", "what are the
  parameters of `Inertia`", "show an example wiring a spring-damper") →
  `--corpus msl`. Also use this while *writing* a model with MSL components to
  confirm parameter names and `connect()` patterns.
- **When unsure, use `all`** (the default) — a question often spans corpora, and
  the results are tagged so you can see where each came from. But `msl` is by
  far the largest corpus (~4,700 chunks vs ~900 for the other two), so if you
  know the question is about the language or the tool, route to that corpus —
  it keeps library chunks from crowding out the answer.

## Requirements

Python 3 only. **No `pip install` needed** — the index uses just the standard
library and the prebuilt JSON data ships inside this skill (`docsearch/data/`).
Run commands from **this skill's own directory** (the folder containing this
`SKILL.md`) so the `docsearch` package imports. Use `python` instead of
`python3` on Windows if that's what's on PATH.

## Commands

```bash
cd "<skill-dir>"     # the folder containing this SKILL.md

# Search (default k=5). Route with --corpus.
python -m docsearch.main --query "how do I write a when statement" --corpus modelica
python -m docsearch.main --query "simulate a fluid tank" --corpus systemmodeler --k 8
python -m docsearch.main --query "anti-windup PID controller output limits" --corpus msl

# Read the FULL text of a specific result (paste its exact url).
python -m docsearch.main --show "https://specification.modelica.org/maint/3.6/statements-and-algorithm-sections.html#4gfvu7z5m8rutn1wqr3gsd7mr"
python -m docsearch.main --show "modelica://Modelica.Blocks/LimPID"

# Machine-readable output for programmatic use.
python -m docsearch.main --query "array construction" --json

# List corpora + aliases / counts.
python -m docsearch.main --corpora

# (Maintainer, repo checkout only) measure retrieval quality against the gold sets.
python -m docsearch.main --eval --k 5
```

Flags: `--corpus` (route, default `all`), `--k` (results, default 5), `--full`
(print whole chunks instead of 600-char previews), `--json`, `--show <url>`.

## Workflow

1. **Route.** Decide `modelica` vs `systemmodeler` vs `all` from the question
   (see the table). Default to `all` if it could be either.
2. **Search.** Run `--query` with the user's question. BM25 is lexical, so if the
   first try is weak, **reformulate with domain keywords** (e.g. add `when clause
   discrete event`, `connector flow potential`, `algorithm section`) and search
   again, and/or raise `--k`. A second targeted query usually finds it.
3. **Read.** The preview is the first 600 chars. To quote or reason carefully,
   pull the full passage with `--show <url>` (or re-run with `--full`).
4. **Answer and cite.** Base the answer on the retrieved text and **cite the
   source URL(s)** so the user can verify. Each result is tagged with its corpus;
   follow the citation guidance the tool prints at the top of search results:
   - **Specification (`spec`)** text is *authoritative/normative*. Text in
     brackets `[...]` is **non-normative** (explanatory only) — don't present it
     as a rule. When the answer quotes or is derived from spec excerpts, end it
     with this attribution: *Derived from the Modelica® Language Specification.
     Copyright © Modelica Association. Used under CC BY-SA 4.0.*
   - **System Modeler docs (`docs`)** are tutorials / user guide / release notes,
     © Wolfram Research — cite the `reference.wolfram.com` source URL.
   - **MSL reference (`msl`)** entries are class docs plus annotation-stripped
     MSL 4.0 source. The code is authoritative for parameter names, defaults,
     and `connect()` wiring. Entries are keyed by *leaf* class name as
     `modelica://<TopPackage>/<Name>` pseudo-URLs — cite the class name (e.g.
     `Modelica.Blocks.Continuous.LimPID` if the doc text gives the full path),
     not the pseudo-URL, since it is not a resolvable link.
5. If nothing relevant comes back after reformulating, say so rather than
   inventing an answer — that is the whole point of this skill.

## Notes

- Retrieval is deterministic and local; identical queries return identical
  results. There is no learning or external call.
- The `--eval` gold sets (`docsearch/data/eval/*.jsonl`) are query→URL
  pairs used only to measure recall@k / MRR when tuning; normal use never reads
  them, and they are not shipped in the release bundle (repo checkout only).
