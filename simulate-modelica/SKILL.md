---
name: simulate-modelica
description: "Simulate Modelica models (.mo files) with WSMKernelX — compiles to C++, builds, and runs the simulation (no plotting; to plot the results too, use simulate-and-plot-modelica). Use this skill whenever the user asks to simulate a Modelica model, run a simulation, or get simulation results or time-domain behavior. Triggers on phrases like 'simulate this model', 'run the simulation', 'get simulation results'. Use it also when running a model is a step in a larger job you took on yourself — verifying a port, a datasheet claim or a hand-written implementation against a model built for the purpose — even if the request never mentioned Modelica. If the request also involves analysis — limits/requirements, violations, parameter sweeps, Monte Carlo, calibration — prefer wolfram-language-modelica when Wolfram Language is available."
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
  3. The usual physical fix, in any domain, is to restore the small **storage element the idealized model dropped** — a device capacitance on an electrical node, a compliant joint for a rigid coupling, a heat capacity on a thermal port, a small volume at a fluid junction. It turns the algebraic loop into an integrable ODE and defines the operating point. The `diagnose-modelica` skill covers where to put it, and the two placements that look right and are not.
  4. As a numerical lever, loosen tolerance or raise `--timeout`, but prefer fixing the model structure — a model that needs a huge timeout for a short horizon is usually telling you something.

---

## Appendix: shared conventions for the Modelica skills

> *Shared by every Modelica skill that drives WSMKernelX through the
> bundled launcher; inlined here at release time. For the CLI/option
> reference, environment variables (`WSM_HOME`, `WSM_VSDEVCMD`),
> install discovery, and the analysis scripts, see
> [`../scripts/README.md`](../scripts/README.md).*

**These are conventions, not a workflow.** Knowing how to call the tools is not
the same as knowing which to call, in what order, and how to tell a good answer
from a plausible one — that lives in the skills, one per job. Invoke the one that
owns the step you are on, **including when it is not the one you started from**:
a job that begins in one skill routinely runs into something another one owns,
and the whole toolkit is available the entire time.

| What you run into | Skill |
|---|---|
| About to write or restructure a model or library — including one you decided to build yourself | `modelica-model-architecture` **first** |
| A `.mo` you just wrote or edited; a structural error | `validate-modelica` |
| You need results | `simulate-modelica` (`simulate-and-plot-modelica` to plot them too) |
| A run that must go in real time, take input changes while it runs, or be driven from another program | `simulate-modelica-realtime` |
| It validates but will not build; it runs far too slowly; it gives an answer you cannot account for; you need its states, equations or blocks | `diagnose-modelica` |
| The launcher reports a `compiler failure` — an internal error, generated code that does not compile, a simulator internal error or a kernel crash | `minimize-modelica-bug` |
| A Modelica language or MSL question you would otherwise answer from memory | `search-modelica-docs` |
| Sweeps, limit checks, calibration, custom result analysis | `wolfram-language-modelica` |
| No icons, or no diagram layout | `annotate-modelica-graphics` |
| Plots that should live in the model and reopen with it | `annotate-modelica-plots` |
| Interactive sliders in Simulation Center's Explore view | `annotate-control-panel` |
| 3D MultiBody animation | `annotate-modelica-animation` |
| A hydraulic circuit | `create-hydraulic-model` |

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

**For your own analysis, borrow the scripts' interpreter.** Whatever `python3`
you get is unlikely to have numpy or scipy, and installing into it is both rude
and often blocked. The analysis scripts run under a managed virtualenv with
numpy, scipy, matplotlib and DyMat; `python3 <scripts-dir>/bootstrap_env.py`
makes sure they are installed there and prints its interpreter path. Use that
interpreter for ad-hoc post-processing rather than discovering package by
package what the system one lacks.

### Line endings in .mo files

Modelica models are written on Windows, macOS and Linux alike, so a `.mo` file
may use CRLF or LF. **Neither is the "right" one.** Match whatever the file
already has, and never leave a file with a mix of both — a mixed file shows up
as a whole-file diff the moment anything rewrites it, burying the real change.

When you edit a `.mo` yourself with the Write/Edit tools (rather than through one
of the annotator scripts), those tools write back exactly the text you give them,
so an edit in the other style silently mixes the file. Check before, and check
again after:

```bash
python3 "<scripts-dir>/mo_edit.py" --eol "<Model.mo>"
```

It prints `LF`, `CRLF`, `MIXED (crlf=N lf=M)` or `NONE`, and exits non-zero on
`MIXED`. If an edit did change the endings, put them back — this rewrites the
whole file to one ending, so it also repairs a mixed one:

```bash
python3 "<scripts-dir>/mo_edit.py" --set-eol auto "<Model.mo>"   # or: lf, or crlf
```

**A mixed file follows its library, not itself.** If the file you are editing is
mixed while the rest of the library is consistent, do not settle it on whichever
ending dominates *inside* that file — the mixing is damage, so the file is not
evidence about itself, and its majority leaves you with the one odd file out.
Use the library's ending. `auto` does this for you, and reports which rule it
applied.

Creating a new `.mo`: same rule — match the sibling `.mo` files in the same
directory or library (`--eol` accepts several paths at once), so one library does
not end up half CRLF and half LF. Use LF only when there is nothing to match.

The annotator scripts' `--write` paths already preserve the file's endings and
warn about a mixed input, so no manual step is needed around those.

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
- **A class that is already in a loaded library needs no `--model` at all** — give
  just the full dotted `--name` and the launcher takes it from MSL (or from a
  `--load-library` library). Use this for MSL examples rather than writing a
  wrapper model that extends one:

  ```bash
  python3 "<scripts-dir>/wsm_run.py" --mode diagnose \
    --name Modelica.Mechanics.MultiBody.Examples.Loops.EngineV6
  ```

  The temp dir then goes in the current directory. `--model` is still required
  for a class in the user's own file.

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

### Checking graphic annotations

A plain run does not evaluate the graphic annotations: `Icon`, `Diagram` and
`Placement` are carried along untouched, so an error inside one cannot fail the
run. Add `--graphics` to have them evaluated together with the model:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate --graphics \
  --model "<Model.mo>" --name "<Package>.<ModelName>" --timeout 90
```

Errors then arrive through the usual `status.flatten` and `messages.errors`: a
variable or component path that does not resolve, a misspelled shape
(`Rectangel`) or field (`extend`), an array subscript out of bounds. This mode
needs no C++ compiler, so it is the gate to run after editing annotations.

The compiling modes (`--mode simulate`, `--mode diagnose`) additionally generate
the model's diagram view, which evaluates the animated (`DynamicSelect`)
expressions themselves. The launcher prints a `graphics :` line naming the
generated view; if it was not generated it says so and exits non-zero, meaning an
animated field could not be evaluated. It also exits non-zero, listing them, when
an animated value falls back to its static value — typically an expression using a
function the diagram does not support. Nothing else reports either.

Evaluating the annotations is extra work for the frontend, so pass `--graphics`
when the annotations are what you changed or are checking, not by default.

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
