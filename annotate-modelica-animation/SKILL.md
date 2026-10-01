---
name: annotate-modelica-animation
description: "Add Wolfram System Modeler 3D-animation annotations (__Wolfram(Animation(cameras, windows))) to a MultiBody .mo model — stored cameras (fixed or following an object), trace paths, auto-play/repeat, time scale, ground grid and force-vector scaling — so the model opens with a ready-made animation in Simulation Center. Use this skill whenever the user wants to add or store an animation, camera, camera follow mode, trace path, or animation window settings in a model, attach a CAD shape, or make a MultiBody animation presentation-ready. Triggers on phrases like 'add a camera to the model', 'store the animation', 'follow the body with the camera', 'add a trace path', 'top/side/front view', 'animate this multibody model', 'attach a CAD file', 'the animation opens empty'."
---

# Annotate Modelica 3D Animation

Adds `__Wolfram(Animation(...))` annotations to a MultiBody model so Simulation
Center opens a configured 3D animation: named cameras, follow cameras, trace
paths, playback behavior and vector scaling — all stored in the model file.

Only models using `Modelica.Mechanics.MultiBody` components with a visual
representation get an Animation view. Simulate first (`simulate-modelica`):
you need the trajectory extents to place cameras and size the scene, and a
model that fails to simulate has no animation to configure.

Unlike the control-panel, graphics and plots annotators, this skill has no
generator engine — you author the annotation text and splice it in by hand,
then validate. That puts the merge-into-`annotation(...)` step (below) on you;
get it right and confirm with `validate-modelica`. Because the edit is yours
rather than a script's, it is also on you to leave the file's line endings as you
found them — see
[Appendix → Line endings in .mo files](#line-endings-in-mo-files).

This is a **vendor-specific annotation** (Modelica spec §18.1): other tools
ignore it and preserve it on save, and it does not affect flattening — it only
tells System Modeler how to build the 3D animation. It sits directly inside the
class `annotation(...)`, as a sibling of `experiment` and `Documentation`
(never nested inside `Documentation`).

## The annotation

```modelica
annotation(__Wolfram(Animation(
  cameras = {
    Camera(name = "Follow", distance = 8, rotation = {0.5, 0.5, 0.5, 0.5},
           follow = bodyShape.shape1, followMode = "NODE_CENTER_AND_AZIM"),
    Camera(name = "Top", center = {32, -19, 0}, distance = 90, rotation = {0, 0, 0, 1})},
  windows = {
    Window(name = "Default", camera = "Follow", preferred = true,
           autoPlay = true, repeat = true, timeScale = 0.5,
           trace = {bodyShape.shape1},
           vectorSettings = {VectorSettings(quantity = "Force", scale = 0.1)})})));
```

### Splicing it into the model

The `Animation(...)` goes inside the **single** class-level `annotation(...)`, as
a sibling of `experiment`/`Documentation` — not in its own second `annotation`.

- **No class annotation yet** — add one before the terminating `end <Class>;`:

  ```modelica
    annotation(__Wolfram(Animation(...)));
  end MyModel;
  ```

- **An `annotation(...)` already exists** (e.g. `experiment`) — add `__Wolfram`
  as another argument inside it, don't create a second block:

  ```modelica
    annotation(
      experiment(StopTime = 10),
      __Wolfram(Animation(...)));
  ```

- **A `__Wolfram(...)` already exists** (e.g. from FMI or a control panel) — add
  `Animation(...)` as another argument inside that same `__Wolfram(...)`, rather
  than a second `__Wolfram`:

  ```modelica
    annotation(__Wolfram(
      FMI(version = "2.0", kind = "ME"),
      Animation(...)));
  ```

Two `annotation(...)` blocks on one class, or two `__Wolfram(...)` inside one
annotation, is invalid — merge instead. If the class already carries an
`Animation(...)`, edit that one rather than adding a second.

### Camera fields

- `name`, `center = {x,y,z}`, `distance`, `rotation = {q1,q2,q3,q4}` (quaternion).
  `center` is ignored when `follow` is set (a follow camera derives its center
  from the tracked object), so omit it on follow cameras.
- `follow = <cref>` attaches the camera to a shape. **The cref must be the
  low-level visualizer instance inside the component (its
  `Visualizers.Advanced.Shape`/`Arrow`/`Surface`), not the component itself** —
  `follow = bodyShape` is ignored and the camera stays unattached. That leaf
  name depends on the component: `vis` for `Visualizers.FixedShape`, `shape` for
  `FixedShape2`/`Parts.Fixed`, `shape1` (and `shape2` for the CM sphere) for
  `Parts.BodyShape`, `cylinder`/`sphere` for `Parts.Body`, `sphere` for
  `PointMass`, `arrow` for `WorldForce`/`SignalArrow`, and a nested path like
  `frameTranslation.shape` for `BodyBox`/`BodyCylinder`. The reliable way to get
  the exact cref is to pick the shape in Simulation Center (right-click →
  Camera Follow Mode, or Trace) and keep the cref it stores.
- `followMode`: `"NODE_CENTER"` (Object Center), `"NODE_CENTER_AND_AZIM"`
  (Object Center and Azimuth), `"NODE_CENTER_ROTATION"` (Object Center and
  Rotation). For fast-spinning bodies avoid `NODE_CENTER_ROTATION` — the camera
  spins with the body; `NODE_CENTER_AND_AZIM` gives a natural chase view.

### Window fields

- `camera = "<name>"`, `preferred = true` (open automatically after the first
  simulation), `autoPlay = true`, `repeat = true`, `timeScale = <r>`.
- `trace = {<cref>, ...}` draws trace paths, using the same low-level visualizer
  crefs as `follow` above (e.g. `bodyShape.shape1`, not `bodyShape`).
- `groundGrid = false` hides the ground grid. Omit the field to keep the grid:
  a stored `false` re-applies every time the window opens, so remove it from
  the annotation rather than toggling in the viewer.
- `vectorSettings = {VectorSettings(quantity = "Force", scale = <m/N>,
  diameter = <r>)}` and `defaultVectorDiameter = <r>` scale MSL 4.x vector
  visualizers (e.g. `WorldForce` arrows).

### Quaternion starting points (z-up world)

| View | `rotation` |
|------|-----------|
| Top (looking down −z) | `{0, 0, 0, 1}` |
| Horizontal, looking along −x | `{0.5, 0.5, 0.5, 0.5}` |
| Horizontal, looking along +y | `{0.7071, 0, 0, 0.7071}` |

If the ground renders vertical, the camera's up-axis is wrong — start from one
of these and adjust, or set the camera in Simulation Center once ("Add Camera
to Model") and keep the numbers it writes.

## Workflow

1. Simulate; read the motion extents from the results.
2. Add a ground plane so motion reads against a fixed reference — size it from
   the simulated extents plus margin, top surface just below the motion floor:

   ```modelica
   Modelica.Mechanics.MultiBody.Visualizers.FixedShape ground(
     shapeType = "box", lengthDirection = {1, 0, 0}, widthDirection = {0, 1, 0},
     length = 90, width = 60, height = 0.02, r_shape = {-10, -19, -0.03},
     color = {60, 150, 60});
   connect(world.frame_b, ground.frame_a);
   ```

3. Add cameras (a follow camera for playback plus fixed top/side views for
   shareable stills — the window's `trace` applies to every camera).
4. Add one `Window` with playback flags and traces; validate the model
   (`validate-modelica`) and let the user confirm the view in Simulation Center.

After a user stores anything from Simulation Center's animation dialogs, diff
the annotation: a GUI store rewrites the whole `Window(...)` from the current
viewer state, overwriting `autoPlay`, `repeat`, `timeScale`, `groundGrid` and
`trace` with whatever the viewer happens to show at that moment (e.g. `autoPlay`
becomes whether playback is running, `trace` becomes the currently traced
shapes). So re-apply hand-authored values after a store — do GUI stores first,
hand-edits last.

## CAD shapes

Attach CAD geometry to `FixedShape` / `BodyShape` with
`shapeType = "modelica://<Library>/Resources/<file>.stl"` (ship the file in the
library's `Resources/` folder). For file shapes, `length`/`width`/`height` act
as scale factors (set all three to one scale value), and `lengthDirection` /
`widthDirection` remap the CAD file's axes into the MultiBody frame.

In Wolfram Language, `CreateSystemModel[Import["part.stl"]]` (pass the imported
mesh, not the path) generates a ready part: a `Body` with the full inertia
tensor computed from the geometry plus a matching `FixedShape`, with consistent
axes and the frame at the center of mass.

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
