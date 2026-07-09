---
name: create-hydraulic-model
description: "Create Modelica models using the Hydraulic library with knowledge-graph-guided component selection and wiring. Use this skill whenever the user asks to create, build, design, or generate a hydraulic circuit or Modelica model using the Hydraulic library. Triggers on phrases like 'create a hydraulic model', 'build a circuit with a pump and cylinder', 'design a meter-in circuit', 'make a model with a directional valve', 'generate a hydraulic system', or any request to assemble Hydraulic library components into a working model. For the overall structure of a large model or library, consult modelica-model-architecture first."
---

# Create Hydraulic Model (Graph RAG Guided)

This skill uses a knowledge graph of the Hydraulic Modelica library to guide the user through creating valid hydraulic circuit models. The graph (built from **Hydraulic 2.1**) contains 168 parsed components with their ports, parameters, inheritance, and 60 validated connection patterns extracted from the library's composite models and 18 example circuits.

## Before you run anything

The query commands below run `python -m Hydraulic.main …`; the optional validation step
(Step 7) additionally drives the shared launcher. For the Windows-vs-Unix shell/Python
rules (PowerShell on Windows, `python` vs `python3`) and launcher conventions, see
[the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills) — the launcher-specific parts (temp dirs,
JSON output, MSL, `--load-library`) only matter once you validate.

## Knowledge Graph (bundled)

The Graph RAG dataset and query module ship **inside this skill** as the
`Hydraulic/` Python package — there is nothing external to locate. The query
path reads the prebuilt graph in `Hydraulic/data/graph.json`; it does **not**
need the Modelica library and does not re-parse anything, so it works wherever
the skill is installed.

- **Requirement:** `networkx` — but you don't install it by hand. `Hydraulic.main`
  **self-provisions it into a managed venv** on first run (it never touches system
  Python). To pre-warm: `python3 "<scripts-dir>/bootstrap_env.py" networkx`.
- Run the query module with **this skill's own directory** (the folder
  containing this `SKILL.md`) as the working directory, so the package resolves
  as `Hydraulic`.

## Query Commands

Run from this skill's directory (`<skill-dir>` below — the folder that contains
this `SKILL.md`) so the `Hydraulic` package is importable. Use `python` instead
of `python3` on Windows if that's what's on PATH.

```bash
cd "<skill-dir>"

# Search for components by keyword
python3 -m Hydraulic.main --query "pump"

# Get the full effective interface of a component (ports + parameters, incl. inherited)
python3 -m Hydraulic.main --details "CylinderDouble"

# Find all components that extend an interface
python3 -m Hydraulic.main --interface "FourPort"

# List all example circuits
python3 -m Hydraulic.main --examples

# Get RAG context for a natural language query
python3 -m Hydraulic.main --rag "pressure control circuit"
```

(Use the absolute path to this skill's directory for `<skill-dir>`.)

## Validating & Simulating the Generated Model

Generation itself only needs the bundled graph (above). To **flatten, validate, or
simulate** a generated model you drive WSMKernelX through the shared launcher — the same
one every other Modelica skill uses. **Read
[the shared-conventions appendix at the end of this file](#appendix-shared-conventions-for-the-modelica-skills) first** for launcher resolution, the
Windows-vs-Unix shell/Python rules, the temp-dir/cleanup conventions, the JSON-array
output gotcha, and the MSL 4.x dialect notes.

The model `extends Hydraulic.…`, so the Hydraulic library must be loaded alongside it.
**Do not locate or pass the path by hand** — add `--load-library Hydraulic` to any
validate / simulate / diagnose run and the launcher finds it (pin a version with
`Hydraulic==2.1`; run `--mode libraries` to see what is installed). Resolution
details and overrides:
[Appendix → Using non-MSL libraries](#using-non-msl-libraries-hydraulic-and-other-installed-libraries).

**Mind the library version.** The bundled graph is built from **Hydraulic 2.1**. If
`--mode libraries` shows a different installed version, treat graph answers as hints
rather than ground truth — component or parameter names may have drifted — and validate
the generated model early so any mismatch surfaces immediately.

## Guided Workflow

Follow these steps **in order**, confirming with the user at each step before proceeding.

### Step 1: Understand the Circuit Requirements

Parse the user's request (from `$ARGUMENTS` if invoked as `/create-hydraulic-model <desc>`, or from the conversation).

Identify:
- **Primary function**: What should the circuit do? (move a load, control flow, hold pressure, transmit power, etc.)
- **Actuator type**: Translation (cylinder) or rotation (motor)?
- **Control needs**: Directional control? Pressure limiting? Flow control? Sequence?
- **Any specific components** the user mentioned by name

### Step 2: Query the Knowledge Graph for Relevant Components

Based on the requirements, run targeted queries:

```bash
# For the main actuator
python -m Hydraulic.main --details "CylinderDouble"   # if translational
python -m Hydraulic.main --details "Motor"             # if rotational

# For the power source
python -m Hydraulic.main --details "Pump"

# For valves — find what's available
python -m Hydraulic.main --interface "FourPort"        # directional control valves
python -m Hydraulic.main --interface "ThreePort"       # pressure control / 3-way valves
python -m Hydraulic.main --interface "TwoPortStatic_2" # restrictions, throttles, filters

# For similar example circuits
python -m Hydraulic.main --rag "<user's circuit description>"
```

Also read the entities.json directly to get parameter defaults:
```bash
python -c "
import json
with open('Hydraulic/data/entities.json') as f:
    entities = json.load(f)
for e in entities:
    if e['name'] == 'COMPONENT_NAME':
        print(json.dumps(e, indent=2))
        break
"
```

### Step 3: Present Component Selection to User

Show the user a table of recommended components:

```
Proposed Components:
| Role              | Component                          | Description                    |
|-------------------|------------------------------------|--------------------------------|
| Power source      | Hydraulic.PumpsAndMotors.Pump      | Fixed displacement pump        |
| Actuator          | Hydraulic.Cylinders.CylinderDouble | Double-acting cylinder         |
| Direction control | Hydraulic....PCVE43ClosedCenter    | 4/3 proportional valve         |
| Pressure relief   | Hydraulic....PressureReliefValve   | System pressure limiter        |
| Tank (supply)     | Hydraulic.LiquidContainers.Tank    | Constant pressure reservoir    |
| Tank (return)     | Hydraulic.LiquidContainers.Tank    | Return line reservoir          |
| Speed source      | Modelica...ConstantSpeed           | Drives the pump shaft          |
| Load              | Modelica...Mass                    | Translational mass load        |
| Control signal    | Modelica.Blocks.Sources.Step       | Step input for valve command   |
```

Ask the user:
- "Does this component selection look right?"
- "Would you like to add, remove, or swap any components?"
- "Any specific valve type preference?" (show available options if relevant)

**Wait for user confirmation before proceeding.**

### Step 4: Propose Connections

Query example circuits that use similar components to find validated connection patterns:

```bash
python -m Hydraulic.main --rag "connect pump cylinder valve"
```

Present the proposed wiring to the user. Group by domain:

```
Proposed Connections:

Hydraulic (blue):
  1. tank1.port          -> pump.port_a          (tank feeds pump inlet)
  2. pump.port_b         -> controlValve.port_p  (pump pressure to valve P port)
  3. controlValve.port_a -> cylinder.port_a       (valve A to cylinder A)
  4. controlValve.port_b -> cylinder.port_b       (valve B to cylinder B)  
  5. controlValve.port_t -> tank2.port            (valve T to return tank)
  6. reliefValve.port_a  -> pump.port_b           (relief across pump output)
  7. reliefValve.port_b  -> tank3.port            (relief to tank)

Mechanical (green):
  8. constantSpeed.flange -> pump.flange          (speed source drives pump)
  9. cylinder.flange_b    -> mass.flange_a        (cylinder moves mass)

Signal (blue):
  10. step.y -> controlValve.u1                   (command signal to valve)
  11. const.y -> controlValve.u2                   (zero signal to valve u2)
```

Ask the user: "Does this wiring look correct? Any connections to add or change?"

**Wait for user confirmation before proceeding.**

### Step 5: Configure Parameters

For each component, show key parameters with defaults. Read these from the knowledge graph:

```bash
python -m Hydraulic.main --details "Pump"
python -m Hydraulic.main --details "CylinderDouble"
# etc.
```

Present a parameter table:

```
Key Parameters (defaults shown — override any you want):

Pump:
  D = 5e-05 [m^3/rev]  "Displacement"

CylinderDouble:
  diameterPiston = 0.05 [m]
  diameterRod_a  = 0.005 [m]
  lengthHousing  = 0.5 [m]
  lengthPiston   = 0.05 [m]
  lengthRod_a    = 0.5 [m]
  Vdead_a        = 1e-05 [m^3]
  mPiston        = 10 [kg]

PressureReliefValve:
  pMin = 20000000 [Pa]  "Opening pressure (200 bar)"

Mass:
  m = 100 [kg]

ConstantSpeed:
  w_fixed = 100 [rad/s]

Simulation:
  StopTime = 2 [s]
```

Ask: "Want to change any parameter values?"

**Wait for user confirmation before proceeding.**

**Units.** Hydraulic models are SI (pressure in Pa, flow in m³/s) and use `displayUnit` for
friendly labels (e.g. bar, L/min):
- A parameter modifier that carries `displayUnit` must take a **literal** value:
  `pMin(displayUnit = "bar") = 20000000.0`, *not* `= 200*1e5`. An arithmetic expression silently
  disables the `displayUnit` conversion in WSM, so the GUI shows the raw SI number. Compute the SI
  value yourself and write it as a literal (keep the readable origin in a comment if helpful).
- Signals arriving through a connector are already in SI base units — never rescale at the wiring
  site (`*1e-5`, `/60000`). Declare SI types with `displayUnit = "…"` and let the unit conversion
  happen for display only.

### Step 6: Generate the .mo File

Ask the user where to save the model:
- Suggested default: an `Examples/` subfolder of the user's own Modelica library
- Or any user-specified path

Generate the complete Modelica model following this template structure:

```modelica
within <package.path>;

model <ModelName> "<Description>"
  extends Hydraulic.Icons.Example;
  extends Hydraulic.Media.BaseModel;

  // Components — pass medium = medium only if <Type> extends Hydraulic.Media.BaseModel (e.g. not Tank)
  <Type> <instanceName>(<params>, medium = medium)
    annotation(Placement(visible = true, transformation(origin = {x, y},
      extent = {{-10, -10}, {10, 10}}, rotation = 0)));
  
  // Parameters
  parameter SI.Pressure openingPressure = 20000000.0 "Relief valve opening pressure";
  
equation
  // Hydraulic connections
  connect(<inst1>.<port>, <inst2>.<port>)
    annotation(Line(visible = true, origin = {0, 0},
      points = {{0, 0}, {0, 0}}, color = {0, 170, 255}));
  
  // Mechanical connections
  connect(<inst1>.<flange>, <inst2>.<flange>)
    annotation(Line(visible = true, origin = {0, 0},
      points = {{0, 0}, {0, 0}}, color = {0, 127, 0}));
  
  // Signal connections
  connect(<source>.y, <target>.u1)
    annotation(Line(visible = true, origin = {0, 0},
      points = {{0, 0}, {0, 0}}, color = {0, 0, 127}));

  annotation(
    experiment(StopTime = <stopTime>, __Wolfram_NumberOfIntervals = 2000,
      __Wolfram_Algorithm = "cvodes"),
    Documentation(info = "<html><body><Description></body></html>"));
end <ModelName>;
```

**Critical rules for valid .mo files:**
1. Every Hydraulic component that extends `Hydraulic.Media.BaseModel` needs `medium = medium` in its parameter list; components that don't (e.g. `Tank`) must NOT receive it — check with `--details <Name>`
2. `extends Hydraulic.Media.BaseModel;` provides the `medium` record
3. `extends Hydraulic.Icons.Example;` gives the example icon
4. Use color `{0, 170, 255}` for hydraulic connections
5. Use color `{0, 127, 0}` for mechanical connections
6. Use color `{0, 0, 127}` for signal connections
7. Every `connect()` needs a `Line` annotation (even with dummy points)
8. The `within` path must match the file's location in the package hierarchy
9. Pump needs `phi.fixed = true, dp.fixed = true` for proper initialization
10. CylinderDouble needs `pA.fixed = true, pB.fixed = true` for initialization

**Layout conventions** (approximate placement origins for a clean diagram):
- Tanks: bottom row, y = -70
- Pump: left side, y = -40
- Relief valve: near pump, y = -40
- Directional valve: center, y = 10
- Cylinder: upper area, y = 50
- Mass/load: right side, y = 50
- Signal sources: far left, various y
- Speed source: far left, y = -40

Write the file using the Write tool.

### Step 7: Offer Validation

After writing the file, ask: "Would you like me to validate this model using the Modelica compiler?"

If yes, use the `validate-modelica` (or `simulate-modelica`) skill on the generated file.
Because the model uses the Hydraulic library, add `--load-library Hydraulic` so the
launcher loads it alongside the model (MSL is automatic):

```bash
python3 "<scripts-dir>/wsm_run.py" --mode validate \
  --model "<path-to-ModelFile.mo>" --name <ModelName> --load-library Hydraulic --timeout 120
```

(Use `python` on Windows. See "Validating & Simulating the Generated Model" above and
[the shared-conventions appendix](#appendix-shared-conventions-for-the-modelica-skills) for launcher resolution and temp-dir/cleanup
conventions.) A clean run reports `flatten=Pass`.

## Component Quick Reference

### Common Circuit Patterns

**Basic servo (translate)**: Pump + PressureReliefValve + PCVE43* + CylinderDouble + Mass
**Basic servo (rotate)**: Pump + PressureReliefValve + PCVE43* + Motor + Inertia
**Meter-in flow control**: Add FixedTurbulentThrottle before directional valve
**Meter-out flow control**: Add FixedTurbulentThrottle after directional valve
**Load holding**: Add CounterBalanceValve between valve and cylinder
**Accumulator circuit**: Add CheckValve + OneWayFlowControlValve + GasChargedAccumulator
**Sequence circuit**: Add PilotOperatedSequenceValve between stages
**Pressure reducing**: Add PressureReducingValve for sub-circuit pressure limiting

### Valve Naming Convention
- **DCVE**: Directional Control Valve, Electrically actuated (conventional solenoid)
- **PCVE**: Proportional Control Valve, Electrically actuated (proportional solenoid)
- **DCVH**: Directional Control Valve, Hydraulically actuated (pilot operated)
- **DCVM**: Directional Control Valve, Mechanically actuated
- **42**: 4 ports, 2 positions
- **43**: 4 ports, 3 positions
- **32**: 3 ports, 2 positions
- **63**: 6 ports, 3 positions
- Center type suffix: ClosedCenter, OpenCenter, TandemCenter, FloatingCenter, DiagonalCenter

### Port Naming Convention
- **port_p**: Pressure supply (from pump)
- **port_t**: Tank return
- **port_a**: Load port A (cylinder side A)
- **port_b**: Load port B (cylinder side B)
- **port_pilot**: Pilot pressure input
- **u1, u2**: Electrical/signal control inputs
- **flange, flange_a, flange_b**: Mechanical connections
- **port**: Single hydraulic port (tanks, accumulators, sensors)

### Required Modelica Standard Library Components
- `Modelica.Mechanics.Rotational.Sources.ConstantSpeed` — drives pump shaft
- `Modelica.Mechanics.Translational.Components.Mass` — translational load
- `Modelica.Mechanics.Rotational.Components.Inertia` — rotational load  
- `Modelica.Blocks.Sources.Step` — step signal for valve command
- `Modelica.Blocks.Sources.Constant` — constant signal (e.g., k=0 for valve u2)
- `Modelica.Blocks.Sources.Ramp` — ramp signal
- `Modelica.Blocks.Math.Min` / `Max` / `Add` — signal processing
- `Modelica.Blocks.Math.BooleanToReal` — convert switch to proportional signal

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
