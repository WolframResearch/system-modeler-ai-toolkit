---
name: simulate-and-plot-modelica
description: "Simulate a Modelica model and plot the results — reads the simulated .mat with DyMat and plots chosen variables over time. Use this skill whenever the user asks to simulate and plot a model, plot simulation results, plot or graph specific variables over time, or visualize a model's time-domain behavior. Triggers on phrases like 'simulate and plot', 'plot the results', 'plot these variables', 'graph the output', 'show me the trajectories', or any request to visualize simulation output. Prefer this over simulate-modelica whenever the request involves plotting or visualizing results. For analysis beyond plotting — checking limits/requirements, violations, parameter sweeps, Monte Carlo, calibration — prefer the wolfram-language-modelica skill when Wolfram Language is available; use this skill's Python path when it is not."
---

# Simulate and Plot

This skill simulates a Modelica model and plots the results: it runs the
simulation to produce a `.mat`, then reads chosen variables from it with DyMat
and plots them over time. No reference data is needed.

**Scope check before starting:** if the request goes beyond plotting —
verifying limits or requirements, finding violations, parameter sweeps, Monte
Carlo, fitting/calibration — and Wolfram Language is available (e.g. a Wolfram
MCP tool or `wolframscript`), hand the task to the `wolfram-language-modelica`
skill instead: the built-in `SystemModel*` functions do that analysis natively.
Use this skill's Python analysis path only when Wolfram Language is not
available.

## Prerequisites

`plot_mat.py` needs **DyMat** (reads `.mat`), **matplotlib**, **numpy** and **scipy**. You do not
install these by hand: the script **self-provisions a managed venv** on first use (it never touches
system Python). To pre-warm it: `python3 "<scripts-dir>/bootstrap_env.py"`.

## Before you run anything

This skill drives WSMKernelX through the shared launcher
`../scripts/wsm_run.py`. **Read [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills)
first** — launcher resolution, the Windows-vs-Unix shell/Python rules, the
temp-dir and cleanup conventions, and the MSL 4.x dialect notes that every
step below assumes.

## Temporary Directory

The launcher writes into `_wsm_simulate_temp/` next to the model file (or pass
`--tempdir "<repo-root>/_wsm_simulate_temp"` to reuse one dir across models in a
session). Tell the user: "Working in `_wsm_simulate_temp/`. Will be deleted at
end of session."

## Workflow

### 1. Identify the model

The user may provide a path to a `.mo` file, or a fully qualified model name (for
a model that lives in a loaded library).

### 2. Simulate

Run the launcher to produce the `.mat`:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode simulate \
  --model "<path-to-ModelFile.mo>" --name <FullyQualifiedModelName> \
  --tempdir "<temp-dir>" --timeout 180 2>&1 | grep -E "succeeded|stopped|events:|out.json"
mat_file=$(ls "<temp-dir>"/*.mat | head -1)
```

MSL is auto-detected.

If the model uses a library that must be loaded first: for a library **installed**
on the machine (e.g. `Hydraulic`), just add `--load-library <Name>` — the launcher
finds and loads it (see [Appendix → Using non-MSL libraries](#using-non-msl-libraries-hydraulic-and-other-installed-libraries)).
For a library that lives in the **repo/on disk**
(e.g. `HydraulicTests`), pass its file with `--load` (repeatable). Both load before
the model:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode simulate \
  --model "<repo>/Model.mo" --name <FullyQualifiedModelName> \
  --load-library Hydraulic --load "<repo>/HydraulicTests/HydraulicTests.mo" \
  --tempdir "<temp-dir>" --timeout 180
```

### 3. Plot the results

Pick the variables to plot (ask the user, or use `--list` to see what's in the
`.mat` and choose a sensible few), then plot them with `plot_mat.py`. Favor curves that reveal
*emergent* behavior — a dynamic response, a comparison, a limit case — over ones that just
re-trace a known input signal (if you'd see the same shape by plotting the input alone, skip it):

```bash
# See what's available
python3 "<scripts-dir>/plot_mat.py" "$mat_file" --list | head -40

# Combined figure, one subplot per variable
python3 "<scripts-dir>/plot_mat.py" "$mat_file" <var1> <var2> <var3> \
  --outdir "<plots-dir>" --title "<model> results"
```

**plot_mat.py options:**
- `--list` — print the `.mat`'s variable names and exit (no plot)
- `--separate` — one PNG per variable instead of a combined figure
- `--ncols N` — columns in the combined grid (default 2)
- `--name NAME` / `--title STR` — output filename stem / figure title

### 4. Show the plot to the user

Read and display the generated `.png` with the `Read` tool. If the user wants a
different set of variables or one-per-file, re-run `plot_mat.py` with a new
variable list or `--separate`.

### 5. Switching to another model

Just re-run the launcher with the same `--tempdir` and a new `--name`/`--model`.
It regenerates the `.mos` and reuses the temp dir; the build is fast for the
second model since the toolchain is warm. To keep the temp dir tidy, optionally
clear old build artifacts first (the `.mat`, `.exe`/binaries, `.sim`, logs):

```bash
find "<temp-dir>" -maxdepth 1 \( -name "*.mat" -o -name "*.exe" -o -name "*.sim" -o -name "*.log" -o -name "*.jsonl" -o -name "*.lib" -o -name "*.libs" -o -name "*.exp" -o -name "*_units.json" -o -name "*_build.log" \) -delete
python3 "<scripts-dir>/wsm_run.py" --mode simulate --model "<new-model.mo>" --name <New.Model> --tempdir "<temp-dir>"
```

### 6. Cleanup

At end of session (or when switching projects), remove `_wsm_simulate_temp/` entirely — commands per OS: [Appendix → Temporary directories](#temporary-directories).

Keep final plots in `_comparison_plots/` — they are useful references.

## Inspecting data inline

For one-off data inspection, use `python -c "..."` inline. Do **not** write
`debug_*.py` files.

```bash
python -c "
import DyMat
d = DyMat.DyMatFile('path/to/file.mat')
print(d.names()[:20])
print(d.data('variable.name')[-10:])
"
```

For longer exploration (5+ lines of Python), use a single `explore.py` in the
temp dir and overwrite it as needed — don't accumulate `debug_a.py`, `debug_b.py`, etc.

## File-efficiency rules

1. **One temp dir per session** — pass the same `--tempdir` for every model; never `_wsm_simulate_temp_plots`, `_wsm_diagnose_temp`, etc. in parallel
2. **Let the launcher manage the `.mos`** — don't hand-write or duplicate scripts
3. **Inline python via `-c`** — don't create `debug_*.py` files for one-off inspection
4. **Clean build artifacts between models** (see step 5)
5. **Final plots in `_comparison_plots/`** — keep. Temp simulation artifacts — delete.

## Edge cases

- **Variable not found in .mat**: `plot_mat.py` warns and skips it; check the name with `--list` (Modelica uses dotted names, e.g. `tank1.port_a.mdot`).
- **Too many variables**: don't plot all of them — pick the few that matter for the question. `--list` shows what's available.
- **DyMat import error**: `plot_mat.py` auto-provisions its venv; if it still fails, pre-warm with `python3 "<scripts-dir>/bootstrap_env.py"` and check `$WSM_SKILLS_VENV`.
- **Model fails to simulate**: report the runtime error from the simulate step; there's nothing to plot until it runs.

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
