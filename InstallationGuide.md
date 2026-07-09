# Installation Guide (for the LLM agent)

**You are an LLM agent with CLI access. The user has given you this folder and
asked you to install these skills. Follow this guide to set them up, then tell
the user they're ready and suggest a test.**

This bundle is a set of **agent skills** for Wolfram System Modeler and Modelica.
Each skill is a plain-Markdown `SKILL.md` (instructions for you) plus, for most,
standalone Python tools. Nothing is tied to a specific agent framework — the
skills are just instructions + command-line tools, so any agent that can read a
file and run shell commands can use them.

---

## Step 1 — Keep the folder layout intact

Do **not** move individual skill folders apart. The Modelica skills reference the
shared launcher as `../scripts/wsm_run.py`, so `scripts/` must stay a **sibling**
of the skill directories. Install/copy the whole folder as a unit.

## Step 2 — Check Python 3

Every skill that ships tools needs **Python 3.7+**. Check it:

```bash
python3 --version    # or: python --version   (Windows often uses `python`)
```

If Python 3 is missing, tell the user and install it (or ask them to), e.g.
`winget install Python.Python.3` on Windows, `brew install python` on macOS,
or the distro package manager on Linux.

> **Shell — on Windows, use PowerShell.** Run all of this guide's commands (and the
> skill commands) in **PowerShell**, not Git Bash. The Git-Bash/cygwin layer is
> often broken on Windows — even `ls`/`find` can be missing, producing a misleading
> `exit code 127 / command not found` that looks like a real failure. In PowerShell,
> use `python` (not `python3`), and for cleanup use `Remove-Item -Recurse -Force`
> instead of `rm -rf`. The `wsm_run.py` invocations themselves are single-line and
> shell-agnostic, so they run as-is. (macOS/Linux: any POSIX shell is fine.)

## Step 3 — Make the skills available to your agent

**If you are Claude Code:** run the installer to link the skills into the user's
skills directory (`~/.claude/skills`). Linking (not copying) means repo edits
show up live.

```bash
# macOS / Linux
./install.sh                 # symlink into ~/.claude/skills
./install.sh --copy          # copy instead of symlink

# Windows (PowerShell)
./install.ps1                # junction into %USERPROFILE%\.claude\skills
./install.ps1 -Copy
```

Both installers link **all skill directories plus `scripts/`** together (linking
the skills without `scripts/` is the #1 cause of "wsm_run.py not found").
Skills are picked up at session start, so tell the user to **start a new
session** afterwards and ask Claude to list its skills —
`modelica-model-architecture`, `validate-modelica` and the others should appear.

**If you are a different agent (Codex, Cursor, Aider, etc.):** there is no skill
auto-discovery. Either (a) add a short pointer to each skill in the agent's
standing-instructions file (e.g. `AGENTS.md` for Codex, `.cursor/rules` for
Cursor) naming the skill and its `SKILL.md` path, or (b) simply read the relevant
`SKILL.md` on demand when a matching request comes in. The skills run as plain
CLI tools either way — nothing about them is Claude-specific.

## Step 4 — Make sure the requirements are present (only what's needed)

Not every skill needs everything. Two things you should **not** worry about
installing by hand:

- **Python third-party packages auto-provision.** The scripts that need them
  build a **managed virtual environment** on first use (`scripts/_env.py`) in
  `~/.cache/wsm-skills/venv` (override with `$WSM_SKILLS_VENV`) — they never touch
  the system Python. `simulate-and-plot-modelica` / the analysis scripts install
  `DyMat`, `matplotlib`, `numpy`, `scipy`; `create-hydraulic-model` installs
  `networkx`. **Note:** this happens automatically the first time one of those
  skills runs and **downloads the latest versions from PyPI** (so that first run
  needs network access; the packages are not version-pinned). You can pre-warm
  it, but don't `pip install` globally:
  ```bash
  python3 scripts/bootstrap_env.py            # plotting/analysis deps (DyMat, matplotlib, numpy, scipy)
  python3 scripts/bootstrap_env.py networkx   # create-hydraulic-model dep
  ```
- **Several skills need nothing extra.** `search-modelica-docs` is pure stdlib and
  fully offline. `wsm_run.py`, `report_blocks.py`, `trace_variable.py`, the
  `check_*.py` scripts (except `check_sanity.py`) and the annotation skills
  (`annotate-modelica-*`, `annotate-control-panel`) use only the Python standard
  library — no venv.

What you **do** need to check for, by skill:

| Requirement | Needed by | How to get it |
|---|---|---|
| **Wolfram System Modeler** | `validate-modelica`, `simulate-*`, `diagnose-modelica`, the `annotate-*` skills (validation gate) | install System Modeler; the launcher auto-discovers it (override with `WSM_HOME` / `--wsm-home`) |
| **C/C++ compiler** | the *compiling* skills (`simulate-*`, `diagnose-modelica`); also `validate-modelica` for models that use external functions | Windows: VS Build Tools; macOS: `xcode-select --install`; Linux: `gcc`/`g++` |
| **Wolfram Language** (Mathematica / Wolfram Engine) | `wolfram-language-modelica` (and optional diagram rendering in `annotate-modelica-graphics`) | install Mathematica or the free Wolfram Engine; `wolfram-language-modelica` also needs the [Wolfram MCP server](https://www.wolfram.com/artificial-intelligence/mcp/local/) connected — its SKILL.md's Prerequisites section covers the setup |

`validate-modelica` only flattens, so it **usually** needs no compiler — but some
models still do (e.g. when the frontend has to evaluate an external C/Fortran
function during instantiation), so a compiler is recommended if you'll validate
models that use external functions. `search-modelica-docs` needs neither System
Modeler nor any package at all.

Check what's missing for the user's intended skills, then verify.

## Step 5 — Verify

```bash
# Did the launcher find System Modeler? (for the Modelica toolchain skills)
python3 scripts/wsm_run.py --mode info

# Is the offline doc-search skill working? (no dependencies needed)
cd search-modelica-docs && python3 -m docsearch.main --corpora
```

If both report sensibly, the install is good. Tell the user and suggest a test
(see the example prompts at the end of the README's "Get started" section).

---

## Reference

### Skills

| Skill | What it does |
|-------|--------------|
| [`modelica-model-architecture`](modelica-model-architecture/SKILL.md) | Architecture/structuring guidance and library conventions to apply before writing equations (decomposition, connectors, reuse, file layout, units, naming, documentation) |
| [`validate-modelica`](validate-modelica/SKILL.md) | Flatten a `.mo` file with `WSMKernelX` and report structural errors |
| [`simulate-modelica`](simulate-modelica/SKILL.md) | Compile + run a simulation, report pass/fail and stats |
| [`simulate-and-plot-modelica`](simulate-and-plot-modelica/SKILL.md) | Simulate, then plot chosen variables with DyMat |
| [`diagnose-modelica`](diagnose-modelica/SKILL.md) | Deep structural/equation/performance report (variables, blocks, tearing, events, runtime) |
| [`create-hydraulic-model`](create-hydraulic-model/SKILL.md) | Build a hydraulic circuit model, guided by a bundled knowledge graph of the Hydraulic library |
| [`search-modelica-docs`](search-modelica-docs/SKILL.md) | Offline BM25 search over bundled Modelica + System Modeler docs; returns passages with citation URLs |
| [`wolfram-language-modelica`](wolfram-language-modelica/SKILL.md) | Drive simulation from Wolfram Language (sweeps, calibration, requirement validation, ML on simulated data) |
| [`annotate-modelica-graphics`](annotate-modelica-graphics/SKILL.md) | Add Icon + Diagram annotations so a text-only model renders as a schematic |
| [`annotate-modelica-plots`](annotate-modelica-plots/SKILL.md) | Add standardized result-plot annotations (`Documentation(figures=…)`) so a model stores its own simulation plots |
| [`annotate-control-panel`](annotate-control-panel/SKILL.md) | Add control-panel (Explore) annotations so a model opens with interactive sliders, checkboxes and menus in Simulation Center |
| [`annotate-modelica-animation`](annotate-modelica-animation/SKILL.md) | Add 3D-animation annotations (stored cameras, trace paths, playback settings) so a MultiBody model opens with a ready-made animation |

### Layout

```
agentskills/
├── README.md                       ← short human quick-start
├── InstallationGuide.md            ← you are here (agent-facing install steps)
├── install.sh / install.ps1        ← link the skills into Claude Code
├── scripts/                        ← shared tooling; MUST stay a sibling of the skills
│   ├── wsm_run.py                  ← cross-platform WSMKernelX launcher
│   ├── modelica_parser.py          ← shared .mo parser (annotation skills)
│   ├── _env.py / bootstrap_env.py  ← managed-venv self-provisioning
│   └── … report_blocks / trace_variable / check_* / plot_mat …
├── modelica-model-architecture/SKILL.md
├── validate-modelica/SKILL.md
├── simulate-modelica/SKILL.md
├── simulate-and-plot-modelica/SKILL.md
├── diagnose-modelica/SKILL.md
├── wolfram-language-modelica/SKILL.md
├── create-hydraulic-model/         ← SKILL.md + self-contained GraphRAG (Hydraulic/)
├── search-modelica-docs/           ← SKILL.md + self-contained BM25 search (docsearch/)
├── annotate-modelica-graphics/     ← SKILL.md + self-contained annotator (Schematic/)
├── annotate-modelica-plots/        ← SKILL.md + self-contained plot annotator (PlotAnnotate/)
├── annotate-control-panel/         ← SKILL.md + self-contained panel annotator (ControlPanel/)
└── annotate-modelica-animation/SKILL.md
```

### Notes

- **Cross-platform** (macOS, Windows, Linux): OS- and compiler-specific knowledge
  lives in `scripts/wsm_run.py`, so the skills contain no hardcoded paths.
- **`create-hydraulic-model`** and **`search-modelica-docs`** are self-contained:
  their data ships inside the skill and is queried offline (no Modelica library,
  no re-parsing, no network).
- **Temporary working directories.** The Modelica skills work in `_wsm_*_temp/`
  next to the model and clean up afterward; kept plots go in `_comparison_plots/`.
