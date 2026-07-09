# Modelica skills — shared scripts

These scripts are shared by the Modelica skills (`validate-modelica`,
`simulate-modelica`, `simulate-and-plot-modelica`, `diagnose-modelica`,
`annotate-modelica-graphics`, `annotate-modelica-plots`, `annotate-control-panel`,
`create-hydraulic-model`).
They are cross-platform: they run on **macOS, Windows, and Linux** with no edits.

The skills refer to this folder as `<scripts-dir>`. If a skill is installed such
that this folder is a sibling of the skill directory, it is reachable as
`../scripts/` from the skill.

**Make sure `scripts/` is installed alongside the skills.** A common failure is
to symlink only the per-skill directories into `~/.claude/skills/` and leave
`scripts/` behind — then `../scripts/wsm_run.py` dangles and every skill breaks.
Use the repo's `install.sh` / `install.ps1`, which link **both** the skill dirs
and `scripts/`. To point a skill at the scripts folder explicitly (e.g. for a
non-standard layout), set `$WSM_SKILLS_SCRIPTS` to its absolute path.

This README is the **tool/CLI reference** (options, env vars, the analysis
scripts). For the cross-cutting **agent operating conventions** the skills share
— launcher resolution, shell/Python rules, temp-dir conventions, model-name
picking, JSON-output parsing and the MSL 4.x dialect — see
the "Appendix: shared conventions for the Modelica skills" section at the end of each skill's `SKILL.md`.

### Python environment (managed venv)

Some scripts need third-party packages that are usually absent from whatever `python3` an agent
invokes — and a bare `pip install` fails on PEP 668 "externally-managed" interpreters (and
pollutes the rest). These scripts **self-provision**: on first use they create a managed venv
(default `~/.cache/wsm-skills/venv`, override with `$WSM_SKILLS_VENV`), install the deps **there**,
and re-exec under it — **system Python is never modified**.

- `plot_mat.py`, `check_sanity.py`, `op_report.py`, `mat_summary.py` → `DyMat`, `matplotlib`,
  `numpy`, `scipy`.
- `create-hydraulic-model`'s `Hydraulic.main` → `networkx` (same venv).

To pre-warm or inspect that environment:

```bash
python3 bootstrap_env.py                 # plotting deps; create/reuse the venv and print its python
python3 bootstrap_env.py networkx        # the create-hydraulic-model dep
python3 bootstrap_env.py --print-python  # just print the managed interpreter path
```

The stdlib-only scripts (`wsm_run.py`, `report_blocks.py`, `trace_variable.py` and the
`check_*.py` scripts except `check_sanity.py`) need no venv.

## `wsm_run.py` — the WSMKernelX launcher

This is the single place where all OS-specific knowledge lives. It discovers the
Wolfram System Modeler installation, the `WSMKernelX` binary and the Modelica
Standard Library (MSL) files; generates the `.mos` test script; and runs the
kernel with a working C/C++ compiler on each platform. The skills call it instead
of hand-writing `.mos`/`.bat` files with hardcoded paths.

### Install discovery

The install root is resolved in this order:

1. `--wsm-home <path>` argument
2. `$WSM_HOME` or `$SYSTEMMODELER_HOME` environment variable
3. per-OS default search globs (newest version wins):
   - **macOS:** `/Applications/SystemModeler*.app/Contents`, `/Applications/Wolfram System Modeler*.app/Contents`
   - **Windows:** `%ProgramFiles%\Wolfram Research\System Modeler *`, plus the x86 and W6432 variants
   - **Linux:** `/usr/local/Wolfram/SystemModeler/*`, `/opt/Wolfram/SystemModeler/*`, `~/Wolfram/SystemModeler/*`

The kernel binary inside the root is `MacOS/WSMKernelX` (macOS), `bin/WSMKernelX.exe`
(Windows) or `bin/WSMKernelX` (Linux). MSL is taken from `L/Modelica <ver>/…`
(newest 4.x by default; override with `--msl-version`).

Check what it found at any time:

```bash
python3 wsm_run.py --mode info
```

### The compiler, per platform

- **macOS / Linux:** the kernel uses the system C/C++ toolchain on PATH. No setup
  file is needed — ensure Xcode command-line tools (`xcode-select --install`) on
  macOS or `gcc`/`g++` on Linux.
- **Windows:** the kernel needs the Visual Studio compiler environment. The
  launcher locates `VsDevCmd.bat` (newest Visual Studio / Build Tools under
  Program Files) and runs the kernel through it, with the compiler and code
  generator set to a matching target automatically. Point it at a specific
  install with `--vsdevcmd <path>` or `$WSM_VSDEVCMD` if it isn't found. This is
  only needed for the compiling modes (`simulate`, `diagnose`); `validate` just
  flattens and runs the kernel directly.

### Usage

```bash
python3 wsm_run.py --mode validate  --model M.mo --name M
python3 wsm_run.py --mode simulate  --model M.mo --name Pkg.M --timeout 180
python3 wsm_run.py --mode diagnose  --model M.mo --name M       # adds +g, keeps build artifacts
python3 wsm_run.py --mode info                                  # print discovered config
python3 wsm_run.py --mode libraries                             # list installed non-MSL libraries
```

(Use `python` instead of `python3` on Windows if that's what's on PATH.)

Key options:

| Option | Purpose |
|--------|---------|
| `--model PATH` / `--name NAME` | the `.mo` file and the model/package name to test |
| `--msl {auto,yes,no}` | load MSL deps; `auto` (default) scans the model for `Modelica.` references |
| `--msl-version VER` | force an MSL version, e.g. `4.1.0` |
| `--load PATH` | extra `.mo` to load before the model (repeatable; e.g. a library's `package.mo` on disk) |
| `--load-library NAME[==VER]` | locate an **installed** non-MSL library by name and load it before the model (repeatable; e.g. `Hydraulic`). Searches bundled, user-installed and Model-Center custom paths; override with `$WSM_LIBRARY_<NAME>` |
| `--library NAME` / `--library-version VER` | `libraries` mode: resolve just this one library and print its package path |
| `--tempdir DIR` | working dir (default `<model-dir>/_wsm_<mode>_temp`) |
| `--wsm-home PATH` | install root override |
| `--vsdevcmd PATH` | Windows: path to `VsDevCmd.bat` |
| `--arch ARCH` | Windows VS arch (default `amd64`; or set `$WSM_ARCH`) |
| `--call {instantiate,build,sim}` | staged diagnostics entry point (flatten only / flatten + build / full run) |
| `--debug` | diagnose mode: also emit the compiler's per-stage dumps + execution statistics (to localize an opaque/silent crash). Best with `--call build`; redirect the large output to a file |
| `--kernel-arg ARG` | advanced raw kernel flag, repeatable. Diagnostics are handled by the launcher; prefer `--debug` over passing flags here |
| `--timeout SECONDS` | kill the run after this long (default 180) |
| `--no-run` | generate the `.mos` (and `.bat` on Windows) without running |
| `--json` | machine-readable summary on stdout |
| `--quiet` | suppress the kernel's stdout/stderr; print only a one-line outcome (status + integration time + result file) |
| `--report "v1,v2"` | after simulate, print a compact min/max/mean/pp/final table of these variables (runs `mat_summary.py`) |
| `--no-sim` | diagnose mode only: build + keep `+g` artifacts but skip the simulation (fast structural analysis) |

On success the kernel writes `<mode>.out.json` into the temp dir (a JSON **array**
— take the first element). The launcher forwards the kernel's stdout/stderr and
prints a short summary with the temp dir, the `out.json` path and the resolved
kernel/MSL versions.

## Analysis scripts (already cross-platform)

These take file paths as arguments and use only standard cross-platform Python
libraries (`json`, `argparse`, `numpy`, `matplotlib`, `DyMat`). Nothing in them
is OS-specific.

| Script | Purpose |
|--------|---------|
| `report_blocks.py` | Full structural report from `*_blockdebug.json` (+ header, res.log); `--summary`/`--json` for just the key metrics (states, coupled systems, runtime) |
| `mat_summary.py` | Compact min/max/mean/pp/final table for chosen `.mat` variables; `--at T`, `--list`, `--json` (DyMat+numpy) |
| `trace_variable.py` | Walk the dependency chain for one variable |
| `check_events.py` | Zero-crossing / event-structure analysis |
| `check_numerics.py` | Numeric vs analytic Jacobian systems |
| `check_singularity.py` | Structural-singularity / solvability issues |
| `check_tearing.py` | Tearing structure of torn systems |
| `check_sanity.py` | Post-sim red flags: NaN/Inf, never-moving / flatlined signals (DyMat+numpy) |
| `op_report.py` | Operating-point / steady-state report (any domain): per-state settling check + settled values; auto BJT-region add-on (DyMat+numpy) |
| `plot_mat.py` | Plot chosen variables from a `.mat` (reads it with DyMat) |

## Shared library modules (imported, not run)

| Module | Purpose |
|--------|---------|
| `modelica_parser.py` | Span-aware, string/comment-safe parser for `.mo` source: nested classes, declarations, connectors/instances/connects and annotation-presence flags (`has_icon`, `has_diagram`, `has_experiment`, `has_documentation`, `has_figures`). Returns byte spans so callers can splice annotations back in place. Shared by `annotate-modelica-graphics`, `annotate-modelica-plots` and `annotate-control-panel` (each has a `parser.py` shim that re-exports this). Stdlib-only, no import-time side effects. |
| `blockdebug.py` | Stdlib-only readers for the diagnostic artifacts: JSON load, section labels, solver-system discovery, Jacobian classification and header / res.log parsing. Imported by `report_blocks.py`, `trace_variable.py` and the `check_*.py` scripts so the parsing lives in one place. |
| `matresult.py` | DyMat/numpy helpers for the `.mat` scripts (load, series, value-at-time, internal-name filter, state detection). Imported only **after** the managed-venv bootstrap, since it needs DyMat+numpy. Used by `mat_summary.py`, `op_report.py`, `check_sanity.py`. |
| `mo_edit.py` | Stdlib-only text-splicing primitives (`Edit`, `splice`, `indent_at`, `balanced_close`, `find_call_open`) shared by the annotation skills' `inject.py`. |

### Parameter studies without recompiling (`wsm_run.py --override` / `--sweep`)

`wsm_run.py` can re-run a compiled model with new parameter values **without a
rebuild**, by editing the `value=` attribute of the `.sim` init file (the runtime
reads `value` for parameters whose `initType="exact"`):

```bash
python3 wsm_run.py --mode simulate --model M.mo --name Pkg.M --override "kfb=0.04,I0=45e-6"
python3 wsm_run.py --mode simulate --model M.mo --name Pkg.M --sweep "I0=12e-6,32e-6,90e-6"
```

It builds once and writes one `run_<label>.mat` per value. **Structural parameters**
(constant-folded into the compiled code or `initType != exact`) can't be changed this
way — the launcher detects them from the `.sim` and warns that they need a real rebuild.

## Python dependencies

`wsm_run.py`, `report_blocks.py`, `trace_variable.py` and the `check_*.py`
scripts (except `check_sanity.py`) use only the Python standard library.

The scripts that need third-party packages **self-provision the managed venv**
described above — there is **no manual `pip install`, and system Python is never
touched**. `plot_mat.py`, `check_sanity.py`, `op_report.py`, `mat_summary.py`
pull in `DyMat`/`matplotlib`/`numpy`/`scipy`; `create-hydraulic-model`'s
`Hydraulic.main` pulls in `networkx` — each on first use, into the same venv.
Pre-warm with `python3 bootstrap_env.py` (plotting deps) or
`python3 bootstrap_env.py networkx`.
