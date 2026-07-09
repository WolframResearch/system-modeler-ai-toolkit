---
name: diagnose-modelica
description: "Diagnose Modelica models (.mo files) by generating a detailed structural and simulation report. Use this skill whenever the user asks to diagnose, analyze, profile, or debug a Modelica model's structure, equations, variables, or performance. Triggers on phrases like 'diagnose this model', 'analyze the model structure', 'show me the equation blocks', 'how many states does this model have', 'why is this model slow', 'debug this model', 'model report', or any request to understand the internals of a Modelica model."
---

# Diagnose Modelica Model

This skill generates a comprehensive diagnostic report for a Modelica model. You
run the model through the bundled launcher, then turn the artifacts it leaves
behind into a report with the bundled `report_blocks.py` / `trace_variable.py`
scripts. The report covers variable counts, equation structure, block analysis,
solver settings, and (if simulated) runtime performance.

## Before you run anything

This skill drives WSMKernelX through the shared launcher
`../scripts/wsm_run.py`. **Read [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills)
first** — launcher resolution, the Windows-vs-Unix shell/Python rules, the
temp-dir and cleanup conventions, the JSON-array output gotcha, and the MSL 4.x
dialect notes that every step below assumes.

In `--mode diagnose` the launcher enables the diagnostic options it needs and
**keeps all intermediate build artifacts** for the report scripts
(`report_blocks.py` / `trace_variable.py`). It works in `_wsm_diagnose_temp/`
next to the `.mo` file and leaves all artifacts there. Tell the user: "Working
in temporary directory `_wsm_diagnose_temp/`. This will be deleted after the
report is generated."

## Workflow

### 1. Identify the model file and name

Identify the `.mo` file and extract the **model name** — see [Appendix → Picking the model name](#picking-the-model-name). For a **directory-form (multi-file) library**, point `--model` at the library folder (not one class file) and pass the full dotted `--name` — see [Appendix → Directory-form (multi-file) libraries](#directory-form-multi-file-libraries).

### 2. Run the launcher

```bash
python3 "<scripts-dir>/wsm_run.py" --mode diagnose \
  --model "<path-to-ModelFile.mo>" --name ModelName --timeout 180
```

MSL is auto-detected; override with `--msl yes|no` or `--msl-version 4.1.0`. If the model uses an installed non-MSL library (e.g. `Hydraulic`), add `--load-library <Name>` — see [Appendix → Using non-MSL libraries](#using-non-msl-libraries-hydraulic-and-other-installed-libraries).

**For structure only, skip the simulation entirely:** add `--no-sim` (build-only,
much faster). The structural report below still works; only the runtime-performance
line is omitted.

**A `Fatal error: exception ...(_)`** (e.g. `ErrorExt.ErrorMessage(_)`, `LError.Errors(_)`)
**is not an opaque crash** — it's a normal error (assertion, parameter/init, type, lookup)
that `+g` let escape, since `+g` keeps build artifacts but disables exception catching.
On any failure the launcher prints the recovered message in an `=== actual kernel
diagnostic ===` block (re-running the same call *without* `+g`, so exception catching is
back on and the error surfaces at whatever stage it occurred). **Read that block first;
don't infer a compiler bug from the `Fatal error` line.** Use the staged diagnostics
below only if it surfaces nothing readable.

#### Staged diagnostics (for a genuinely opaque crash)

A full run goes through the whole pipeline (flatten → optimize → build → simulate);
a crash partway through gives no clue *which* stage failed. The launcher's `--call`
option runs a stage-restricted entry point so you can bracket the failure, and
`--debug` adds the compiler's per-stage dumps and execution statistics:

| `--call` | What it does | When to use |
|----------|--------------|-------------|
| `instantiate` | Flatten only. | First call when a model is failing — confirms whether flattening succeeds. |
| `build` | Flatten + translate to simulator (no simulation). | If flatten passes but the full run crashes — isolates optimization/code-gen from the runtime. |
| `sim` | Full pipeline including simulation. | Default for healthy models (used when `--call` is omitted). |

Workflow (only when the diagnostic block above surfaced nothing readable):
1. Run with `--call instantiate` first. If it fails → it's a flatten error (type/connection/balance). Read the `=== actual kernel diagnostic ===` block, then `diagnose.out.json` in the temp dir.
2. If flatten passes, run `--call build --debug` and capture stdout — the last stage printed before the crash localizes the bug. The `--debug` output can be large, so redirect it:
   ```bash
   python3 "<scripts-dir>/wsm_run.py" --mode diagnose \
     --model "<path-to-ModelFile.mo>" --name ModelName \
     --call build --debug > debug.log 2>&1
   ```
3. Only then run the default (`--call sim`, or omit it) for the full report.

If the log shows `++++ Running` or runtime annotation lines, the model already built —
the failure is at init/simulation (a model error), not code-gen; a truncated `_build.log`
("Step 2 of 4") does not mark where it died.

### 3. Generate the structural report

After a successful run, use the bundled `report_blocks.py` script to generate a complete report. This is the preferred approach — it parses all the artifacts automatically, so you never need to read them by hand:

```bash
python3 "<scripts-dir>/report_blocks.py" \
  "<temp-dir>/ModelName_blockdebug.json" \
  --header "<temp-dir>/ModelName_header.h" \
  --reslog "<temp-dir>/ModelName_res.log"
```

The script produces a full report covering variable counts, block summaries, non-trivial systems with solvability details, eliminated aliases, and runtime performance.

**Prefer `--summary` (or `--json`) for a few-line digest** — states, algebraic/parameter
counts, zero-crossings, coupled-system count + largest block, and runtime — instead of
the full multi-screen report. Reach for the full report only when you need block-level
detail. With `--no-sim` the same `--summary` works from the `_blockdebug.json` alone;
only the runtime-performance line is omitted.

The artifacts `report_blocks.py` reads all live in the temp dir (`ModelName_header.h`,
`ModelName.sim`, `ModelName_blockdebug.json`, `ModelName_res.log`, `ModelName.log`,
`diagnose.out.json`). The script understands their formats for you; only open them
directly if you need to dig past what the report surfaces.

### 4. Present the diagnostic report

Present the report to the user in this format:

```
# Diagnostic Report: ModelName

## Build Status
- Flatten: Pass/Fail
- Build: Pass/Fail
- Simulation: Pass/Fail

## Model Summary
| Metric | Count |
|--------|-------|
| Continuous states (NX) | ... |
| Discrete states (NDX) | ... |
| Algebraic variables (NY) | ... |
| Parameters (NP) | ... |
| Inputs (NI) | ... |
| Outputs (NO) | ... |
| Zero crossings | ... |
| External objects | ... |
| Clocked partitions | ... |

## Solver Settings
- Method: ...
- Time range: ... to ...
- Step size: ...
- Output steps: ...

## Variable Details
| Name | Kind | Type | Unit | Init |
|------|------|------|------|------|
| ... | STATE | Real | m/s | exact |

## Equation Structure

### Initialization (N blocks)
- Block 0: [solved] variable_name ← equation_text
- ...

### ODE (N blocks)
- Block 0: [solved] ...
- ...

### Output (N blocks)
- ...

### Eliminated Variables (N aliases)
- gain.u → sine.y
- ...

## Potential Issues
- [List any nonlinear systems, large blocks, unsolvable equations, etc.]

## Runtime Performance
- Integration time: ... s
- Function evaluations: ...
- Events: ...
- Step events (dynamic state switches): ...

## Compiler
- Version: ...
```

Tailor the "Potential Issues" section based on what `report_blocks.py` reports:
- Nonlinear blocks → "Nonlinear system of N equations — may cause convergence issues at initialization or during simulation"
- Large algebraic loops → "Algebraic loop with N equations — consider breaking with `Modelica.Blocks.Math.InverseBlockConstraints` or adding initial guesses"
- Many zero crossings → "N zero crossings — may cause slow simulation due to frequent event detection"
- No states → "No continuous states — this is a purely algebraic/discrete model"
- Many events at runtime → "N events detected — consider smoothing discontinuities"

### 5. Trace a specific variable (optional)

If the user asks to trace a variable (e.g. "trace clutch1.w_rel", "what equations solve w_rel"), use the bundled `trace_variable.py` script to walk the full dependency chain.

The script needs the `_blockdebug.json` produced in step 2. Run it from the temp directory:

```bash
python3 "<scripts-dir>/trace_variable.py" "<temp-dir>/ModelName_blockdebug.json" "variable.name" --section both
```

Options for `--section`:
- `init` — How the variable gets its starting value (initialization phase)
- `ode` — How the variable is computed each integration step
- `both` — Show both traces (default)

The script automatically:
- Walks backwards through predecessor blocks from the target variable to all leaf nodes
- Shows each equation, its source file/line, and solvability
- Flags non-trivial solvability (nonlinear, mixed, conditioned, relaxed)
- If the variable isn't found in the ODE section, automatically tries `der(variable)` (since state variables are integrated, their derivatives are what appears in the ODE blocks)
- Reports eliminated variable aliases

### 6. Clean up

Remove `_wsm_diagnose_temp/` entirely — commands per OS: [Appendix → Temporary directories](#temporary-directories).

## Edge cases

- **Model fails to flatten**: Report errors from `diagnose.out.json`. Analyze the error messages and suggest fixes (missing components, type mismatches, unbalanced equations).
- **Model flattens but fails to build**: Still run `report_blocks.py` on `_blockdebug.json` if it was generated — it's produced before compilation. Report build errors from `ModelName.log`.
- **Model builds but fails to simulate**: Report runtime errors from `_res.log`. Check for division by zero, assertion failures, or solver convergence issues.
- **`Fatal error: exception ...(_)`** (no `_blockdebug.json` or `.sim`): a normal error `+g` let escape, **not** a compiler bug. Read the launcher's `=== actual kernel diagnostic ===` block (it auto-recovers the message by re-running the same call without `+g`). Only if it surfaces nothing readable, use the staged diagnostics above; report to Wolfram only when the failure lands in a compiler stage with no model-level cause.
- **Multiple models in one file**: Use the top-level model/package name — see [Appendix → Picking the model name](#picking-the-model-name).
- **WSMKernelX or compiler not found**: see [Appendix → When the install or compiler isn't found](#when-the-install-or-compiler-isnt-found).

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
