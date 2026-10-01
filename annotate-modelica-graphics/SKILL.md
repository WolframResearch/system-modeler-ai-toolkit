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
  A **reference component** shared by several components — one `Ground` that four parts
  connect to, one `Fixed` housing, one `FixedTemperature` ambient — is first given one
  instance per connection, so the diagram loses its star of long ground lines and each
  reference sits beside the component it anchors.

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

A `reference <name>: N connections` line appears for each ground / housing / fixed-temperature
reference with enough connections to be worth splitting, saying whether it will be split into
one instance per connection or is kept shared (and why). Mention it when you present the scope
— it is the one change that touches the model's structure rather than only its graphics.
A `warning:` line names a component whose pin positions are guessed, or a connection that
will be drawn as a zero-length stub; mention those too, and check their lines in step 6.

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
- `--extent N` — force the diagram coordinate system to `{{-N,-N},{N,N}}`. The canvas is
  otherwise sized to the layout, growing with the component count, so reach for this only
  to add margin around a diagram the user finds tight — it moves the frame, not the
  components, so it cannot separate two that are too close.
- `--force` — strip **all** graphical annotations (including hand-written ones) and regenerate;
  destructive, so confirm with the user first (see the caution above).
- `--glyphs-file <json>` — supply your own icon glyphs for named classes (see step 3b).
- `--no-split-references` — keep a shared ground / housing / ambient as the single instance
  the user wrote, and rail it along the bottom as before.

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
python3 "<scripts-dir>/wsm_run.py" --mode validate --graphics \
  --model "<Model.mo>" --name "<Package>.<ModelName>" --timeout 90
```

`--graphics` is what makes this gate cover the annotations you just wrote: without it the
`Icon`, `Diagram` and `Placement` annotations are not evaluated, so a shape or field name
that does not resolve passes unnoticed
([Appendix → Checking graphic annotations](#checking-graphic-annotations)).

Parse `_wsm_validate_temp/validate.out.json` (a JSON array — take the first element; field
reference: [Appendix → Reading the JSON output](#reading-the-json-output))
and check `status.flatten == "Pass"`. A Pass confirms the edits didn't corrupt the source. If it
Fails after annotating but passed before, report it — that's a bug, not the user's model. Then
remove the temp dir (`rm -rf "<Model-dir>/_wsm_validate_temp"`).

When references were split, each extra reference adds its own connector (two variables) and two
equations to the flattened model — the same solution, written out more times. If the user wants
that confirmed rather than argued, simulate once before and once after and compare the
trajectories (the `simulate-modelica` skill); they must match exactly.

### 6. Look at the diagram (whenever the Wolfram Language is available)

A flatten Pass says nothing about how the diagram looks. If you can evaluate Wolfram
Language (a Wolfram MCP evaluator, or `wolframscript` on PATH), render each laid-out model with
System Modeler's own renderer and look at the image before reporting back:

```wolfram
Import["<abs-path>/Model.mo", "MO"];
Export["<abs-path>/diagram.png", SystemModel["<Package>.<ModelName>"]["Diagram"], ImageSize -> 700]
```

Check the image for:

- a line that stops short of a pin, overshoots it, or has a diagonal stub at its end;
- a line running through a component's body, or lines from different pins piled onto one
  point;
- a block drawn sideways or upside down;
- a line leaving a component backwards, across its own icon;
- labels overlapping each other or a component.

Fix what you find by editing the offending `Placement` or `Line` by hand (keeping to the
invariants below), then render again. Remove the image when you are done unless the user
wants it.

## Placement invariants

If you ever write a `Placement` by hand instead of letting the tool generate it, keep to the
form below — it is what the tool emits and what Model Center writes back.

```modelica
annotation(Placement(transformation(extent={{-10,-10},{10,10}}, origin={x,y}, rotation=0)));
```

- **`origin` carries the position; `extent` stays centred on `{0,0}`.** A transformation
  applies its attributes in the order `extent`, `rotation`, `origin`: the icon is mapped onto
  `extent`, rotated **about `{0,0}` — not about the `origin` attribute** — and only then
  shifted so `{0,0}` lands on `origin`. So a centred extent makes the component rotate about
  its own centre, and `origin` is the handle the GUI grabs.
- **Never bake the position into `extent`.** `extent={{x-10,y-10},{x+10,y+10}}` with `origin`
  left at its `{0,0}` default draws in the right place, but its rotation centre — and the
  origin marker Model Center shows — sits at the coordinate system origin instead of on the
  component. Rotating or dragging it then behaves oddly.
- **Mirror by swapping the extent's corners; there is no flip keyword.**
  `extent={{10,-10},{-10,10}}` mirrors the icon left to right, `{{-10,10},{10,-10}}` top to
  bottom, and the mirror is applied before `rotation`. To point a signal block right to
  left (on a feedback path, say) mirror it rather than `rotation=180`: the mirrored block
  keeps its name above and its parameter text below, while the rotated one swaps them. A
  top-to-bottom mirror also swaps them, and turns the glyph over, with the text still upright.
  Turn only physical two-terminal components (resistors, springs, sources) by 90 or 270
  degrees, never a block.
- This rule is specific to `Placement`. Inside `Icon`/`Diagram` `graphics`, a `Line`,
  `Rectangle` or `Text` *does* rotate about its own `origin` attribute, and its geometry is
  relative to that origin.
- **Connection `Line` points are absolute diagram coordinates** (the tool emits no `origin`
  on them), and each endpoint must land on the connector's pin anchor — the component's
  `origin` plus the connector's offset on the icon boundary.

## Notes and edge cases

- **Pick an instantiable model for the gate**, not the package (e.g. `OTAlib.VCA`) — see
  [Appendix → Picking the model name](#picking-the-model-name).
- **Multi-name declarations** (`Pin b, c, e;` or `PNP Q3, Q4;`) are split into one declaration
  per component so each gets its own placement. This is a structural rewrite but semantically
  identical; it flattens to the same model.
- **A shared reference component is given one instance per connection.** A *reference* fixes
  the absolute potential of a physical network and has one connector on which it prescribes
  the **effort** and leaves the **flow** free: `Electrical.Analog.Basic.Ground`,
  `Mechanics.Rotational`/`Translational.Components.Fixed`,
  `Thermal.HeatTransfer.Sources.FixedTemperature`, the magnetic `Ground`s, and any `Ground`
  model defined in the file itself. Because each copy absorbs whatever flow reaches it, N
  instances behave exactly like one instance shared by N connections — so from three
  connections up the tool replicates it (`ground`, `ground2`, `ground3`, …) and parks each
  copy beside the component it anchors. Like the multi-name split this is a structural rewrite
  with identical behaviour, and re-running is a no-op because nothing is shared any more.
  Never applied to a **flow-prescribing** source (`FixedHeatFlow`, `ConstantCurrent` — copies
  would each inject the full amount), to a `Fluid` boundary (also a flow *path* between the
  connections it joins), or to an `inner` singleton (`MultiBody.world`, `Fluid.System`):
  these are not references to the tool, so `--analyze` says nothing about them. A reference
  it *does* recognise is still kept shared when it is declared `inner`/`outer` or as an
  array, when its name is a quoted identifier, or when an equation reads it (`ground.p.i`) —
  and there `--analyze` names the reason. `--no-split-references` turns the pre-pass off.
  The split only runs for a class that is getting a **newly laid-out** diagram, so re-running
  over a model you already laid out by hand stays the no-op it advertises. It is also the one
  edit `--force` cannot undo: `--force` strips graphics, not the extra instances.
- **Layout is heuristic, not pixel-perfect.** Groups of components with no connection
  between them are laid out as separate bands, one under the other. Within a band:
  - An electrical network of two-terminal components with a ground is drawn as a ladder:
    series components along a top wire, the others standing between it and the ground, each
    ground under the component it grounds.
  - Anything else flows left to right. Signal direction (output to input) sets the order, a
    block that only feeds a signal back sits on a return row below the forward path, and each
    component moves up or down so its pins line up with its neighbours'. Blocks are never
    rotated; a block on a return row is mirrored. A two-terminal electrical component with a
    grounded pin stands up with that pin at the bottom.
  - A reference with a single connection is parked beside the pin it connects to, and one
    shared by several sits below their pins where there is room, else on a rail along the
    bottom; supplies rail along the top.
  - Last, each component is tried mirrored left to right, top to bottom and both, and a flip
    is kept where it makes that component's lines shorter, with fewer bends or crossings — a
    sensor that closes a loop turns its output toward the return row, a block with a second
    input takes it on the side the signal comes from. A top-to-bottom flip has to pay for
    moving the name below the icon, so it is taken only when it clearly helps. The references
    are then placed again, beside the pins as they now face.

  Every line ends exactly on its pin, leaves the pin in the direction the pin faces, goes
  around component bodies and their labels, and crosses or runs close to lines of other nets
  only where no short detour avoids it. Pin positions come from
  the model's own classes and, for Modelica Standard Library components, from a table read
  off the library's source; type names brought in by `import` are resolved first. For any
  other class (one from another library, say) the pins are guessed from the connector names,
  and a `warning:` line names the component. The user can fine-tune positions afterward in
  System Modeler.
- *Known limitations.* A long chain stays on one row rather than wrapping, and densely
  cross-coupled circuits (bridges, differential stages) get a readable but untidy layout —
  step 6 is where you catch and fix those. A connection to a class connector that is
  **inherited** (declared in an extended base, not in this class) is emitted as a harmless
  zero-length stub, since the inherited connector has no diagram placement to anchor to,
  and reported in a `warning:` line.
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
