---
name: diagnose-modelica
description: "Diagnose Modelica models (.mo files) by generating a detailed structural and simulation report. Use this skill whenever the user asks to diagnose, analyze, profile, or debug a Modelica model's structure, equations, variables, or performance. Triggers on phrases like 'diagnose this model', 'analyze the model structure', 'show me the equation blocks', 'how many states does this model have', 'why is this model slow', 'debug this model', 'model report', or any request to understand the internals of a Modelica model. It applies equally when you reach for it mid-task — a model you wrote yourself validates but will not build, simulates far too slowly, or gives an answer you cannot account for."
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
python3 "<scripts-dir>/report_blocks.py" --tempdir "<temp-dir>"
```

(`--tempdir` finds the newest build's `_blockdebug.json`, `_header.h` and
`_res.log` for you; name the three paths individually only to report on an older
build in a reused temp dir.)

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
- Large algebraic loops → "Algebraic loop with N equations, torn to M". The fix is
  to give one of its variables a state by restoring an idealised-away storage
  element (see step 5, *Breaking a large coupled block*); better `start` values on
  the iteration variables help convergence but not the block's size
- Many zero crossings → "N zero crossings — may cause slow simulation due to frequent event detection"
- No states → "No continuous states — this is a purely algebraic/discrete model"
- Many events at runtime → "N events detected — consider smoothing discontinuities"
- A long integration time with no structural culprit → profile it (step 5); the
  structure says what the solver has to do, not which part is expensive

### 5. Profile where the time goes (optional)

The structural report says what the solver has to solve; it does not say what is
slow. When the user asks why a model takes so long — or when step 4 shows a long
integration time that the block structure alone does not explain — profile the
run:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode diagnose --profile --model "<path-to-ModelFile.mo>" --name ModelName --seconds 60
```

This builds the model the same way step 2 does, then runs it under the host's
sampling profiler — the launcher picks the right one for Windows, macOS or
Linux. `--load-library <Name>`, `--load <path-to-package.mo>` and the other
build options work exactly as in step 2. To profile again without rebuilding, run
`profile_sim.py --tempdir "<temp-dir>"` instead — it re-runs and re-samples the
model, skipping only the build.

**A model has to run long enough to sample.** The profiler collects a few hundred
samples per second of simulation, so it re-runs the model until it has enough
(the header says how many runs it took). The sampler needs up to about a second
to attach, so a run shorter than that can end before sampling starts, and
repeating will not help — give `--stop-time <T>` so that one run takes a few
seconds:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode diagnose --profile \
  --name Modelica.Mechanics.MultiBody.Examples.Loops.Fourbar2 --stop-time 10000
```

That needs no rebuild and does not touch the model's own settings. Say so when
you report the numbers: the run keeps the model's number of output points, so a
longer run spreads them more thinly and the output-section share drops, while the
per-block shares of the integration stay meaningful.

**The profiled run writes no result file.** The trajectory is identical — the
model still evaluates its output section at every output point — but the cost of
writing the file is left out, and a long run does not leave a large `.mat`
behind. Add `--profile-result` when you specifically want writing counted.

**A dense output interval is its own performance problem, and the profile hides
it.** Every output point forces the ODE blocks to be evaluated again, so the cost
lands on those blocks and the shares look unremarkable while the run is several
times longer than it needs to be. Read the interval out of the model's
`experiment` annotation (or the `.sim`'s `outputSteps` over its `start`–`end`)
against the run's own time scale, and check it before reading anything else into the profile: a model asking
for thousands of output points over its stop time is usually carrying a default
nobody chose. To measure what a coarser one would save, edit `outputSteps` in a copy
of the temp dir's `.sim` and re-run the built executable with `-f <copy>` — no
rebuild.

**The profile alone is not the answer.** A block index means nothing to the
user; the job is to carry it back to their model and say what to change. Work
through it in three passes.

**Pass 1 — read the profile.** Every sample is charged to the block it was taken
in, so each row is one block, what it solves, which classes its equations came
from, and how its cost divides:

```
  44.87 %  ode block 366 -- 366 equations, torn to 30 iteration variables, analytic-linear Jacobian
           solves cylinder1, cylinder2, cylinder3, cylinder4, +4 more
           from Utilities.Cylinder, Parts.Body, Parts.FixedTranslation, +2 more
           cost generated equation bodies 71% | Jacobian linear algebra 22% | nonlinear solver 2%
```

The **by model component** roll-up that follows names the instances. Six equal
shares across `cylinder1..6` means the cost lives in the shared class, not in one
instance — fix the class once. A final **by kind of work** table gives the same
cost split for the whole run, which is the one number to quote when the user asks
where the time goes overall.

**Pass 2 — open the hot blocks against the model.** For each of the top two or
three blocks, get the classes and lines its equations were flattened from:

```bash
python3 "<scripts-dir>/report_blocks.py" --tempdir "<temp-dir>" --block ode:366
```

It prints the equation count and torn size, every source class with the lines it
contributed, the variables solved per component, and the equations themselves.
Read the named lines in the user's own `.mo` files. When they land in a library
class (`Modelica.*`), the lever is not that class — it is how the model uses it:
which component was chosen, how many of them there are, and how they are
connected.

A row reading `N blocks evaluated together (a-b)` is time the sampler could not
place on one block of that range; `--block` opens the blocks in it one at a time.

**Pass 3 — turn that into changes.** The cost split says which kind of fix
applies:

| What the profile shows | What it means | What to suggest |
|---|---|---|
| big block, many iteration variables, cost mostly **generated equation bodies** | one large coupled system, expensive to evaluate once | shrink the system — usually by giving one of its variables a state (see below), or by picking a simpler component variant or cutting duplicated structure |
| cost mostly **nonlinear solver**, small torn size | the solver iterates a lot per step | better `start` values on the iteration variables (`check_tearing.py` names them and the residuals Newton solves), `homotopy` when it is initialization that struggles, and remove discontinuities feeding the block |
| Jacobian reported as **numeric** | the solver finite-differences it — one extra residual evaluation per iteration variable | find what the compiler could not differentiate in that block (external functions, non-smooth tables, `noDerivative`) and make it differentiable |
| cost mostly **Jacobian linear algebra** | dense factorisation of a large torn system each step | the lever is the torn size, not the arithmetic — same fix as the first row; `check_tearing.py` (below) shows what is torn |
| cost mostly **transcendental math** or a **medium:** category | expensive correlations re-evaluated every step | simplify or cache the correlation, or use a cheaper medium/property model |
| high **integrator and event handling**, many events in step 4 | the solver is restarting on discontinuities | smooth the discontinuity (`smooth`, `noEvent`, a regularised law) |
| the hot blocks are in the **init** section | initialisation dominates | only matters for short runs or repeated restarts; give better initial guesses |
| the hot blocks are in the **output** section | writing results dominates | store fewer variables, or increase the output interval |

#### Breaking a large coupled block: restore the storage the model idealised away

This is the highest-value fix in the table and the one to reach for whenever a
single block dominates, so it is worth doing deliberately rather than by
instinct. A block is large because none of the variables in it is a state: they
are all unknowns of one simultaneous system, so the solver tears it and runs
Newton on every step. Give **one** of those variables a state and the system
falls apart into smaller ones.

The variable to pick is almost always a **connector variable of a component that
was idealised** — a source whose output is an algebraic function of its inputs, a
rigid coupling, a perfect contact. Real hardware has a small storage element
there (capacitance, compliance, inertia, volume) that the ideal model dropped.
Putting it back is physical, not a numerical trick.

**Find the variable.** `check_tearing.py` names each torn system's iteration
variables and the residual equations Newton solves (`--section ode` or
`output` narrows it to the section of the profiled block):

```bash
python3 "<scripts-dir>/check_tearing.py" "<temp-dir>/ModelName_blockdebug.json" --section ode
```

`report_blocks.py --block <section>:<index>` names the classes and lines the
block's equations came from. A connector variable of the user's own component in
that list is the candidate.

**Then add the element that gives it a state**, matching the domain:

| Domain | Storage on the **potential** (across) | Storage on the **flow** (through) |
|---|---|---|
| Electrical | capacitance from the node to ground → node voltage | series inductance → branch current |
| Thermal | heat capacitor on the port → port temperature | (no dual in the MSL thermal domain) |
| Fluid / hydraulic | a small volume at the junction → junction pressure | fluid inertia in a line → mass flow rate |
| Translational | spring-damper replacing a rigid connection → relative position | a mass → velocity |
| Rotational | torsional spring-damper replacing a rigid shaft → relative angle | an inertia → angular velocity |
| Signal blocks | a first-order lag in the algebraic feedback path → the lag output | — |

Use the **potential** column when the loop solves for voltages, temperatures,
pressures or positions — the common case, and what an idealised *source* leaves
behind. Use the **flow** column when two ideal potential sources or rigid
velocity constraints meet and the unknown is the current, flow rate or force
between them. Adding it inside the component's own equations (a
`C*der(pin.v)` term) and adding the library component do the same thing
structurally; the term keeps the parasitic with the component it belongs to.

**Two placements look right and are not:**

- **One element away from the connector.** A pole *behind* a series output
  resistance bandwidth-limits the component but leaves the connector variable
  algebraically tied to the load, so the block survives. The storage has to be on
  the variable the block is solving for.
- **On a node a real storage element already ties to another state.** A second
  capacitance on a node that already has one, a capacitance straight across an
  ideal voltage source, an inertia rigidly coupled to another one: the new
  variable is fixed by an existing state or source, so it does not become a state
  of its own and the block does not shrink. Pick another node in the block.

**Sizing and checking.** Make the added time constant short against the fastest
behaviour the model is meant to show, and no shorter — an unnecessarily tiny one
just makes the model stiff. Then, every time:

- Re-run step 2, and check that `NX` in `report_blocks.py --summary` rose by one
  per added element (the `selected as states` notification in
  `diagnose.out.json` lists the states). If it did not, or a notification there
  reports `Differentiated equation for index reduction` on the new equation, the
  second placement above applies — move it.
- In the same summary, the largest block should shrink. The number of coupled
  systems usually goes *up*, since one large system becomes several small ones;
  if the largest block did not shrink, the state did not land inside it.
- **Check the trajectory, not only the clock.** A parasitic big enough to change
  the answer is a modelling change, and has to be reported to the user as one.
- Re-time the run. Honest reporting means the before and after come from the same
  stop time and the same tolerance.

**A tolerance that suddenly costs 100x is a symptom of this, not a setting to
tune.** If tightening the tolerance one decade turns a fast run into one that
does not finish, the model has a block like this and the fix is structural.

Report to the user, in this order: which components and model classes the time is
in, why (the block's structure and cost split), and a ranked list of concrete
changes with what each would save. Name model classes and line numbers — never
`chunkFunction_74` or the runtime functions underneath it, which the user cannot
change. Be honest about size: say when a suggestion is a modelling trade-off
(a compliant joint changes the physics) rather than a free win.

The profile is only as good as its sample count — the header prints the samples
collected and the effective rate, so profile a case that is genuinely slow and
treat a small count as thin evidence.

If the host has no usable sampling tool the launcher says so before building,
and the message names the fix; `wsm_run.py --mode info` prints which profiler it
resolved. When one cannot be made available, the structural reports of steps 3-4
remain the way in.

### 6. Trace a specific variable (optional)

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

### 7. Clean up

Remove `_wsm_diagnose_temp/` entirely — commands per OS: [Appendix → Temporary directories](#temporary-directories).

## Edge cases

- **Model fails to flatten**: Report errors from `diagnose.out.json`. Analyze the error messages and suggest fixes (missing components, type mismatches, unbalanced equations).
- **Model flattens but fails to build**: Still run `report_blocks.py` on `_blockdebug.json` if it was generated — it's produced before compilation. Report build errors from `ModelName.log`.
- **Model builds but fails to simulate**: Report runtime errors from `_res.log`. Check for division by zero, assertion failures, or solver convergence issues.
- **`Fatal error: exception ...(_)`** (no `_blockdebug.json` or `.sim`): a normal error `+g` let escape, **not** a compiler bug. Read the launcher's `=== actual kernel diagnostic ===` block (it auto-recovers the message by re-running the same call without `+g`). Only if it surfaces nothing readable, use the staged diagnostics above. When the launcher prints a `=== compiler failure ===` block, the fault is in System Modeler: hand over to `minimize-modelica-bug`.
- **Multiple models in one file**: Use the top-level model/package name — see [Appendix → Picking the model name](#picking-the-model-name).
- **WSMKernelX or compiler not found**: see [Appendix → When the install or compiler isn't found](#when-the-install-or-compiler-isnt-found).

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
