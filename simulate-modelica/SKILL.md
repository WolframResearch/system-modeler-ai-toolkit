---
name: simulate-modelica
description: "Simulate Modelica models (.mo files) with WSMKernelX — compiles to C++, builds, and runs the simulation (no plotting; if the user also wants the results plotted, use simulate-and-plot-modelica). Use this skill whenever the user asks to simulate a Modelica model, run a simulation, get simulation results, or wants to see time-domain behavior. Triggers on phrases like 'simulate this model', 'run the simulation', 'get simulation results', or any mention of simulating (without plotting) Modelica code. If the request also involves analysis of the results — checking limits/requirements, violations, parameter sweeps, Monte Carlo, calibration — prefer the wolfram-language-modelica skill when Wolfram Language is available; simulate here and analyze with ad-hoc scripts only when it is not."
---

# Simulate Modelica Model

This skill simulates Modelica models (.mo files) with WSMKernelX: it flattens the model, generates C++ code, compiles it, and runs the simulation. It produces a `.mat` results file.

## Before you run anything

This skill drives WSMKernelX through the shared launcher
`../scripts/wsm_run.py`. **Read [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills)
first** — launcher resolution, the Windows-vs-Unix shell/Python rules, the
temp-dir and cleanup conventions, the JSON-array output gotcha, and the MSL 4.x
dialect notes that every step below assumes.

The launcher works in `_wsm_simulate_temp/` next to the `.mo` file and leaves
`simulate.out.json` and the `.mat` there. Tell the user: "Working in temporary
directory `_wsm_simulate_temp/`. This will be deleted after simulation."

## Workflow

### 1. Identify the model file and name

Identify the `.mo` file and extract the **model name** — see [Appendix → Picking the model name](#picking-the-model-name). For a **directory-form (multi-file) library**, point `--model` at the library folder (not one class file) and pass the full dotted `--name` — see [Appendix → Directory-form (multi-file) libraries](#directory-form-multi-file-libraries).

### 2. Run the simulation

```bash
python3 "<scripts-dir>/wsm_run.py" --mode simulate \
  --model "<path-to-ModelFile.mo>" --name ModelName --timeout 180
```

**Terser loop:** add `--quiet` to print only a one-line outcome (status + integration
time + result file) instead of the full kernel log, and `--report "Vout,x.T"` to print a
compact min/max/mean/pp/final table of those variables straight from the result `.mat` —
so the common "simulate then inspect a few values" step is a single call. (`--report`
runs `mat_summary.py`, which you can also call standalone on any `.mat`.)

The launcher auto-detects MSL usage and loads the right version; force it with
`--msl yes|no` or `--msl-version 4.1.0`. If the model uses an installed non-MSL
library (e.g. `Hydraulic`), add `--load-library <Name>` — see
[Appendix → Using non-MSL libraries](#using-non-msl-libraries-hydraulic-and-other-installed-libraries).
Timeout: allow up to 180 seconds — compilation and simulation of complex models can take time.

Compiling needs a per-OS C++ toolchain (Visual Studio Build Tools / Xcode CLT /
gcc) — the launcher finds it; if it can't, see
[Appendix → When the install or compiler isn't found](#when-the-install-or-compiler-isnt-found).

### 3. Parse the output

WSMKernelX writes structured results to `simulate.out.json` in the temp
directory — a JSON *array*; take the first element. Check **`status.flatten`**,
**`status.build`**, and **`status.result`** in that order; on success
`simulation.resultFile` holds the path to the `.mat` (also printed as a
`SimulationResult` record). Field reference:
[Appendix → Reading the JSON output](#reading-the-json-output).

### 4. Report results

Summarize clearly:
- **Pass**: State the simulation completed successfully. Report key stats from the log (integration time, number of events, number of function evaluations).
- **Build Fail**: The C++ compilation or linking failed. Show the build errors.
- **Flatten Fail**: The model has structural errors. Show the flatten errors.
- **`Fatal error: exception ...(_)` / no out.json**: a normal error (assertion, parameter/init, type, lookup) that escaped catching — not a crash. Read the launcher's `=== actual kernel diagnostic ===` block, which prints the recovered message; don't assume a compiler bug.

**A clean "Pass" does not mean the result is correct.** A model can compile and
simulate with zero errors while being physically wrong (mis-biased circuit with
~0 output, a state pinned at a saturation limit, a node that silently went NaN).
After a successful run, sanity-check the trajectories:

```bash
python3 "<scripts-dir>/check_sanity.py" "<temp-dir>/<Model>.mat"
```

It flags NaN/Inf, variables that never move, and signals that swung then
flatlined (possible saturation / mis-bias). Treat the flags as prompts to
inspect operating points, not as failures. (It self-provisions DyMat/numpy.)

When you simulate a system to settle, get the **operating point** — a domain-neutral
steady-state report that works for thermal, hydraulic, mechanical, electrical, ...
models. It checks each state's derivative to report whether the run reached
equilibrium (and lists states still drifting), then prints the settled values:

```bash
python3 "<scripts-dir>/op_report.py" "<temp-dir>/<Model>.mat" --vars tank.T pump.dp
```

Domain add-ons fire automatically when applicable — e.g. for circuits it also
classifies BJT regions (ACTIVE / SATURATED / CUTOFF from `Vbe`/`Vbc`), catching
mis-bias that no error would report. (Self-provisions DyMat/numpy.)

### 4b. Parameter studies WITHOUT recompiling (`--override` / `--sweep`)

To try different parameter values, do **not** rebuild or hand-write wrapper models.
The launcher builds once and re-runs the compiled executable per value by editing the
`.sim` init file's `value=` attribute:

```bash
# one value set
python3 "<scripts-dir>/wsm_run.py" --mode simulate --model M.mo --name Pkg.M \
  --override "kfb=0.04,I0=45e-6"
# sweep one parameter (one .mat per value), holding others via --override
python3 "<scripts-dir>/wsm_run.py" --mode simulate --model M.mo --name Pkg.M \
  --sweep "I0=12e-6,32.5e-6,90e-6"
```

Each run writes `run_<label>.mat` in the temp dir; plot/compare them directly.
**Caveat (this is enforced):** only parameters with `initType="exact"` in the `.sim`
can be overridden this way. **Structural parameters** (used in array sizes, conditional
components, etc.) are constant-folded into the compiled code — the launcher detects
these from the `.sim` and warns that they need a real rebuild (set them in the model or
build `model X = Pkg.M(param=value)`).

### 5. Clean up

Remove `_wsm_simulate_temp/` entirely — commands per OS: [Appendix → Temporary directories](#temporary-directories).

## Edge cases

- **Packages / name mismatches**: parse the actual `model`/`package` declaration, not the filename — see [Appendix → Picking the model name](#picking-the-model-name).
- **`Unknown library: X` on a multi-file library**: you pointed `--model` at a single class file; point it at the library folder instead — see [Appendix → Directory-form (multi-file) libraries](#directory-form-multi-file-libraries).
- **`Element not found ... in Modelica...`**: the MSL path is wrong — look up the right one with the `search-modelica-docs` skill, don't grep the install tree. See [Appendix → MSL 4.x dialect](#msl-4x-dialect).
- **WSMKernelX or compiler not found**: see [Appendix → When the install or compiler isn't found](#when-the-install-or-compiler-isnt-found).
- **Simulation times out or stalls at initialization**: First distinguish *build* from *solve* — check whether the `.exe` was produced (build done) and whether any result rows were written. If it builds but the solver makes no progress:
  1. Re-run with a short `StopTime` (override the model's `experiment` annotation, or use a small wrapper model) to confirm it integrates *at all* before committing to a long run.
  2. If it stalls at/near `t=0`, suspect a **nonlinear algebraic loop with no dynamic states** — common in high-gain feedback (active circuits, control loops) where every variable is algebraic. Run the `diagnose-modelica` skill, then the `check_singularity.py` / `check_tearing.py` scripts (documented in [`../scripts/README.md`](../scripts/README.md)) — they reveal the offending algebraic systems.
  3. The usual physical fix for active analog circuits is to add the **parasitic dynamic elements** the idealized model omitted (junction/winding capacitances, lead inductances). They turn the stiff algebraic loop into an integrable ODE and bandwidth-limit feedback, which also defines the operating point.
  4. As a numerical lever, loosen tolerance or raise `--timeout`, but prefer fixing the model structure — a model that needs a huge timeout for a short horizon is usually telling you something.

---

## Appendix: shared conventions for the Modelica skills

> *Shared by every Modelica skill that drives WSMKernelX through the
> bundled launcher; inlined here at release time. For the CLI/option
> reference, environment variables (`WSM_HOME`, `WSM_VSDEVCMD`),
> install discovery, and the analysis scripts, see
> [`../scripts/README.md`](../scripts/README.md).*

### Locating the launcher

`<scripts-dir>` (used throughout the skills) is the shared `scripts/` folder.
Some installs symlink the skill directories without it, so resolve it in this
order and use the first that exists:

1. `$WSM_SKILLS_SCRIPTS` (bash) or `$env:WSM_SKILLS_SCRIPTS` (PowerShell), if set.
2. `../scripts` relative to the skill directory — in a normal install
   `../scripts/wsm_run.py` already exists, so use that path directly; **do not run
   a shell probe to "resolve" it.**
3. The repo checkout you installed from, e.g. `.../agentskills/scripts`.
4. Last resort, search the home directory:
   - PowerShell: `Get-ChildItem $HOME -Recurse -Filter wsm_run.py -ErrorAction SilentlyContinue | Select-Object -First 1`
   - bash/zsh: `find ~ -name wsm_run.py -path '*scripts*' 2>/dev/null | head -1`

If only #4 finds it, the install is missing the `scripts/` link — tell the user
to run `install.sh` (or `install.ps1`) from the repo, which links `scripts/` too.

### Shell and Python

**On Windows, use PowerShell.** The Git-Bash/cygwin layer may be broken (even
`ls`/`find` can be absent, giving a misleading "exit 127 / command not found").
Run `wsm_run.py` with `python` (not `python3`); those calls are single-line and
shell-agnostic. For cleanup use `Remove-Item -Recurse -Force`, not `rm -rf`.
On macOS/Linux any POSIX shell is fine and `python3` is the usual name.

### Let the launcher own .mos/.bat and paths

Do **not** hand-write `.mos` scripts, `.bat` files, or hardcode install/compiler
paths. The bundled `scripts/wsm_run.py` handles every OS difference — it finds
the System Modeler install and kernel binary (macOS / Windows / Linux), finds and
loads the right MSL files, generates the `.mos`, and runs the kernel with a
working compiler environment per platform (system clang/gcc on macOS/Linux; the
Visual Studio dev environment via `VsDevCmd.bat` on Windows).
See [`../scripts/README.md`](../scripts/README.md) for `WSM_HOME`, the Windows compiler prerequisites,
and the full option table.

### When the install or compiler isn't found

The launcher searches each OS's standard install locations. If it prints
`ERROR: Could not locate a Wolfram System Modeler installation`, the install
is in a non-standard place — ask the user for it and re-run with
`--wsm-home "<path>"` (or have them set `WSM_HOME`).

Building and simulating also need a C++ toolchain:

- **Windows**: Visual Studio Build Tools. The launcher locates `VsDevCmd.bat`
  itself; if it reports the compiler environment is missing, pass
  `--vsdevcmd "<path-to-VsDevCmd.bat>"` (or set `WSM_VSDEVCMD`) and make sure
  Build Tools are installed.
- **macOS**: the Xcode command-line tools (`xcode-select --install`).
- **Linux**: gcc/g++.

Run `python3 "<scripts-dir>/wsm_run.py" --mode info` to see what the launcher
discovered.

### Temporary directories

The launcher works in a `_wsm_<mode>_temp/` directory next to the `.mo` file
(`_wsm_validate_temp/`, `_wsm_simulate_temp/`, `_wsm_diagnose_temp/`) and leaves
its outputs there. Tell the user, e.g.: "Working in temporary directory
`_wsm_<mode>_temp/`. This will be deleted afterwards." Pass `--tempdir`
to reuse one directory across models in a session.

Clean up by removing the whole directory — use the user's shell:

```bash
rm -rf "<model-dir>/_wsm_<mode>_temp"          # macOS / Linux
# PowerShell: Remove-Item -Recurse -Force "<model-dir>\_wsm_<mode>_temp"
```

### Picking the model name

- The user may provide a path to a `.mo` file, or you may already be working with
  one in context.
- Extract the **model name**: the identifier after `model` on the first non-comment
  line, e.g. `model FooBar` → `FooBar`. The filename does not always match the
  model name — parse the actual `model`/`package` declaration.
- For packages or nested models, use the **top-level** model name.
- **Pick an instantiable model, not a package**, for any kernel call. A `package`
  cannot be validated or simulated ("Invalid instantiation … is a package") — use
  a nested model's full dotted name, e.g. `Package.Model`.
- Pass an **absolute path** to `--model` (relative paths break as the working
  directory shifts between calls).

### Directory-form (multi-file) libraries

A directory-form library stores one class per file with a `package.mo` at each
level. You **cannot** validate such a class by handing the launcher only its own
`.mo` file — the class's `within Lib;` clause needs the whole package loaded, and
loading the single file alone fails with
`Internal error: ... expandLibNode: Unknown library: Lib`. Instead point
`--model` at the **library folder** (or its top `package.mo`, or any class file
inside it) and pass the **full dotted class name** via `--name`:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate \
  --model "/abs/path/InvertedPendulum" \
  --name InvertedPendulum.Controller
```

The launcher resolves any of those forms up to the library's root `package.mo`
and loads the entire package (following `package.order`) before instantiating
`--name`. It prints a `NOTE:` telling you which `package.mo` it loaded. Do **not**
try to work around the unknown-library error by `--load`-ing individual files.

### Reading the JSON output

The kernel writes `<mode>.out.json` into the temp dir. **It is a JSON *array* —
take the first element**, then read:

- **`status.flatten`**: `"Pass"` / `"Fail"` (the primary result for `validate`).
- **`status.build`**: `"Pass"` / `"Fail"` — C++ compilation/linking (`simulate`).
- **`status.result`**: simulation result status (`simulate`).
- **`messages.errors`** / **`messages.warnings`** / **`messages.notifications`**:
  arrays (empty if none).
- **`flat_model`** (`validate`) / **`simulation.resultFile`** (`simulate`): the
  flattened class / path to the `.mat`.

See [`../scripts/README.md`](../scripts/README.md) (`wsm_run.py` section) for the full field reference.

### MSL 4.x dialect

This toolchain ships **MSL 4.x**. When authoring models, use the 4.x names — the
3.2 names flatten with confusing "not found" errors:

- units: `Modelica.Units.SI.*` (not `Modelica.SIunits.*`)
- source frequency parameter: `f` (not `freqHz`), e.g. `SineVoltage(V=.., f=..)`
- declare the dependency as `annotation(uses(Modelica(version="4.0.0")))`

Run `python3 "<scripts-dir>/wsm_run.py" --mode info` to confirm the exact MSL
version. `wsm_run.py` also warns on stderr if it spots a 3.2 name in the model.

**When a flatten fails with `Element not found ... in Modelica...`**, the MSL
component path is wrong (a misremembered name, not a missing install). Resolve
the correct path with the **search-modelica-docs** skill — e.g. sine is
`Modelica.Blocks.Sources.Sine` (not `Math.Sine`), difference is `Math.Feedback`
(not `Math.Subtract`), and saturation is `Nonlinear.Limiter` (not
`Nonlinear.Saturation`). **Do not** grep or walk the System Modeler install tree
to hunt for the class.

### Using non-MSL libraries (Hydraulic, and other installed libraries)

MSL is automatic (`--msl`). For **any other** library a model uses — Hydraulic, or
anything the user installed from the Library Store — the launcher can find it for you.
Two steps, no guessing at paths:

1. **See what is installed** (bundled with System Modeler, user-installed archives, and
   any custom folders configured in Model Center):

   ```bash
   python3 "<scripts-dir>/wsm_run.py" --mode libraries
   # add --json for a machine-readable array; each row has name/version/source/package
   ```

   To get just one library's package path (e.g. for a manual `--load`):
   `--mode libraries --library Hydraulic` (add `--library-version 2.1` to pin a version).

2. **Load it into a build** by name — add `--load-library <Name>` to a validate /
   simulate / diagnose run (repeatable; pin a version with `Name==Ver`):

   ```bash
   python3 "<scripts-dir>/wsm_run.py" --mode validate \
     --model "<path>/M.mo" --name M --load-library Hydraulic
   ```

   The launcher resolves the library (bundled → user-installed → Model-Center custom
   path, newest version wins) and `loadFile`s it before the model. A library usually
   pulls in MSL, so keep MSL on (auto, or `--msl yes`). Override a lookup with
   `$WSM_LIBRARY_<NAME>` (e.g. `WSM_LIBRARY_HYDRAULIC=/path/to/package.moe`), or fall
   back to an explicit `--load <path-to-package.mo|.moe>`.
