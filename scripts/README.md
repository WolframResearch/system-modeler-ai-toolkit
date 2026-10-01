# Modelica skills — shared scripts

These scripts are shared by the Modelica skills (`validate-modelica`,
`simulate-modelica`, `simulate-and-plot-modelica`, `diagnose-modelica`,
`annotate-modelica-graphics`, `annotate-modelica-plots`, `annotate-control-panel`,
`create-hydraulic-model`, `simulate-modelica-realtime`).
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

**Start from the skill, not from this folder.** These scripts are the parts of a
workflow, not the workflow: the skill that owns a job carries the order to do it
in, the checks that catch a wrong answer, and the modelling guidance that keeps
you from building the wrong thing in the first place. If you reached this file by
listing the scripts directory, invoke the matching skill and follow it —
`validate-modelica` to check a model compiles, `simulate-modelica` to run one,
`diagnose-modelica` for structure or performance, `modelica-model-architecture`
**before** writing a model or library, `annotate-modelica-graphics` for diagrams.

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

- `plot_mat.py`, `check_sanity.py`, `op_report.py`, `mat_summary.py`, `mat_features.py` → `DyMat`, `matplotlib`,
  `numpy`, `scipy`.
- `wsm_realtime.py plot` → `matplotlib`.
- `create-hydraulic-model`'s `Hydraulic.main` → `networkx` (same venv).

To pre-warm or inspect that environment:

```bash
python3 bootstrap_env.py                 # plotting deps; create/reuse the venv and print its python
python3 bootstrap_env.py networkx        # the create-hydraulic-model dep
python3 bootstrap_env.py --print-python  # just print the managed interpreter path
```

That interpreter is also the one to use for **ad-hoc analysis of your own** — a quick
numpy/scipy calculation over a result — instead of the system `python3`, which typically
has none of these packages.

The stdlib-only scripts (`wsm_run.py`, `wsmsim.py`, `report_blocks.py`, `trace_variable.py` and the
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
  only needed for the compiling modes (`simulate`, `diagnose`);
  `validate` just flattens and runs the kernel directly.

### The sampling profiler, per platform

`--mode diagnose --profile` builds the model the way a plain `--mode diagnose`
does, then runs the executable under the host's own sampling profiler instead of
letting the kernel simulate it. The launcher picks the profiler:

| Platform | What it needs |
|----------|---------------|
| Windows | nothing — the profiler is built into the OS |
| macOS | `/usr/bin/sample`, part of macOS; no `sudo` needed for a process the launcher started |
| Linux | `perf` (Debian/Ubuntu: `linux-tools-common linux-tools-$(uname -r)`; Fedora: `perf`), and `kernel.perf_event_paranoid` ≤ 2 |

Override the tool with `--profiler <path>` or `$WSM_PROFILER`. `--mode info`
prints the resolved profiler, or why it is unavailable — check that first if a
profile run fails.

### Usage

```bash
python3 wsm_run.py --mode validate  --model M.mo --name M
python3 wsm_run.py --mode simulate  --model M.mo --name Pkg.M --timeout 180
python3 wsm_run.py --mode validate  --model M.mo --name M --graphics   # also check Icon/Diagram
python3 wsm_run.py --mode validate  --model M.mo --name M --figures    # also check the stored plots
python3 wsm_run.py --mode diagnose  --model M.mo --name M       # adds +g, keeps build artifacts
python3 wsm_run.py --mode diagnose  --model M.mo --name M --profile        # + where the time goes
python3 wsm_run.py --mode diagnose  --name Modelica.Blocks.Examples.PID_Controller  # library class, no --model
python3 wsm_run.py --mode info                                  # print discovered config
python3 wsm_run.py --mode libraries                             # list installed non-MSL libraries
```

(Use `python` instead of `python3` on Windows if that's what's on PATH.)

Key options:

| Option | Purpose |
|--------|---------|
| `--model PATH` / `--name NAME` | the `.mo` file and the model/package name to test. **`--model` is optional** when `--name` is a dotted class already in a loaded library (an MSL example, or one from `--load-library`) -- the launcher then loads only the libraries and works in the current directory |
| `--msl {auto,yes,no}` | load MSL deps; `auto` (default) scans the model for `Modelica.` references, and is always on when there is no `--model` to scan |
| `--msl-version VER` | force an MSL version, e.g. `4.1.0` |
| `--load PATH` | extra `.mo` to load before the model (repeatable; e.g. a library's `package.mo` on disk) |
| `--load-library NAME[==VER]` | locate an **installed** non-MSL library by name and load it before the model (repeatable; e.g. `Hydraulic`). Searches bundled, user-installed and Model-Center custom paths; override with `$WSM_LIBRARY_<NAME>` |
| `--library NAME` / `--library-version VER` | `libraries` mode: resolve just this one library and print its package path |
| `--graphics` | evaluate the graphic annotations (`Icon`, `Diagram`, `Placement`) instead of carrying them along untouched, so an error inside one is reported. The compiling modes also generate the model's diagram view, which evaluates the `DynamicSelect` expressions; the launcher prints a `graphics :` line and exits non-zero if that view was not produced, or if an animated value falls back to its static value |
| `--figures` | also parse the class's `Documentation(figures)` annotation as System Modeler does; the launcher prints a `figures  :` line and exits non-zero, listing each part it would ignore |
| `--tempdir DIR` | working dir (default `<model-dir>/_wsm_<mode>_temp`) |
| `--wsm-home PATH` | install root override |
| `--vsdevcmd PATH` | Windows: path to `VsDevCmd.bat` |
| `--arch ARCH` | Windows VS arch (default `amd64`; or set `$WSM_ARCH`) |
| `--call {instantiate,check,build,sim}` | staged diagnostics entry point (flatten only / flatten + symbolic processing without code generation / flatten + build / full run) |
| `--debug` | diagnose mode: also emit the compiler's per-stage dumps + execution statistics (to localize an opaque/silent crash). Best with `--call build`; redirect the large output to a file |
| `--kernel-arg ARG` | advanced raw kernel flag, repeatable. Diagnostics are handled by the launcher; prefer `--debug` over passing flags here |
| `--timeout SECONDS` | kill the run after this long (default 180) |
| `--no-run` | generate the `.mos` (and `.bat` on Windows) without running |
| `--json` | machine-readable summary on stdout |
| `--quiet` | suppress the kernel's stdout/stderr; print only a one-line outcome (status + integration time + result file) |
| `--report "v1,v2"` | after simulate, print a compact min/max/mean/pp/final table of these variables (runs `mat_summary.py`) |
| `--no-sim` | diagnose mode only: build + keep `+g` artifacts but skip the simulation (fast structural analysis) |
| `--profile` | diagnose mode: after building, run the model under the host's sampling profiler and report which equation blocks the time goes to (builds only, like `--no-sim` — the profiled run replaces the kernel's) |
| `--seconds N` | `--profile`: total sampling budget across however many runs it takes (default 60) |
| `--min-samples N` | `--profile`: re-run the model until this many samples accumulate (default 2000). A fast model needs more runs, not a longer one |
| `--stop-time T` | `--profile`: sample the run out to simulation time T instead of the model's own stop time, without rebuilding — for a model that finishes too fast to sample at all |
| `--profile-result` | `--profile`: write a result file during the profiled run so the cost of writing one is counted. Off by default — the trajectory is the same either way, and a long run would leave a large `.mat` behind |
| `--hz N` / `--top N` | `--profile`: requested sample rate (default 500) and how many equation blocks to list (default 20) |
| `--profiler PATH` | `--profile`: sampling tool override (or set `$WSM_PROFILER`) |

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
| `report_blocks.py` | Full structural report from `*_blockdebug.json` (+ header, res.log) -- `--tempdir DIR` finds all three in a diagnose temp dir instead; `--summary`/`--json` for just the key metrics (states, coupled systems, runtime); `--block SECTION:INDEX` for one block instead — the classes and lines its equations were flattened from, the variables it solves and the equations themselves, which is how a block named by the profile is followed back to the model text |
| `mat_summary.py` | Compact min/max/mean/pp/final table for chosen `.mat` variables, named positionally (`mat_summary.py FILE a b c`) or as `--variables a,b`; `--at T` for the value at one time, `--list`, `--json` (DyMat+numpy) |
| `trace_variable.py` | Walk the dependency chain for one variable |
| `check_events.py` | Zero-crossing / event-structure analysis |
| `check_numerics.py` | Numeric vs analytic Jacobian systems |
| `check_singularity.py` | Structural-singularity / solvability issues |
| `check_tearing.py` | Tearing structure of torn systems: iteration variables and residuals per system, for the `init`, `ode` or `output` section (default: all) |
| `check_sanity.py` | Post-sim red flags: NaN/Inf, never-moving / flatlined signals (DyMat+numpy) |
| `op_report.py` | Operating-point / steady-state report (any domain): per-state settling check + settled values; auto BJT-region add-on (DyMat+numpy) |
| `plot_mat.py` | Plot chosen variables from a `.mat` (reads it with DyMat) |
| `mat_features.py` | Turn features of a `.mat` result (`VAR:max\|min\|at:T\|settle:FRAC\|cross:LEVEL\|final\|initial`) into plot markers for an `annotate-modelica-plots` figures spec; prints them, or adds them to a figure with `--spec FILE --figure ID --plots LIST` (DyMat+numpy) |
| `minimize_mo.py` | Reduce a model that hits a compiler failure to the smallest one that still fails the same way (`--model FILE-or-LIBRARY --name NAME`; `--stage`, `--strict`, `-j`, `--budget`). Works on copies in `_wsm_minimize_temp/`; `best.mo` there is always the smallest model found so far. Drives `wsm_run.py` per candidate |

## Talking to a running simulation

| Script | Purpose |
|--------|---------|
| `wsmsim.py` | Client for the TCP server of a simulation executable: launch one in server mode (interactive copy of its `.sim`, real-time pacing, free port) or attach to one already running; control, input and parameter changes, variable queries, streamed subscriptions. Stdlib-only; imported, not run. |
| `wsm_realtime.py` | Command line on top of it: `info`, `run` (timed input and parameter changes, CSV), `plot` (live curves with sliders; matplotlib), `cmd` (raw protocol commands). |

## Profiling

`wsm_run.py --mode diagnose --profile` is the entry point; these are what it drives.

| Script | Purpose |
|--------|---------|
| `profile_sim.py` | The report: charges every sample to the equation block it was taken in, lists the blocks by share with the variables and components each solves, and rolls that up per component. Falls back to a plain function list when the build artifacts that name the blocks are absent. Run it directly with `--tempdir` to re-run and re-sample a build that is already there, or with `--model`/`--name` to build and profile in one go. Stdlib-only. |
| `blockmap.py` | Maps a sampled generated function back to the equation blocks it evaluates, and through the block-debug JSON to the variables and components solved there. Imported, not run. |
| `sampler_win.py`, `sampler_mac.py`, `sampler_linux.py`, `sampler_common.py` | The per-platform sampling backends and the launch/timing plumbing they share. Not run directly — see the table in "The sampling profiler, per platform" above. |

Because the build is a diagnose build, the generated C++ and the block-debug
JSON sit beside the executable, which is what lets the report name the blocks and
components behind each generated function instead of an opaque generated name.

The profiled run asks for no result file, so it computes the same trajectory
without writing one: the profile measures the model rather than the disk, and a
long run leaves nothing behind. Evaluating the output section is still counted —
that happens at every output point either way — so a dense output interval still
shows up, as extra evaluations of the ODE blocks rather than as I/O.

A sample is charged to the innermost frame on its stack that maps to an equation
block, so the solver and linear-algebra time spent on a block counts towards that
block rather than being reported separately. Where the stack could not be walked
the sample is charged to the block whose own code it landed in; the report's
closing line says how much of the profile that covers.

## Shared library modules (imported; `mo_edit.py` is also runnable)

| Module | Purpose |
|--------|---------|
| `modelica_parser.py` | Span-aware, string/comment-safe parser for `.mo` source: nested classes, declarations, connectors/instances/connects and annotation-presence flags (`has_icon`, `has_diagram`, `has_experiment`, `has_documentation`, `has_figures`). Returns byte spans so callers can splice annotations back in place. Shared by `annotate-modelica-graphics`, `annotate-modelica-plots` and `annotate-control-panel` (each has a `parser.py` shim that re-exports this). `class_statements` and `comment_spans` give the statement structure (sections, `if`/`for`/`when`/`while` blocks with their branches) used by `minimize_mo.py`. Stdlib-only, no import-time side effects. |
| `kernel_failure.py` | Recognises compiler failures (internal errors, generated code that does not compile, simulator internal errors, kernel crashes) in a run's `out.json` and gives each a stable signature. Used by `wsm_run.py` (the `=== compiler failure ===` block and `compiler_failure` in `--json`) and `minimize_mo.py`. |
| `blockdebug.py` | Stdlib-only readers for the diagnostic artifacts: JSON load, section labels, solver-system discovery, Jacobian classification and header / res.log parsing. Imported by `report_blocks.py`, `trace_variable.py`, `blockmap.py` and the `check_*.py` scripts so the parsing lives in one place. |
| `matresult.py` | DyMat/numpy helpers for the `.mat` scripts (load, series, value-at-time, internal-name filter, state detection). Imported only **after** the managed-venv bootstrap, since it needs DyMat+numpy. Used by `mat_summary.py`, `op_report.py`, `check_sanity.py`, `mat_features.py`. |
| `mo_edit.py` | Stdlib-only text-splicing primitives (`Edit`, `splice`, `indent_at`, `balanced_close`, `find_call_open`) shared by the annotation skills' `inject.py`, plus the line-ending handling every `.mo` writer needs (`read_for_edit`, `dominant_eol`, `write_atomic`). Also runnable: `mo_edit.py --eol FILE...` reports `LF` / `CRLF` / `MIXED` / `NONE` and exits non-zero on a mixed file; `--set-eol auto\|lf\|crlf FILE...` rewrites a file to one ending, where `auto` keeps a consistent file's own ending and settles a mixed one on what the enclosing directory-form library uses. Use those around a hand edit, so a model keeps the line endings it arrived with. |

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
touched**. `plot_mat.py`, `check_sanity.py`, `op_report.py`, `mat_summary.py`,
`mat_features.py` pull in `DyMat`/`matplotlib`/`numpy`/`scipy`; `create-hydraulic-model`'s
`Hydraulic.main` pulls in `networkx` — each on first use, into the same venv.
Pre-warm with `python3 bootstrap_env.py` (plotting deps) or
`python3 bootstrap_env.py networkx`.
