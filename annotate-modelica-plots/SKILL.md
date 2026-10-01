---
name: annotate-modelica-plots
description: "Add standardized Modelica result-plot annotations (Documentation(figures={Figure/Plot/Curve/Axis})) to a .mo model so simulation plots are stored in the model itself and reopen in Wolfram System Modeler. Use this skill whenever the user wants to store, embed, or save result plots in a model, define which variables to plot, add a figures annotation, or mark a time or a level on a stored plot with a labelled plot marker — a peak, a settling time, a threshold, a final value. Triggers on phrases like 'store the plots in the model', 'embed result plots', 'save these curves into the .mo', 'add a figures annotation', 'which variables should be plotted by default', 'mark the peak on the plot', 'add a marker at t = 2 s', 'show the settling time', 'draw a line at the limit', 'add measurements to the plot'."
---

# Annotate Modelica Plots

This skill writes the **spec-standard** result-plot annotation into a Modelica `.mo` file so a
model carries its own simulation plots:

```modelica
annotation(Documentation(figures = {
  Figure(identifier = "response", title = "Mass response", preferred = true,
    plots = {
      Plot(title = "Position and velocity",
        curves = {Curve(x = time, y = s, legend = "position"),
                  Curve(x = time, y = v, legend = "velocity")},
        x = Axis(label = "time"), y = Axis(label = "states", unit = ""))})}));
```

It is a **self-contained source transform**: Claude assembles a *figures spec* (JSON) — from the
user's request, or from variables discovered by simulating — and the Python engine renders it to
valid Modelica and splices it into the class annotation. The engine is pure Python (standard
library only); WSMKernelX is used only afterwards as a validation gate.

Wolfram System Modeler renders this standard annotation natively from the stored figure, picking up
the `Plot.title`, `Axis.label`, and per-curve `legend`. No vendor-specific annotation is needed.

It can also add System Modeler **plot markers** (`__Wolfram_markers`): labelled lines drawn on the
stored plot. A vertical marker at a time makes the plot's Measurements panel list every curve's
value at that time; a horizontal marker at a level lists every time a curve crosses it. See
[step 3c](#3c-markers--mark-a-time-or-a-level-optional).

It is **idempotent**: a class that already has `figures =` is skipped unless you pass `--force`
(which strips the old `figures` assignment and regenerates). By default it prints a dry-run diff;
nothing is written until `--write`.

> **`--force` is destructive — ask the user first.** It deletes the class's existing `figures`
> block before regenerating, so any hand-written or previously curated plot definitions there are
> lost (a user may have tuned those by hand). Don't pass `--force` on a class that already carries
> figures without first confirming with the user that discarding them is intended. Review the
> dry-run diff (no `--write`) to see exactly what would be removed.

## The figures spec (JSON)

Shaped after the spec records (MLS `annotations.tex` §figure-plot-properties). Only fields you set
are emitted:

```json
{
  "figures": [
    {
      "title": "Mass response", "identifier": "response", "preferred": true,
      "caption": "Damped oscillation of %[position](variable:s).",
      "plots": [
        {
          "identifier": "states",
          "title": "Position and velocity",
          "x": {"label": "time"},
          "y": {"label": "states", "unit": "", "scale": "Linear"},
          "curves": [
            {"x": "time", "y": "s", "legend": "position"},
            {"x": "time", "y": "v", "legend": "velocity"}
          ]
        }
      ],
      "markers": [
        {"identifier": "first_min", "x": 1.0, "xUnit": "s", "label": "first minimum",
         "plots": ["states"], "labelPosition": {"yOffsetCanvas": 0.9, "verticalAlignment": "Top"}},
        {"identifier": "rest", "y": 0.0, "yUnit": "m", "label": "rest position"}
      ]
    }
  ]
}
```

Marker fields (a position is required, the rest is optional):
- `x` **or** `y` — `x` is a vertical line at a position on the x axis, `y` a horizontal line at a
  level. Never both: System Modeler does not draw such a marker. On a time-based plot `x` is a
  time (`"xUnit": "s"`); on an X vs. Y plot it is a value of the x variable, in its unit (e.g.
  `"x": 0, "xUnit": "mm"`) — a time there lands at that value of the x variable instead.
- `yUnit` — the unit of a `y` level. Always set it, preferably to the unit the plot's y axis shows;
  without it the number is read in the axis unit, whatever that is.
- `label` — text drawn on the line. `%{var}` shows the variable's final value in its display unit.
- `plots` — plot identifiers or 0-based indices that show the marker; default is every plot of the
  figure. Restrict a `y` marker to the plots whose y axis it belongs to.
- `labelPosition` — where the label sits along the line, from 0 to 1: `yOffsetCanvas` for a
  vertical marker (0 = bottom), `xOffsetCanvas` for a horizontal one (0 = left). Plus
  `verticalAlignment` (`Top|Center|Bottom`, default `Bottom`) and `horizontalAlignment`
  (`Left|Center|Right`, default `Left`).
- `yAxis` — `"right"` for a level on the right y axis; default `"left"`.
- `identifier` — unique within the figure; defaults to `m1`, `m2`, ...

Rules the engine enforces (from the spec):
- `Curve.x`/`Curve.y` must be **result-references**: a scalar variable (`s`, `mass.v`), `time`, or
  `der(v[, n])` — *not* arbitrary expressions. A bad reference is a hard error. `x` defaults to
  `"time"`; set it to a variable for an X vs. Y plot (e.g. `{"x": "s", "y": "v"}` for a phase
  portrait).
- `Figure.identifier` must be unique in the spec; `Plot.identifier` unique within its figure.
- A marker has exactly one numeric position, a unique identifier within its figure, and `plots`
  entries naming existing plots.
- Axis `scale` is `"Linear"` (default), `"Log"`, or `{"Log": 10}` to set the base.
- `%{var}` variable replacements and `%[text](variable:ref)` caption links are passed through; the
  engine does not invent them.

To target a specific class in a multi-model file, either pass `--class <Name>`, or use a mapping
spec `{"Oscillator": {"figures": [...]}, "Plain": {"figures": [...]}}`.

## Running the annotator

The annotator lives in the `PlotAnnotate/` package next to this file. Run it as a module **from
this skill's directory** so the package is importable:

```bash
cd "<this-skill-dir>"
python3 -m PlotAnnotate.main --file "<path-to-Model.mo>" --analyze
```

Use `python` instead of `python3` on Windows if that's what's on PATH. Only `--file` (and `--spec`,
`--vars-file`) must be absolute or correctly-relative paths.

## Cross-platform launcher (for simulate / validate steps)

> The simulate/validate steps below call the shared `scripts/wsm_run.py` and
> `scripts/plot_mat.py`. Read [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills)
> (launcher resolution, shell rules, temp dir, JSON-array output, MSL 4.x notes)
> before those steps. In a normal install the launcher is `../scripts/wsm_run.py`
> (`<scripts-dir>` is the shared `scripts/` folder); if that path doesn't exist,
> see [Appendix → Locating the launcher](#locating-the-launcher).

## Workflow

### 1. Identify the model file and target class

The user gives a `.mo` path. Pick a **concrete instantiable model** for any kernel step
(`Package.Model`, not the package) — see
[Appendix → Picking the model name](#picking-the-model-name).

### 2. Analyze — see classes and existing figure status

```bash
python3 -m PlotAnnotate.main --file "<Model.mo>" --analyze
```

Lists every class, flagging `has Documentation` / `HAS figures`. Present this and confirm scope.

### 3. Choose what to plot

Pick curves that reveal *emergent / non-obvious* behavior — a dynamic response, a comparison, a
phase shift, a limit case. Skip tautological curves that just re-trace a known input signal (if
you'd see the same shape by plotting the input alone, it teaches nothing).

Curves default to `x = time`, but `Curve.x` can be any result variable, giving an **X vs. Y
plot**. Reach for one when the relationship between two variables is the story: a phase portrait
of an oscillator (limit cycles show as closed loops), a hysteresis loop, a transfer or force-
displacement characteristic. Put an X vs. Y curve in its own `Plot` (not mixed with time-based
curves — they'd share the x axis) and label both axes.

**Mode A — user-specified.** The user already knows the curves. Build the spec JSON directly from
their request and skip to step 4.

**Mode B — simulate-and-suggest.** When the user doesn't name variables, discover them:

```bash
# simulate to produce a .mat (and, beside it, a .sim init file with the same stem)
python3 "<scripts-dir>/wsm_run.py" --mode simulate --model "<Model.mo>" --name "<Package.Model>" --timeout 180
# enumerate result variables (write working files next to the model, not into the skill dir)
python3 "<scripts-dir>/plot_mat.py" "<Model-dir>/_wsm_simulate_temp/<result>.mat" --list > "<Model-dir>/vars.txt"
# get a starting spec (filters time/der/aux; one plot, x=time). Pass the .sim so protected
# variables are dropped — they are stored in the .mat but render blank in a stored figure.
python3 -m PlotAnnotate.main --file "<Model.mo>" --vars-file "<Model-dir>/vars.txt" \
  --sim-file "<Model-dir>/_wsm_simulate_temp/<result>.sim" --suggest --max-curves 8 > "<Model-dir>/figs.json"
```

`<result>.mat` is the file named by `simulation.resultFile` in `simulate.out.json`; the `.sim`
file sits next to it with the same stem (swap the `.mat` extension for `.sim`).
Passing `--sim-file` is what stops protected variables from being suggested — without it, a
protected variable in the result is offered as a curve and then renders blank in System Modeler.

The suggestion is a **starting point** — refine `figs.json`: drop parameters/noise, split into
multiple `plots` by physical quantity, set titles/legends/axis units. Passing `--vars-file` to the
`--annotate` step also warns when a curve references a variable absent from the result; passing
`--sim-file` there additionally warns when a curve references a protected variable.

### 3b. Title, caption, and reference alignment

Every figure should be self-identifying and self-explaining:

- **Title** — name the quantity shown, not "Plot 1" (e.g. `"Refrigerant pressure"`). The title is
  how the user finds the plot in the model's figure list, so make it scannable.
- **Caption** — set a one-line `caption` on *every* `Figure` saying what it shows and what to look
  for (e.g. "Pressure rises with the accumulation after the step"). It renders beneath the plot in
  System Modeler. Use `%[label](variable:ref)` to link a variable inside the caption.
- **Default** — mark exactly one figure `preferred = true` so it opens by default.
- **Reference alignment** — if the model implements a **published reference** (a paper, app note,
  textbook) and that reference numbers its figures, name the model's figures to match it
  (`"Fig. 6 - Stored refrigerant mass"`) and state the correspondence in the caption ("compare
  Fig. 6 of <citation>"). This makes a replication auditable at a glance — anyone can line the
  stored plot up against the source. When no reference is given, use your own clear, ordered
  scheme (e.g. `"Evaporator 1 - Outlet vapour quality"`).

### 3c. Markers — mark a time or a level (optional)

Add markers when the user asks to mark, measure or label something on a plot, or when a caption
makes a claim ("settles in 13 s") that a marker makes visible. Keep them few: two or three that
support the caption beat a marker on every extremum.

If the user gives the numbers ("a line at 3 bar", "mark t = 2.5 s"), write the markers into the
spec directly. Otherwise simulate (as in Mode B) and let `mat_features.py` find the positions and
add the markers to a figure of the spec. Each feature is `VAR:KIND[:ARG]`:

| Feature | Marker |
|---------|--------|
| `s:max`, `s:min` | vertical line at the time of the extremum |
| `s:at:2.5` | vertical line at t = 2.5 s |
| `s:settle:0.02` | vertical line at the settling time: within 2 % of the step of its final value, or of its largest deviation from it when `s` returns to where it started; fails if `s` is still outside that band in the last 10 % of the run |
| `s:cross:0.5` | horizontal line at the level 0.5, in the unit the marker is written in |
| `s:final`, `s:initial` | horizontal line at the final / initial value |

```bash
python3 "<scripts-dir>/mat_features.py" "<Model-dir>/_wsm_simulate_temp/<result>.mat" s:min s:settle:0.02 \
  --spec "<Model-dir>/figs.json" --figure response --plots states
```

Horizontal lines are written in the unit the plot's y axis shows (the plot's `Axis.unit`, else the
variable's `displayUnit`); pass `--unit bar` to choose it, which also sets the unit of a `cross`
level. Run it once per group of plots that share a y axis. Without `--spec` it prints the markers
as JSON; for a mapping spec, name the class with `--class`. Re-running a feature replaces its marker. Labels carry the measured value; the `final`
label uses `%{var}`, so it stays correct after the model changes.

### 4. Preview — dry-run diff

```bash
python3 -m PlotAnnotate.main --file "<Model.mo>" --class "<Model>" --spec "<Model-dir>/figs.json" --annotate
```

Shows the unified diff without writing. `--vars-file "<Model-dir>/vars.txt"` adds membership warnings,
and `--sim-file "<Model-dir>/_wsm_simulate_temp/<result>.sim"` warns on any curve that references a
protected variable. `--force` regenerates over an existing `figures` block.

### 5. Apply — write in place

```bash
python3 -m PlotAnnotate.main --file "<Model.mo>" --class "<Model>" --spec "<Model-dir>/figs.json" --annotate --write
```

Re-running without `--force` is a no-op for already-annotated classes (idempotent).

### 6. Validate — confirm the model still flattens (validate-modelica gate)

Annotations must not change the flatten result, and System Modeler must accept every part of the
figures. `--figures` has the kernel parse them as System Modeler does when it opens the plots.

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate --figures --model "<Model.mo>" --name "<Package.Model>" --timeout 90
```

Parse `_wsm_validate_temp/validate.out.json` (a JSON array — take `[0]`; field reference:
[Appendix → Reading the JSON output](#reading-the-json-output)) and check
`status.flatten == "Pass"`. If it passed before annotating but fails after, that's a bug in the
annotation, not the user's model — report it. The launcher also prints a `figures  :` line and
exits non-zero, listing each part System Modeler would ignore (a malformed curve, an unknown
attribute, a misspelled `MarkerPosition`); fix those in the spec and regenerate rather than
editing the `figures` block by hand. Then remove the temp dir.

## Notes and edge cases

- **Pick an instantiable model for the kernel steps**, not the package — use a nested model's full
  dotted name. See [Appendix → Picking the model name](#picking-the-model-name).
- **`figures` is inherited.** A class's figures = its own plus those from base classes. Keep
  `Figure.identifier`s unique across that whole collection (the engine checks within one spec; it
  can't see base-class figures, so choose distinct identifiers when extending).
- **Result-references only.** To plot a derived quantity, add a variable for it in the model and
  reference that — `Curve.y` cannot be an expression like `s + v`.
- **No protected variables in curves.** System Modeler stores protected variables in the result
  `.mat` (so `plot_mat.py --list` shows them), but a stored figure resolves curves against the
  public result tree only — a curve on a protected variable renders **blank**, and the model still
  flattens, so the validate gate won't catch it. The `.sim` file beside the `.mat` marks them
  (`protected="true"`); pass it as `--sim-file` to `--suggest`/`--annotate` so they are dropped and
  flagged. If you must show a protected quantity, expose it through a public variable in the model.
- **X vs. Y (parametric) curves are supported.** `Curve.x` defaults to `time`, but any
  result-reference works (`Curve(x = x, y = y)`), and System Modeler renders the
  variable-vs-variable curve natively. Same rules as `y`: a result-reference (no expressions),
  and a protected variable renders blank on either axis. Don't mix time-based and X-vs-Y curves
  in one `Plot` — all curves share the plot's x axis (the engine warns on this); use separate
  plots. Label both axes, since the default "time" x-label no longer applies. A vertical marker
  on an X vs. Y plot sits at a value of the x variable, not at a time, so restrict
  `mat_features.py`'s time features (`max`, `min`, `at`, `settle`) to time-based plots with
  `--plots` (it refuses otherwise).
- **Marker positions are numbers.** A marker does not move when parameters change; after
  re-tuning, re-simulate, re-run `mat_features.py` and regenerate with `--force`.
- **Units.** A non-empty `Axis.unit` must be compatible with the plotted variable's unit, or the
  model won't flatten; leave `unit = ""` to let the tool choose per-curve units.
- **Idempotency / regen.** Default runs never duplicate a `figures` block; use `--force` to
  regenerate after editing the spec — but it discards the existing figures (hand-written included),
  so confirm with the user first (see the caution near the top).
- **MSL dialect (this toolchain ships MSL 4.x).** Annotations don't affect flattening, but if the
  *model* uses 3.2 names it fails the gate for unrelated reasons — see
  [Appendix → MSL 4.x dialect](#msl-4x-dialect).

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
