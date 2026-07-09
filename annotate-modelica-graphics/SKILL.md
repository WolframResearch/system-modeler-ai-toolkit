---
name: annotate-modelica-graphics
description: "Add Modelica graphical annotations (Icon + Diagram) to a text-only .mo model so it renders as a clean, laid-out schematic in Wolfram System Modeler. Use this skill whenever a model has no icons or diagram, or the user asks to add graphics, draw icons, lay out the diagram, place components, or make a model look right when opened in System Modeler. Triggers on phrases like 'add an icon to this model', 'lay out the diagram', 'the model has no graphics', 'make this render in System Modeler', 'add Placement/Line annotations', 'give these components icons', 'create a schematic'."
---

# Annotate Modelica Graphics

This skill adds graphical annotations to a text-only Modelica `.mo` file so it renders as a
clean schematic in Wolfram System Modeler. It is a **self-contained source transform** — it
parses the `.mo`, classifies each class, and splices annotations back into the source:

- **Category classes** (packages, runnable examples, records, functions) get the idiomatic
  `extends Modelica.Icons.*;` base — the same icons the Modelica Standard Library uses.
- **Leaf components / sub-circuit building blocks** get a custom `Icon(graphics=…)` with their
  connectors anchored on the icon boundary. This works for **any domain** — connector detection
  spans every Modelica Standard Library domain (electrical, mechanical, rotational/translational,
  MultiBody, control signals, thermal/heat, fluid, magnetic, digital, …) plus any `connector`
  class defined in the file itself. Recognized component kinds get a hand-drawn glyph
  (transistor, amplifier, tank, pump, valve, pipe, heat capacitor); anything else gets a generic
  block placeholder **that you are expected to replace with an icon you draw from the component's
  name and description** (see step 3b — this is a normal part of the workflow, not an edge case).
- **Connectors** get their own domain-colored square icon. When the domain is recognized the
  color is automatic; when it isn't, you author the symbol the same way as for components.
- **Composite models** get an auto-laid-out **Diagram**: each component instance gets a
  `Placement`, and every `connect(…)` gets an orthogonal, domain-colored connection `Line`.

It is **idempotent**: re-running only fills in what is missing (use `--force` to regenerate).
By default it prints a dry-run diff; nothing is written until you pass `--write`.

> **`--force` is destructive — ask the user first.** It strips **every** `Placement`, connection
> `Line`, `Icon(...)`, `Diagram(...)`, and `extends Modelica.Icons.*` in scope and regenerates them
> from scratch. The tool leaves no marker, so it matches by shape, not provenance: **hand-written
> and hand-tuned annotations are deleted too** (custom placements, manual line routing, bespoke icon
> graphics). Do not pass `--force` on a model that may carry hand-authored graphics without first
> confirming with the user that discarding it is intended. Review the dry-run diff (no `--write`)
> to see exactly what would be removed before applying.

The engine is pure Python (standard library only) — no third-party packages or WSMKernelX are
needed to generate the annotations. WSMKernelX is used only afterwards, as a safety gate, to
confirm the edited file still flattens.

## Running the annotator

The annotator lives in the `Schematic/` package next to this file. Run it as a module **from
this skill's directory** so the package is importable:

```bash
cd "<this-skill-dir>"
python3 -m Schematic.main --file "<path-to-Model.mo>" --analyze
```

`<this-skill-dir>` is the folder containing this `SKILL.md` (use `python` instead of `python3`
on Windows if that's what's on PATH). The only argument that must be an absolute or
correctly-relative path is `--file`.

## Cross-platform launcher (for the validation gate in step 5)

> The validation gate in step 5 uses the shared launcher `scripts/wsm_run.py`.
> Read [the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills) (launcher resolution, shell
> rules, temp dir, JSON-array output, MSL 4.x notes) before that step. In a normal
> install the launcher is `../scripts/wsm_run.py` (`<scripts-dir>` is the shared
> `scripts/` folder); if that path doesn't exist, see
> [Appendix → Locating the launcher](#locating-the-launcher).

## Workflow

### 1. Identify the model file

The user gives a `.mo` path, or you are already working with one. The file may be a `package`
with several nested `model`s — the tool handles all of them in one pass.

### 2. Analyze — see what each class will receive

```bash
python3 -m Schematic.main --file "<Model.mo>" --analyze
```

This prints every class with its category and what it would get (a standard `Modelica.Icons.*`
icon, a custom icon, and/or a diagram layout), plus its connectors / instances / connects.
Present this to the user and confirm the scope. By default all non-trivial classes are
annotated; restrict with `--class <Name>` if the user wants just one.

**Read the `glyph:` line under each leaf and connector.** Recognized ones name a built-in glyph
or a domain color. Unrecognized ones say `domain unrecognized — author …` and are collected in an
`Unrecognized classes/connectors` list at the end. **Treat that list as a work item: you must
author a glyph for each entry in step 3b before applying.** Do not ship the generic-block /
neutral-square placeholder when you have a name and description to draw from.

### 3. Preview — dry-run diff

```bash
python3 -m Schematic.main --file "<Model.mo>" --annotate
```

Shows the unified diff without writing. Summarize what will be added (icons, placements,
connection lines). Useful flags:
- `--class <Name>` — only that nested class.
- `--no-glyphs` — plain rounded-rectangle icons instead of typed glyphs.
- `--extent N` — force the diagram coordinate system to `{{-N,-N},{N,N}}`.
- `--force` — strip **all** graphical annotations (including hand-written ones) and regenerate;
  destructive, so confirm with the user first (see the caution above).
- `--glyphs-file <json>` — supply your own icon glyphs for named classes (see step 3b).

### 3b. Author glyphs for unrecognized classes and connectors (required when the list is non-empty)

The tool recognizes every Modelica Standard Library domain and draws those automatically. For
anything it can't recognize — a custom component or a connector in a domain outside the MSL — it
emits a placeholder (generic block / neutral square) and lists the class in
`Unrecognized classes/connectors`. **For each listed name, you (the LLM running this skill) draw
a real icon from the component's name and description.** This is expected, not exceptional:
the engine deterministically handles layout, placement, colors and recognized glyphs; you supply
domain knowledge for the long tail.

For each unrecognized entry:
1. Read its `description`, its connectors, and (if helpful) its equations to decide what it *is*
   and what it should look like.
2. Express that as Modelica graphic **primitives** — `Rectangle`, `Ellipse`, `Line`, `Polygon`,
   `Text`, etc. — in the `{{-100,-100},{100,100}}` icon frame. A **component** gets a
   representative symbol (leave room where pins sit); a **connector** typically gets a single
   filled `Rectangle`/`Ellipse` spanning the frame in a sensible domain color.

Write a JSON file mapping each class name to its glyph and (optionally) which edge each connector
sits on, then pass it with `--glyphs-file`:

```json
{
  "Membrane": {
    "graphics": [
      "Rectangle(extent={{-40,-90},{40,90}}, lineColor={90,90,90}, fillColor={210,225,235}, fillPattern=FillPattern.Solid)",
      "Line(points={{0,90},{0,-90}}, color={90,90,90}, pattern=LinePattern.Dash)"
    ],
    "ports": {"feed": "L", "permeate": "R"}
  }
}
```

- `graphics` — a list of primitive strings spliced verbatim into `Icon(graphics={…})`. A `%name`
  label is added automatically (set `"name_text": false` to suppress it). Keep shapes within
  `±100` and put nothing where a connector pin will sit.
- `ports` — optional `connector → "L"|"R"|"T"|"B"` map. Omitted ports fall back to the
  name-based heuristic. The tool computes the exact pin coordinates on that edge. (Irrelevant
  for a `connector` class itself, which has no sub-connectors — give it `graphics` only.)
- A bare list value (`"Membrane": ["Rectangle(...)", …]`) is accepted as graphics-only.

The JSON can target **both components and connectors** in one file — key every unrecognized name
from the analyze list. Example connector entry: `"MolarPort": {"graphics": ["Ellipse(extent=
{{-100,-100},{100,100}}, lineColor={0,140,90}, fillColor={120,220,170}, fillPattern=
FillPattern.Solid)"]}`. Then preview/apply as usual with the same `--glyphs-file` argument; the
connectors are still placed and (when instantiated) routed automatically.

### 4. Apply — write in place

```bash
python3 -m Schematic.main --file "<Model.mo>" --annotate --write
```

Re-running without `--force` is a no-op for already-annotated classes (idempotent).

### 5. Validate — confirm the model still flattens (use the validate-modelica gate)

Annotations must not change the flatten result. Confirm with the shared launcher (this is the
`validate-modelica` skill's gate). Target a **concrete instantiable model**, not the package:

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate \
  --model "<Model.mo>" --name "<Package>.<ModelName>" --timeout 90
```

Parse `_wsm_validate_temp/validate.out.json` (a JSON array — take the first element; field
reference: [Appendix → Reading the JSON output](#reading-the-json-output))
and check `status.flatten == "Pass"`. A Pass confirms the edits didn't corrupt the source. If it
Fails after annotating but passed before, report it — that's a bug, not the user's model. Then
remove the temp dir (`rm -rf "<Model-dir>/_wsm_validate_temp"`).

## Notes and edge cases

- **Pick an instantiable model for the gate**, not the package (e.g. `OTAlib.VCA`) — see
  [Appendix → Picking the model name](#picking-the-model-name).
- **Multi-name declarations** (`Pin b, c, e;` or `PNP Q3, Q4;`) are split into one declaration
  per component so each gets its own placement. This is a structural rewrite but semantically
  identical; it flattens to the same model.
- **Layout is heuristic, not pixel-perfect.** Components are laid out left-to-right by signal
  flow (feedback loops handled), grounds pinned to the bottom and supplies to the top, with
  orthogonal connection routing between connector *pins* — each line terminates exactly on the
  pin anchor (instance origin + the connector's icon-edge offset) and leaves it perpendicular to
  that edge, so the rendered line is right-angled end to end with no diagonal bridge from the
  pin; interior waypoints snap to a grid. Pin offsets come from the model's own leaf/sub-circuit icons and a heuristic table for
  standard-library components (resistors, sources, ground, blocks). Library components render
  with their own MSL icons; only domain leaves without an MSL equivalent get a custom icon. The
  user can fine-tune positions afterward in System Modeler.
- **Two-terminal components are rotated to avoid wrap-around.** A component with two pins on
  opposite left/right edges (resistor, capacitor, inductor, …) is stood up vertically
  (pins top/bottom) when both its neighbours sit on the same horizontal side or are separated
  more vertically than horizontally — so the two connection lines fan out instead of one
  wrapping around the body. Sources, grounds and supplies keep their orientation.
  *Known limitation:* a connection to a class connector that is **inherited** (declared in an
  extended base, not in this class) is emitted as a harmless zero-length stub, since the
  inherited connector has no diagram placement to anchor to.
- **Idempotency / re-layout.** Default runs never duplicate annotations. To re-generate (e.g.
  after editing the model's connections), pass `--force` — but it discards all existing graphics,
  hand-written included, so confirm with the user first (see the caution near the top).
- **MSL dialect (this toolchain ships MSL 4.x).** Annotations don't affect flattening, but if the
  *model* uses 3.2 names it will fail the gate for unrelated reasons (`Modelica.Units.SI.*`, source
  param `f`, `uses(Modelica(version="4.0.0"))`) — see
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
