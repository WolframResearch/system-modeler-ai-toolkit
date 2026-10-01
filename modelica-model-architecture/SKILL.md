---
name: modelica-model-architecture
description: "Architecture and structuring guidance for Wolfram System Modeler / Modelica (.mo) models and libraries. Use this skill BEFORE writing equations whenever creating, implementing, structuring, or refactoring a model or library, to decide component decomposition, connectors, component reuse, file/folder layout, units, and naming. Triggers on phrases like 'create/build a Modelica model', 'implement this model/paper in Modelica', 'make a WSM model', 'write a Modelica library', 'structure this model', 'single .mo file vs directory', 'split this into components', 'refactor this model/library'. Before writing a multi-class library, consult it to choose directory-form (one class per file) storage over a single .mo — also when the library is your own idea, such as a circuit or mechanism modelled to validate something else against it. For a specific component library (e.g. create-hydraulic-model) defer to that domain skill."
---

# WSM / Modelica model architecture

Use this when creating or restructuring a WSM/Modelica model or library —
**before** writing equations. This skill covers the architecture and structuring
decisions that come first (sections 1-7), then the library conventions —
naming, plots, documentation HTML, testing, icons, library shape — that a model
or library must meet before it is "done" (sections 8-9). Read sections 8-9
before declaring a library done.

The default in Modelica is **object-oriented decomposition into reusable
components**. Reach for a flat all-in-one model only under the explicit
exception in section 5.

## Working method

- Propose a **step-by-step** plan and wait for explicit approval before any edit.
  Present it as numbered steps.
- Offer the user a **"one-shot"** option: they may approve the whole sequence at
  once and have you execute it end to end without stopping between steps.
- If the user takes the one-shot option, **first state the choices you will make
  autonomously** — the decisions you would otherwise have stopped to ask about
  (e.g. authoring `GettingStarted`/`Introduction`, storing example result plots,
  adding icons, how far to decompose). One-shot suppresses the questions, not the
  decisions; surfacing the defaults up front lets the user veto before you build.
- When creating a library, recommend a **parallel test library** from the start.
  Add a unit test for each component as you build it — not at the end.
- **Never delete the user's model files to "start clean."** When the toolchain
  errors, fix the code forward — a validate/simulate failure is almost always a
  wrong name or missing load, not a reason to throw the work away. Deleting files
  to reset loses work and is rarely what the user wants.

## 1. Reuse before building (priority order)

When you need a component (or a connector), look in this order and only build
new if nothing fits:

1. **MSL** — the Modelica Standard Library.
2. **The user's own Git-repo libraries** (e.g. what lives in their repo).
3. **Wolfram libraries** — bundled / add-on WSM libraries.
4. **Your own component** — last resort.

The same order applies to connectors: reuse a standard connector
(`Modelica.Blocks.Interfaces`, mechanical `Flange`, electrical `Pin`,
`Thermal.HeatPort`, `Fluid` ports, ...) before inventing one.

**Ground every MSL name in the docs — do not recall paths from memory.** MSL
component paths are easy to misremember: there is no `Modelica.Blocks.Math.Sine`
(sine is `Modelica.Blocks.Sources.Sine`), no `Math.Subtract` (use
`Math.Feedback` for `u1 - u2`, or `Math.Add` with `k2 = -1`), and no
`Nonlinear.Saturation` (the saturation block is `Nonlinear.Limiter`). Before you
write an MSL class name, confirm it with the **search-modelica-docs** skill. If a
later validate reports `Element not found ... in Modelica...`, the path is wrong
— look the correct one up with **search-modelica-docs**; **do not** grep or walk
the System Modeler install tree hunting for it.

## 2. Components by default; design the connector first

Whether something should be a component hinges on the **interface**, not the
part. Componentize where you can draw a clean connector:

- a **small, stable set of physically-conjugate effort/flow pairs**
  (`v`/`i`, `p`/`m_flow`, `f`/`v`, `T`/`Q_flow`);
- **regime-independent** — the variables crossing don't change meaning with
  global state;
- **low-bandwidth** — you're not smuggling a neighbour's internal state across.

If a cut would force a wide or regime-dependent connector, or would break a
**global constraint** that no single component owns, the boundary is in the
wrong place: move it, or keep just that coupled residue together.

Use `flow` for conserved quantities and `stream` for transported fluid
properties.

### 2a. Reference components - one per attachment point

Every physical network needs a **reference** that fixes its absolute potential.
Without one the model is structurally singular: the effort variables are only
ever determined up to a constant.

A **pure reference** has one connector, prescribes the **effort** on it, and
leaves the **flow** free:

| Domain | Component | Prescribes |
|---|---|---|
| Electrical analog | `Modelica.Electrical.Analog.Basic.Ground` | `p.v = 0` |
| Electrical quasi-static | `Modelica.Electrical.QuasiStatic.SinglePhase.Basic.Ground` | `pin.v = Complex(0)` |
| Rotational | `Modelica.Mechanics.Rotational.Components.Fixed` | `flange.phi = phi0` |
| Translational | `Modelica.Mechanics.Translational.Components.Fixed` | `flange.s = s0` |
| Thermal | `Modelica.Thermal.HeatTransfer.Sources.FixedTemperature` | `port.T = T` |
| Magnetic | `Modelica.Magnetic.FluxTubes.Basic.Ground` | `port.V_m = 0` |

Because such a component absorbs whatever flow arrives at it, N instances behave
exactly like one instance shared by N connections. So **give each attachment
point its own reference instance**, named after what it anchors (`groundInput`,
`fixedBearing`) — not one instance that every component connects to. Both are
correct; only the first draws a readable diagram. One shared reference is the
highest-degree node in the graph, and each connection to it becomes a line
across the whole schematic.

Two things that are **not** replicable references:

- **Flow-prescribing sources** — `FixedHeatFlow`, `ConstantCurrent`. Each copy
  injects the full amount, so replicating them multiplies the excitation.
- **Fluid boundaries** — `Modelica.Fluid.Sources.Boundary_pT` does prescribe an
  effort (p, T), but a shared boundary is also a flow *path* between the
  connections it joins; splitting it removes a path that was there.
- **`inner` singletons** — `Modelica.Mechanics.MultiBody.World` (as `inner
  Modelica.Mechanics.MultiBody.World world`) and `Modelica.Fluid.System`.
  Exactly one per model, by language rule.

Confirm the exact class path with **search-modelica-docs** before writing it
(section 1). The **annotate-modelica-graphics** skill applies the same rule to
an existing model, splitting a shared reference before it lays out the diagram.

## 3. Composition vs inheritance (two reuse axes - don't conflate)

- **Composition** (instantiate + connect): *"is made of"* — distinct physical
  parts wired in the diagram.
- **Inheritance** (`partial` base + `extends`): *"is a kind of"* — variants that
  share equation structure (e.g. two heat exchangers sharing the same balance
  and wall equations).

## 4. Granularity

Decompose at **real engineering joints** — the parts an engineer would name
(pump, valve, wall, zone). Avoid trivial one-variable wrappers, and do not merge
genuinely simultaneous physics that has no clean internal interface.

## 5. Monolith exception

A single all-equations model is acceptable **only** as a first correctness pass
on a numerically hard model. When you do it:

- say so explicitly, and
- end with a **concrete written decomposition proposal** — name the components
  and the connector or `partial` base each would become — not an open-ended offer
  to "refactor later".

Even when no clean connector exists (a tightly coupled DAE — shared pressure
state, regime-dependent coupling), still factor the reusable **equation
structure** into `partial` base classes and functions (see section 3). A model
that derives a generic control volume, then specialises it, is decomposed even if
its zones cannot be cut into separately-connected components.

Never present a monolith as the finished structure.

## 6. One class per file (for version control)

**One-off model vs library.** If the user just wants a single throwaway model
(not a reusable library), write **one self-contained `.mo` file** holding that
model — it is simpler to author, validate, and simulate. Reach for the
directory form below only when building a library or a genuinely multi-class
model.

Store libraries in **directory form**:

- `package.mo` + `package.order` at each level,
- subpackages as folders,
- **each `model` / `block` / `function` / `record` / `connector` in its own
  `Name.mo`**.

This makes version handling far easier: granular diffs, fewer merge conflicts,
per-component blame and review. Exception: a few tiny, tightly-coupled leaf
classes (e.g. some `Types`) may share a file.

**Names must be valid Modelica identifiers.** A package/class name — and the
directory or file that holds it — is letters, digits, and underscores only, and
must not start with a digit: **no hyphens or spaces** (`inverted-pendulum` is
illegal; use `InvertedPendulum`). A directory-form library's folder name must
equal its package name, and the dotted `--name` you pass the launcher (e.g.
`InvertedPendulum.Controller`) is built from these identifiers.

**Keep line endings consistent.** Same motivation as one-class-per-file: a file
whose endings get switched or mixed by an edit diffs whole-file and buries the
real change. Match what a file already has when editing it, and match the
library's existing `.mo` files when adding one — see
[Appendix → Line endings in .mo files](#line-endings-in-mo-files).

## 7. Units - always declare

Every variable/parameter that has a unit **must** declare it, in this priority:

1. An **SI type** from `Modelica.Units.SI` (e.g. `SI.Pressure p`).
2. Else a **NonSI type** from `Modelica.Units.NonSI`.
3. Else the **`unit=` attribute** (e.g. `Real areaPerLength(unit="m2/m")`).

Signals flowing through connectors are SI; use `displayUnit` for friendly
labels (note a `displayUnit` default needs a literal value).

Use the **MSL 4.x** names — this toolchain ships MSL 4.x, and the old 3.2 names
flatten with confusing "not found" errors. Write `Modelica.Units.SI.*` (not
`Modelica.SIunits.*`), and source frequency is `f=` (not `freqHz=`). Declare the
dependency as `annotation(uses(Modelica(version = "4.1.0")))`.

## 8. Conventions

These are the library conventions every WSM/Modelica model and library must
follow. Sections 8a-8h are the detail behind the section 9 checklist.

### 8a. Naming and code

- **camelCase, no underscores** for parameters and variables, starting lower
  case (`heatSource`), following the
  [MSL naming conventions](https://reference.wolfram.com/system-modeler/libraries/Modelica/Modelica.UsersGuide.Conventions.ModelicaCode.Naming.html).
- Use **meaningful names** — `enthalpy`, not `h`.
- Avoid any **tool-dependent** code, so the library stays tool-independent.
- Store all external resources (images, CAD, PDFs) in a **`Resources`** folder in
  the library directory, referenced via **Modelica URIs** (never raw paths); use
  only resources you have the rights to use.
- Review **experiment settings** (time unit, solver, tolerance, step) so they are
  relevant for each example.

### 8b. Units

Covered in section 7 — every variable/parameter with a unit declares it (SI type
→ NonSI type → `unit=` attribute). Signals through connectors are SI; use
`displayUnit` for friendly labels.

### 8c. Documentation text

- **All classes documented**; **all parameters and variables, including
  `protected`,** have a one-line description.
- First character **uppercase**; for one-line descriptions of params, variables,
  and classes, **no trailing period**.
- Spelling and grammar must be correct.
- **Do not** set custom font style/size styling.
- Write library names **spaced** ("Rotating Machinery", not "RotatingMachinery").
- Wrap component, class, variable, and instance names in the text with `<code>`.
- **Write concisely, in a scientific style.** One idea per sentence, and cut any
  sentence that does not tell the reader something new.
  - Impersonal and declarative, in the present tense: "The limiter caps the armature
    voltage at `supplyVoltage`." No "we", "you" or "our", and no promotional or filler
    words ("simply", "powerful", "easily", "note that").
  - Quantities with their value and SI unit, a space between the two (`200 rad/s`,
    `0.1 N·m`). Define each symbol where it first appears, and give a relation as an
    equation rather than paraphrasing it in words.
  - State the assumptions and limits the model rests on ("ideal commutation, no
    friction").
  - Every number is one the model or a simulation of it gives; do not quote a value you
    have not checked. Cite the source of any equation or data that is not derived here.

### 8d. HTML documentation

- Use only `<h4>` and `<h5>` headings — **never `<h1>`-`<h3>`** (those are used by
  the auto-generated docs). Headings must **not** end with a `:`.
- System Modeler builds most of the documentation page from the code. `info` holds
  only what the page cannot derive. The page already shows:

  | Page part | Built from | Shown for |
  |---|---|---|
  | Title, description, icon | class name, description string, `Icon` | every class |
  | Diagram | `Diagram` annotation | models and blocks that have one |
  | Parameters: value, type and unit, description (inherited ones too) | declarations | models, blocks |
  | Connectors and Components: icon, type, description | declarations | models, blocks |
  | Syntax, Inputs, Outputs | function signature | functions |
  | Package Contents: each class with icon and description | the package | packages |
  | Used in Examples / Used in Components | the loaded libraries | classes used elsewhere |
  | Revisions | `Documentation(revisions=...)` | when set |

  So `info` **never** contains parameter, connector or component lists or tables. It
  also never repeats the description string, the call syntax, the inputs and outputs,
  or the package's contents. Mention a parameter only to say what its own description
  cannot: how it interacts with others, its valid range, its sign, or the choice it
  makes.
- What the general information says, by kind of class:
  - **Component:** the governing equations, the sign convention, valid ranges, and
    when to use a sibling instead.
  - **Function:** what it computes, how it fails, and a call example.
  - **Example:** its purpose, what drives it, and what to observe or plot.
  - **Package:** a short overview in prose.
- Each class's doc, in this order: **general information** (how the class works, no
  subsections) → **References** (relevant articles) → optionally **Implementation**,
  **Limitations**, **Notes**, **Examples**, **Acknowledgments**, **See also**
  (hyperlinks to related classes), in that order. Omit the MSL convention's
  **Syntax** section for functions, since the page generates it.
- Put any **revision history** in `annotation(Documentation(revisions="..."))`;
  "what's new" goes in the revisions, e.g.:
  ```
  <h4>New in Version 1.2.0</h4>
  <ul>
    <li>Library is now available for free for Wolfram System Modeler users</li>
  </ul>
  ```

### 8e. Plot styling

- Add model plots to the library examples; set **at least one as the default
  plot**.
- Plot titles and legends should be **meaningful**. Raw component paths are fine
  when already clear (e.g. `R1.v`, `R2.v`); replace them only when the default is
  ambiguous or unwieldy (deep nesting, generic names like `.y`).
- Plot titles: **sentence case, no trailing period** (e.g. "Fuel consumption of
  an aircraft"). Legends: start **uppercase**, no trailing period.
- Explores are optional (prefer them for faster simulations); control-panel names
  and explore parameter descriptions start uppercase.

### 8f. Appearance / icons and availability

- **Every class has an icon.** Follow the
  [MSL icon conventions](https://reference.wolfram.com/system-modeler/libraries/Modelica/Modelica.UsersGuide.Conventions.Icons.html),
  except the `%name` text uses color `{64, 64, 64}`.
- State which **platforms** (Mac, Windows, Linux) the library supports, with good
  reasons for any exclusion.
- Declare **all dependencies with `uses` annotations**, including the MSL version
  (e.g. `uses(Modelica(version = "4.1.0"))`). State any additional software
  needed.

### 8g. Library structure and documentation shape

Every library's top-level `package.order` starts with the same three nodes, in
this order, then the library-specific components/subpackages:

```
GettingStarted   ← always present, info-only model
Conventions      ← encouraged; omit only when no cross-cutting reference exists
Examples         ← always present, runnable models
...Components (with Utilities, Types), other subpackages...
```

- `GettingStarted` and `Conventions` are **info-only models** (not packages):
  `preferredView = "info"`, `DocumentationClass = true`. Fold any existing
  `Introduction` / `Troubleshooting` into `Conventions` (or, if substantial, keep
  `Troubleshooting` as a sibling with a consistent shape).
- The top-level `package.mo` doc is the **library elevator pitch**: a one/two-
  paragraph summary, a short linked list of 4-8 core abstractions, three "where to
  go next" links (`GettingStarted` / `Conventions` / `Examples`), and a
  `<h4>References</h4>` section if applicable. It must not duplicate
  `GettingStarted` or `Conventions`.
- **`GettingStarted` skeleton** (same sections, same order): one-paragraph summary
  → **Building Blocks** (linked core components) → **Worked example** (diagram
  screenshots + a simulation plot) → **Next steps** (links to `Conventions` and
  `Examples`).
- **`Conventions` skeleton** (always these `<h5>` sections, in order): Symbols &
  Notation → Units & Display Units → Connectors & Sign Conventions → Styling →
  References. Keep a heading even when its content is one line.
- `Examples` is a `package` (subpackage it by category past ~8 examples). Each
  example documents its **purpose** and **what to observe** after simulating, and
  should preferably cover all main components in the library.
- **Cross-link with Modelica URIs** (`modelica://Library.Path.Class`), never raw
  HTML paths. Every `GettingStarted` ends with Next steps; every `Conventions`
  opens with a one-line link to `GettingStarted`; link components to confusable
  siblings.

### 8h. Testing

- Create a **parallel test library** named `<Library>Tests` (e.g. `Hydraulic` ->
  `HydraulicTests`). Every component gets its corresponding unit test(s) there **as
  it is created**, not at the end.
- If the example models do not cover every component, the test library must
  exercise the remaining ones.

## 9. Definition of done

A model or library is not "done" — and success must not be reported — until these
hold:

- [ ] Each class **validates**, and examples **build/simulate**, without warnings
  (justify any exception).
- [ ] Every class has an **icon** (invoke the `annotate-modelica-graphics` skill)
  and a one-line description; every parameter/variable, including `protected`,
  has a description and — where it has one — a unit.
- [ ] Each `info` covers only what the generated documentation page does not show
  (section 8d), written concisely in the scientific style of section 8c.
- [ ] Every **example** documents its purpose and what to observe, and carries
  **stored result-plot annotations** (`figures=`, at least one default plot) —
  invoke the `annotate-modelica-plots` skill once it simulates. Give each figure
  an identifiable **title** and a one-line **`caption`**; if the model replicates a
  published reference, **name figures to match it** (e.g. `"Fig. 6 - …"`) and note
  the correspondence in the caption. (Pure pass/fail assertion tests need no
  figure; anything meant to be simulated and *inspected* does.)
- [ ] Every physical network has a **reference** (ground, housing, fixed
  temperature), and each attachment point has **its own instance** of it rather
  than one shared instance fanned out (section 2a).
- [ ] Every component has a **unit test** in the parallel `<Library>Tests`.
- [ ] The library follows the three-slot top-level shape — **`GettingStarted`**,
  **`Conventions`**, **`Examples`** first in `package.order` (section 8g).
- [ ] If a monolith was used, a concrete **decomposition proposal** is on the
  table (section 5).

Treat this as a checklist to run through and report against, not a list to skim.

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
