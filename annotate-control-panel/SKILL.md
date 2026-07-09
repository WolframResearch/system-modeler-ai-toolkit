---
name: annotate-control-panel
description: "Add Wolfram System Modeler control-panel (Explore) annotations (__Wolfram(ControlPanels(Panel(...)))) to a .mo model so it opens with interactive sliders, checkboxes, input fields and popup menus in Simulation Center's Explore view. Use this skill whenever the user wants to add a control panel or Explore panel, make a model interactive, expose parameters as sliders/controls, or let someone tune parameters and re-simulate from the GUI. Triggers on phrases like 'add a control panel', 'add an explore panel', 'make interactive sliders', 'expose these parameters as controls', 'let me tune parameters in Simulation Center', 'add controls to this model'."
---

# Annotate Control Panel

This skill writes the Wolfram **control-panel** (Explore) annotation into a Modelica `.mo` file so a
model carries its own interactive panels — the sliders, checkboxes, input fields and popup menus that
Simulation Center's **Explore** view shows for driving parameters and start values, plus the plots to
display:

```modelica
annotation(__Wolfram(ControlPanels(
  Panel(
    identifier = "id1",
    title = "Controller tuning",
    elements = {
      Slider(variable = Kp, label = "Proportional gain", min = 0, max = 100),
      Slider(variable = Kd, min = 0, max = 20, scale = Log()),
      Checkbox(variable = useFeedforward, label = "Feedforward")},
    figures = {"response"})));
```

It is a **self-contained source transform**: Claude assembles a *control-panel spec* (JSON) — from the
user's request, or suggested from the model's parameters — and the Python engine renders it to the
`__Wolfram(ControlPanels(...))` vendor annotation and splices it into the class annotation. The engine
is pure Python (standard library only); WSMKernelX is used only afterwards as a validation gate.

This is a **vendor-specific annotation** (Modelica spec §18.1): other tools ignore it and preserve it
on save, and it does not affect flattening — it just tells System Modeler how to build the Explore
panels. It sits directly inside `annotation(...)`, as a sibling of `experiment` and `Documentation`
(never nested inside `Documentation`).

It is **idempotent**: a class that already has control panels is skipped unless you pass `--force`
(which strips the old `ControlPanels` block and regenerates). By default it prints a dry-run diff;
nothing is written until `--write`.

> **`--force` is destructive — ask the user first.** It deletes the class's existing control panels
> before regenerating, so any hand-tuned panels there are lost. Don't pass `--force` on a class that
> already carries control panels without confirming that discarding them is intended. Review the
> dry-run diff (no `--write`) to see exactly what would be removed.

## The control-panel spec (JSON)

A model has a list of **panels**; each panel has a list of **controls** and an optional list of
**figures** (plot identifiers to show). Only fields you set are emitted:

```json
{
  "panels": [
    {
      "identifier": "id1",
      "title": "Controller tuning",
      "controls": [
        {"type": "slider",     "variable": "Kp", "label": "Proportional gain", "min": 0, "max": 100},
        {"type": "slider",     "variable": "Kd", "min": 0, "max": 20, "scale": "Log", "showInputField": false},
        {"type": "checkbox",   "variable": "useFeedforward", "label": "Feedforward"},
        {"type": "inputField", "variable": "mass"},
        {"type": "popupMenu",  "variable": "mode", "items": [{"value": "1", "label": "Fast"}, {"value": "2"}]}
      ],
      "figures": ["response"]
    }
  ]
}
```

Control `type` is chosen from the variable's kind:

- **`slider`** — a `Real`/`Integer` parameter or start value. Requires numeric `min` and `max`.
  Optional `"scale": "Log"` for a logarithmic slider, and `"showInputField": false` to hide the
  numeric field beside the handle (it defaults to shown).
- **`inputField`** — a typed value for a `Real`/`Integer`/`String`.
- **`checkbox`** — a `Boolean`.
- **`popupMenu`** — an enumeration or Boolean. Give `items` as `{"value": <token>, "label": "…"}`;
  `value` is emitted verbatim, so use a bare token for a number/enumeration (`"2"`,
  `"MyEnum.fast"`) and include quotes for a `String` value (`"\"idle\""`).

Rules the engine enforces:
- Each control's `variable` is a **component reference** (e.g. `Kp` or `controller.gain[1]`) — the
  parameter/start value to control. It is emitted unquoted, as System Modeler expects.
- A `slider` must have finite numeric `min`/`max`.
- Each panel needs a unique, non-empty `identifier` and a `title`.
- `figures` entries are `Figure` identifiers that must exist in the model's stored figures
  (written by the `annotate-modelica-plots` skill); the first listed is the panel's default plot.

## Running the annotator

The annotator lives in the `ControlPanel/` package next to this file. Run it as a module **from this
skill's directory** so the package is importable:

```bash
cd "<this-skill-dir>"
python3 -m ControlPanel.main --file "<path-to-Model.mo>" --analyze
```

Use `python` instead of `python3` on Windows if that's what's on PATH. Only `--file` (and `--spec`,
`--sim-file`) must be absolute or correctly-relative paths.

## Cross-platform launcher (for the validate step)

> The validate step below calls the shared `scripts/wsm_run.py`. Read
> [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills) (launcher resolution, shell rules, temp dir,
> JSON-array output, MSL 4.x notes) before it. In a normal install the launcher is
> `../scripts/wsm_run.py` (`<scripts-dir>` is the shared `scripts/` folder); if that path doesn't
> exist, see [Appendix → Locating the launcher](#locating-the-launcher).

## Workflow

### 1. Identify the model file and target class

The user gives a `.mo` path. Pick a **concrete instantiable model** (`Package.Model`, not the
package) — see [Appendix → Picking the model name](#picking-the-model-name).
Control panels belong on the model you actually simulate.

### 2. Analyze — see classes, panel status, and controllable parameters

```bash
python3 -m ControlPanel.main --file "<Model.mo>" --analyze
```

Lists every class, flagging `HAS control panels`, and lists the target class's controllable
parameters with their kind (numeric / boolean / string / other) and default. Present this and
confirm scope. Target a specific class with `--class <Name>`.

### 3. Choose the controls

Expose the parameters a user would actually want to turn — gains, setpoints, masses, switches,
mode selectors — not every constant in the model. Prefer a small, meaningful panel.

**Mode A — user-specified.** The user names the parameters (and ranges). Build the spec JSON
directly from their request and skip to step 4.

**Mode B — suggest from the model's parameters.** When the user doesn't name them, let the tool
propose a starting spec from the class's parameter declarations:

```bash
python3 -m ControlPanel.main --file "<Model.mo>" --class "<Model>" --suggest --max-controls 12 > "<Model-dir>/panels.json"
```

It picks a control per parameter by type (slider for numeric with a first-guess range around the
default, checkbox for Boolean, input field otherwise) — a **starting point**. Refine
`panels.json`: drop parameters that shouldn't be exposed, set real slider `min`/`max`, add labels,
switch an enumeration to a `popupMenu` with `items`, and split into multiple panels if useful.

**Optional — check against a built model.** If the model has been built or simulated, pass the
`.sim` init file (beside the result `.mat`, same stem) so the tool confirms each controlled
variable exists and is runtime-tunable, warning on structural (constant-folded) parameters that
can't be changed from a panel without a rebuild:

```bash
python3 -m ControlPanel.main --file "<Model.mo>" --class "<Model>" \
  --spec "<Model-dir>/panels.json" --annotate --sim-file "<Model-dir>/_wsm_simulate_temp/<Model>_res.sim"
```

### 3b. Labels, ranges, and linking plots

- **Label** — give each control a short `label` (the parameter's description is a good default). It
  is what the user sees next to the slider/box.
- **Range** — set slider `min`/`max` to the span worth exploring, not just around the default. Use
  `"scale": "Log"` when the interesting range spans orders of magnitude.
- **Title** — name the panel for what it controls (e.g. `"Controller tuning"`), not "Panel 1".
- **Plots** — list `figures` (by `Figure` identifier) so the panel shows the relevant plot as you
  drag. The identifiers must already exist in the model's stored figures; add them first with the
  **annotate-modelica-plots** skill if they don't. The first listed figure is the default plot.

### 4. Preview — dry-run diff

```bash
python3 -m ControlPanel.main --file "<Model.mo>" --class "<Model>" --spec "<Model-dir>/panels.json" --annotate
```

Shows the unified diff without writing. Warnings surface unknown/structural variables, control-type
mismatches, and figure ids with no stored Figure. `--force` regenerates over existing panels.

### 5. Apply — write in place

```bash
python3 -m ControlPanel.main --file "<Model.mo>" --class "<Model>" --spec "<Model-dir>/panels.json" --annotate --write
```

Re-running without `--force` is a no-op for classes that already have control panels (idempotent).

### 6. Validate — confirm the model still flattens (validate-modelica gate)

The annotation must not change the flatten result.

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate --model "<Model.mo>" --name "<Package.Model>" --timeout 90
```

Parse `_wsm_validate_temp/validate.out.json` (a JSON array — take `[0]`; field reference:
[Appendix → Reading the JSON output](#reading-the-json-output)) and check
`status.flatten == "Pass"`. A vendor annotation is ignored by flattening, so a failure here that
wasn't present before means the annotation is malformed — report it. Then remove the temp dir.

## Notes and edge cases

- **Pick an instantiable model for the kernel step**, not the package — use a nested model's full
  dotted name. See [Appendix → Picking the model name](#picking-the-model-name).
- **Control panels vs. plots.** This skill writes the interactive `__Wolfram(ControlPanels(...))`
  panels; the **annotate-modelica-plots** skill writes the stored `Documentation(figures={...})`
  plots. A panel's `figures` list just *references* figure identifiers from that annotation — add
  the plots there first, then link them here.
- **Bind to parameters and start values.** Controls change the *start value* of a variable or a
  *parameter value* — the things you set before (or, in real-time mode, during) a run. A control on
  a purely computed variable can't do anything useful.
- **Structural parameters.** A parameter that is constant-folded (used in array sizes, conditional
  components, etc.) can't be changed from a panel without rebuilding. Pass `--sim-file` to get a
  warning when a controlled variable is structural or absent from the built model.
- **Enumerations and popup values.** `popupMenu` `items` values are emitted verbatim; use the bare
  enumeration/number token (`"value": "2"`), and quote a `String` value (`"value": "\"idle\""`).
- **Idempotency / regen.** Default runs never duplicate a control-panel block; use `--force` to
  regenerate after editing the spec — but it discards the existing panels, so confirm with the user
  first (see the caution near the top). `--force` preserves other content in `annotation(...)`
  (e.g. `experiment`, `Documentation`).
- **MSL dialect (this toolchain ships MSL 4.x).** The annotation doesn't affect flattening, but if
  the *model* uses 3.2 names it fails the gate for unrelated reasons — see
  [Appendix → MSL 4.x dialect](#msl-4x-dialect).

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
