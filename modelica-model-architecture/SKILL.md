---
name: modelica-model-architecture
description: "Architecture and structuring guidance for Wolfram System Modeler / Modelica (.mo) models and libraries. Use this skill BEFORE writing equations whenever creating, implementing, structuring, or refactoring a model or library, to decide component decomposition, connectors, component reuse, file/folder layout, units, and naming. Triggers on phrases like 'create/build a Modelica model', 'implement this model/paper in Modelica', 'make a WSM model', 'write a Modelica library', 'structure/architect this model', 'single .mo file vs directory', 'split this into components', 'refactor this model/library', or any decomposition / connector / component-reuse / file-layout decision. Whenever you are about to write a multi-class library, consult this skill first to choose directory-form (one class per file) storage rather than a single monolithic .mo. Complements the validate/simulate/diagnose/annotate Modelica skills; for assembling a specific component library (e.g. create-hydraulic-model) defer to that domain skill."
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

### 8d. HTML documentation

- Use only `<h4>` and `<h5>` headings — **never `<h1>`-`<h3>`** (those are used by
  the auto-generated docs). Headings must **not** end with a `:`.
- Each component's doc, in this order: **general information** (how the class
  works, no subsections) → **References** (relevant articles) → optionally
  **Implementation**, **Limitations**, **Notes**, **Examples**, **Acknowledgments**
  (in that order).
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
- [ ] Every **example** documents its purpose and what to observe, and carries
  **stored result-plot annotations** (`figures=`, at least one default plot) —
  invoke the `annotate-modelica-plots` skill once it simulates. Give each figure
  an identifiable **title** and a one-line **`caption`**; if the model replicates a
  published reference, **name figures to match it** (e.g. `"Fig. 6 - …"`) and note
  the correspondence in the caption. (Pure pass/fail assertion tests need no
  figure; anything meant to be simulated and *inspected* does.)
- [ ] Every component has a **unit test** in the parallel `<Library>Tests`.
- [ ] The library follows the three-slot top-level shape — **`GettingStarted`**,
  **`Conventions`**, **`Examples`** first in `package.order` (section 8g).
- [ ] If a monolith was used, a concrete **decomposition proposal** is on the
  table (section 5).

Treat this as a checklist to run through and report against, not a list to skim.
