---
name: minimize-modelica-bug
description: "Reduce a Modelica model that triggers a System Modeler compiler failure (an internal error, generated code that fails to compile, a simulator internal error or a kernel crash) to the smallest model that still fails the same way, and prepare a bug report for Wolfram support. Use this skill whenever the launcher prints a `=== compiler failure ===` block or reports a `compiler_failure`, or the user mentions an 'internal error', 'Fatal failure', 'the compiler crashed', 'generated code failed to compile', 'report this bug to Wolfram', 'make a minimal example' or 'reduce this model for a bug report'. It applies just as much when the failure turns up mid-task in a model you wrote yourself: a compiler failure is a fault in System Modeler, not something to work around silently."
---

# Minimize a Modelica Compiler Bug

A *compiler failure* is a fault in System Modeler itself rather than in the
model. Examples are an `Internal error`, generated code that does not compile,
and a simulator that stops with an internal error. This skill shrinks the
failing model to the smallest one that still fails with the same message, and
writes a short report the user can send to Wolfram support. A small
reproduction gets a bug fixed; a 5,000-line proprietary model usually does not.

Ordinary model errors are not compiler failures: type, lookup and balance errors,
failed assertions, or a solver giving up. Fix those in the model instead, using
`validate-modelica` or `diagnose-modelica`.

## Before you run anything

This skill drives WSMKernelX through the shared launcher
`../scripts/wsm_run.py` and the reducer `../scripts/minimize_mo.py`. **Read
[the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills) first**. It covers launcher
resolution, the Windows-vs-Unix shell/Python rules, and the temp-dir and
line-ending conventions that every step below assumes.

The reducer never touches the user's files. It works on copies in
`_wsm_minimize_temp/` next to the model. Tell the user: "Working in temporary
directory `_wsm_minimize_temp/`; your model is not modified."

## Workflow

### 1. Confirm that it is a compiler failure

Identify the model file and name — see
[Appendix → Picking the model name](#picking-the-model-name)
and, for a multi-file library,
[Appendix → Directory-form (multi-file) libraries](#directory-form-multi-file-libraries).
Then run it once:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode simulate \
  --model "<path-to-ModelFile.mo>" --name ModelName --json
```

- `"compiler_failure"` in the printed JSON is not `null`: this is a compiler failure. Note its `head` (the part of the message that identifies the fault) and the System Modeler `version`.
- `"compiler_failure"` is `null`: it is not a compiler failure. Tell the user so, show the ordinary error the launcher printed, and help fix the model instead.

A crash — `kind` `crash`, or a `head` reporting a simulator crash or stack
overflow — can come from the model's own code rather than from System Modeler:
a function that recurses without end, an external C function that crashes, or
arrays too large for memory. Rule these out first, for example by checking the
recursion's end condition or by replacing the external function with a Modelica
stub on a copy, and treat it as a compiler failure only if it still crashes.

An `Internal error` about an unknown library is a setup problem, not a bug, and
is not reported as a compiler failure. The fix is to load the missing library
(see [Appendix → Using non-MSL libraries](#using-non-msl-libraries-hydraulic-and-other-installed-libraries)).

### 2. Run the reducer

```bash
python3 "<scripts-dir>/minimize_mo.py" \
  --model "<path-to-ModelFile.mo>" --name ModelName
```

Pass the same `--load-library` / `--load` options the model needs to run.

The reducer finds the earliest stage that shows the failure (`instantiate`, then
`check`, `build`, `sim`). It then keeps removing comments, annotations, classes,
statements, modifiers and bindings, and replacing `if`/`when` statements by one
of their branches, as long as the model still fails with the same `head`. On a
machine with four or more cores it tries several candidates in parallel (`-j`).

This takes from a minute to half an hour depending on the model. `--budget`
sets the limit in seconds and defaults to 30 minutes. Run it in the background
and tell the user roughly how long to expect. The smallest model found so far is
always in `_wsm_minimize_temp/best.mo`, so an interrupted run still leaves a
result.

It ends by printing a JSON summary containing:
- `stage`
- `failure`
- `reproduced_by_minimal`
- `original_lines` and `minimal_lines` (non-blank lines)
- `msl`: whether the minimal model still needs the Modelica Standard Library
- `kernel_version`

If it exits with status 2, the model showed no compiler failure, and the reducer
removes the work directory it created. Go back to step 1, and remove its
`_wsm_simulate_temp/` once you are done with it (see step 7). Status 1 with `"reproduced_by_minimal": false` means the final check of
`best.mo` did not fail the same way, even though every kept step did: the failure
is intermittent, or that run timed out (`minimal_failure` is `null`). Check
`best.mo` as in step 4 before going on. Status 1 without a summary is an error,
printed above it.

`--strict` requires the whole message to match, not only its `head`. Use it only
if a first run drifted to a *different* fault that happens to share the head. That
is visible when `minimal_failure.message` describes a different problem than
`failure.message`. The same error repeated, or different variable names, is not
a drift. For generated code that does not compile, the head hides the
identifiers, so compare the two messages yourself.

### 3. Reduce further by hand

The reducer only deletes, unwraps and replaces references by `0`. Once it
stops, what's left usually still contains structure only a human-style rewrite
removes. A typical example is one component feeding another: neither can go
without the other until the connection is replaced by a literal of the right
type.

Work on copies of `best.mo` in `_wsm_minimize_temp/manual/`, never on the user's
model. After each rewrite, check that the failure is still the same by running
the stage the reducer reported, giving each candidate its own `--tempdir` so
several can run in parallel:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate --call <stage> \
  --model "<copy.mo>" --name <Name> --tempdir "<unique-dir>" --json
```

For `build` or `sim`, use `--mode simulate --call <stage>`. Compare
`compiler_failure.head` with the original. If it changed or went away, undo the
rewrite; that tells you the removed part is involved, which is worth noting for
the report. After a batch of successful rewrites, run `minimize_mo.py` again on
the copy with `--tempdir _wsm_minimize_temp/round2`, since a rewrite often makes
more deletions possible.

Rewrites that usually pay off, roughly in this order:

1. **Collapse the hierarchy.** Move the equations and variables of the component that fails into one top-level model. Replace records by plain variables and parameters by literal values. Drop enclosing packages; `--name` then becomes the plain model name.
2. **Replace library components.** An MSL component still in the model can often be replaced by the two or three equations that matter. Keep the MSL dependency if the failure disappears without it; a report that loads the MSL is fine.
3. **Simplify expressions.** Replace sub-expressions by `time` or constants, shorten arrays to two elements, drop terms that do not matter.
4. **Neutral names.** Rename the user's identifiers, descriptions and the model itself (e.g. `MinimalBug`) so the report carries nothing proprietary. Do this last, and check the failure once more afterwards.

Stop when removing any remaining line makes the failure go away, or when further
gains are marginal. Edits made with Write/Edit must keep the file's line endings
— see [Appendix → Line endings in .mo files](#line-endings-in-mo-files).

While reducing, keep two lists for the report:
- variations that **do not** fail, for example "works when the clock is a named variable" or "works with a parameter condition". They are often a workaround the user can apply right away;
- variations that fail the same way. They show how general the bug is.

A variation that fails with an ordinary model error instead is evidence of
neither, so leave it out.

### 4. Verify the final model

Run the final model once more in a fresh temp dir with the reducer's stage, and
check that `compiler_failure.head` still matches the original. If the reducer
reported `"msl": false`, the final model must also fail with `--msl no`.

### 5. Write the report

Create a folder `<Name>_bug_report/` next to the user's model, where `<Name>` is
the last part of the user's model name (`Plant` for `Batch.Plant`). It contains:

- `MinimalBug.mo`: the final model.
- `bug_report.md`, in this form:

```markdown
# <one-line summary of the failure>

- System Modeler version: <kernel_version>
- Operating system: <OS and version>
- Fails when: <checking | translating | simulating> the model `<Name>`

## Steps to reproduce
Load `MinimalBug.mo` and <check | simulate> `<Name>`.

## Observed
<the message of the final run's compiler_failure, verbatim, in a code block>

## Expected
The model <checks | translates | simulates> without an internal error.

## Notes
- Variations that also fail: <list from step 3>
- Variations that do not fail: <list from step 3>
- Reduced from a <original_lines>-line model.
```

Map the stages to plain words: `instantiate` and `check` mean checking the
model, `build` means translating it, and `sim` means simulating it.

Keep local paths out of the report. The full kernel output, such as a compiler
command line, names the user's directories; quote only the error lines.
Unrelated warnings about the user's model do not belong in the report.

### 6. Hand it to the user

Show the user the minimal model and the report, and suggest sending the folder
to **support@wolfram.com**. Ask them to review both files first for anything
confidential. Never send anything yourself. Mention any variation from step 3
that avoids the failure, since it may unblock them while the bug is fixed. If
you offer one as a workaround, first check it on a copy of their model in
`_wsm_minimize_temp/manual/`.

### 7. Clean up

Remove `_wsm_minimize_temp/` and the `_wsm_simulate_temp/` from step 1 once the
report is written — commands per OS:
[Appendix → Temporary directories](#temporary-directories).

## Edge cases

- **The reducer lands on a different message**: the head was too generic. Re-run with `--strict`, and compare the final message with the original in the report.
- **Every candidate times out**: the failure is a hang, not a message. The reducer cannot follow a hang; reduce by hand instead, treating "does not finish within N seconds" as the failure.
- **The failure only shows at `sim`**: each candidate is compiled and simulated, so a run takes longer. Give it a larger `--budget`, or bring the model to a smaller size by hand first.
- **Directory-form library**: point `--model` at the library folder. The reducer packs it into a single file, so the minimal model is one `.mo`.

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
