---
name: simulate-modelica-realtime
description: "Run a compiled Modelica model as a live, real-time simulation server and interact with it over the System Modeler simulation TCP interface: start, pause, resume and stop it, set inputs and tunable parameters while it runs, read and stream values, or send raw protocol commands, on an executable it launches or one already running in Simulation Center. Use it whenever a simulation must run in real time or as a server, take input or parameter changes mid-run, be driven from Python or another program, or feed an operator, hardware-in-the-loop or live-dashboard demo. Triggers on phrases like 'run in real time', 'simulate in server mode', 'connect to the running simulation', 'change the input while it runs', 'stream simulation values', 'hardware in the loop', 'simulation server', 'TCP interface of the simulation'. For one-shot simulations use simulate-modelica; for live interaction from Wolfram Language use wolfram-language-modelica."
---

# Talk to a simulation executable

Every simulation System Modeler builds is an executable plus a `.sim` settings file, and every
running simulation has a built-in TCP server. A client can start, pause, resume and stop the run,
set top-level inputs at any time, set tunable parameters while the solver runs, read any variable,
and subscribe to variables that are then streamed while it runs. This skill does that with the
stdlib-only client `<scripts-dir>/wsmsim.py` and its command line `<scripts-dir>/wsm_realtime.py`.
Resolve `<scripts-dir>` as in [Appendix → Locating the launcher](#locating-the-launcher),
and follow its shell and Python rules per OS.

## 1. Get a simulation to talk to

Either of these works:

- **Launch an executable.** Build the model with the simulate-modelica skill, and keep
  `_wsm_simulate_temp/` next to the model: it holds `<Model>_<id>.exe` and its `.sim`. Give that
  directory as `<target>` with `--model ModelName` (or the executable path) below; the CLI starts
  it in server mode, paced to the wall clock, on a free port.
- **Attach to a running simulation.** A simulation started in Simulation Center, or by hand with
  `<Model>_<id>.exe -f <Model>_<id>.sim -server 127.0.0.1:7000`, is already listening; the
  simulation log shows the address (`Server listening on 127.0.0.1:<port>`). Pass
  `--attach host:port` instead of a target. An attached client never stops the simulation when it
  disconnects, so several clients can share one run.

Only top-level `input` variables can be changed while the solver runs, and only tunable
parameters after the start. If the model exposes nothing to steer, add `input Real u(start = ...)`
variables (or a wrapper model) for the quantities the user wants to drive, and make the display
quantities top-level `output`s; validate with validate-modelica.

## 2. Inspect the interface as the server sees it

```bash
python3 "<scripts-dir>/wsm_realtime.py" info <target> --model ModelName
```

Prints inputs and their start values, outputs, tunable parameters and states. Use these exact
names below; nested names use dots (`load.p`), array elements `[k]`. Every streamed sample already
carries the simulation time, so do not subscribe to `time`.

## 3. Run a scripted scenario

```bash
python3 "<scripts-dir>/wsm_realtime.py" run <target> --model ModelName \
  --watch flow,angle,status --duration 30 --scale 2 \
  --set 5:Pset=4500 --set 12:breakerClosed=false --param 0:sensWarn=3 --param 8:T=1 \
  --csv run.csv
```

- `--scale N`: N simulated seconds per wall second; `--fast` runs without pacing and takes no
  timed changes.
- `--set T:name=value`: input change T simulated seconds into the run. `--param T:name=value`:
  parameter change; T=0 is applied before the start, later times need a tunable parameter.
  `--duration` and T count from the start or, with `--attach` to a simulation that is already
  running, from the moment of attaching; a simulation that has not started yet is started.
- Values stream once per **output interval** (the model's `Interval`, or `--interval 0.01`), plus
  one sample at each event instant carrying the values from just before the event. A change is
  sent at the first sample at or after its time and takes effect from the next solver step, so
  up to one output interval later; model the change in Modelica when its exact time matters.
- `--step 0.01 --method explicit-euler`: fixed-step integration (also `rk4`, `heuns-method`);
  the default is the model's own solver settings.
- One printed row per `--print-every` simulated seconds; `--csv` records every sample received.
- The run ends with the packet count and the gaps longer than the output interval, and exits
  non-zero if simulated time stopped short of `--duration`. The server
  sends the newest sample whenever it can, so a gap means samples were skipped (common with
  `--fast`); the stream is not a complete result — simulate-modelica gives that.

## 4. Send protocol commands directly

```bash
python3 "<scripts-dir>/wsm_realtime.py" cmd --attach 127.0.0.1:63597 \
  -c 'getVariableNames()' -c 'setInputValues({"u", 2.3})' -c 'getVariableValues({"y"})'
```

Each reply is printed as the server sends it (`{"u", "y", "k"}`, `{true}`, `{4.6}`); a refused
command prints the server's error text. Without `-c` the commands are read one per line from
standard input. Commands:

| Command | Effect |
|---|---|
| `getModelName()`, `getTime()`, `getStopTime()`, `getSimulationState()` | model name; current and stop time; 1 not started, 2 running, 3 suspended |
| `getVariableNames()`, `getInputVariableNames()`, `getOutputVariableNames()`, `getParameterNames()`, `getTunableParameterNames()`, `getStateVariableNames()` | name lists |
| `getVariableValues({"a", "b"})` | current values |
| `setInputValues({"u", 2.3, "v", 0})` | inputs, used from the next step |
| `setParameterValues({"T", 1.0})` | before the start: a parameter from `getParameterNames()`; after: a tunable one |
| `setSubscription({"a", "b"})` | returns a subscription id; values then stream on a data session |
| `startSimulation()`, `suspendSimulation()`, `continueSimulation()`, `stopSimulation()` | run control |

Boolean values may be written `true`/`false` or `1`/`0`. To run again from the start, use the
Restart button of the live view (section 5) or `restart()` in Python (section 6), not
`restartSimulation()`, which ends the simulation process. Evaluated and structural parameters are
in neither parameter list; changing them needs a rebuild.

## 5. Live view with controls

```bash
python3 "<scripts-dir>/wsm_realtime.py" plot <target> --model ModelName \
  --watch flow,angle --sliders Pset:0:7500,V:0.85:1.1 --toggles breakerClosed
```

Live curves with sliders and check boxes writing the inputs, and a Pause/Run button; a launched
simulation also gets a Restart button. Needs a display.

## 6. Custom logic from Python

```python
import sys; sys.path.insert(0, "<scripts-dir>")
from wsmsim import WsmSimulation, find_simulation
exe, sim = find_simulation("<build-dir>", "ModelName")
with WsmSimulation.launch(exe, sim, scale=1.0) as s:          # or WsmSimulation.attach(host, port)
    sub = s.subscribe(["flow", "angle"])
    s.set_parameters(sensWarn=3.0)                              # before start
    s.start()
    for t, row in s.stream(sub, seconds=10):                    # (sim_time, {name: value}) per sample
        if row["angle"] > 30:
            s.set_inputs(Pset=3000)                             # Booleans may be True/False here
    s.set_parameters(T=1.0)                                     # tunable parameter, mid-run
    s.suspend(); s.resume(); s.get_values(["flow", "P"]); s.stop()
```

`launch` writes an interactive copy of the `.sim` (long stop time, the model's output interval,
real-time pacing, no result file), starts the executable on a free port and removes the copy when
it exits; `attach` connects to a running server and leaves it running on close. `s.latest(sub)`
gives the newest sample without consuming the stream; `s.send_inputs([...])` sends all inputs as
one binary packet in `s.inputs` order, for high-rate feeds (paced runs only); `s.restart()`
relaunches a launched simulation from the start, keeping its subscriptions and the values set
through `s`; `s.scs.command_raw(text)` sends any protocol command.

## Behaviour to rely on

- The server does nothing until `startSimulation()`; connecting does not start the run.
- Without real-time pacing the executable runs its whole horizon as fast as it can. The CLI and
  `launch` enable pacing unless told otherwise; a simulation started elsewhere keeps its own
  settings.
- Suspending stops the run at the end of the current step and holds the time there.
- When a simulation reaches its stop time the process exits and closes every connection.

## Protocol, for clients in other languages

Documented in the System Modeler User Guide, "Communication with Simulation via TCP"
(reference.wolfram.com/system-modeler/UserGuide/CommunicationwithSimulationviaTCP.html). In
short: every packet is an 8-byte little-endian header — `version` (1), `type`, one byte with the
subscription id on data packets, one byte with the simulation state, and a 4-byte payload length —
followed by the payload. A control session opens with a `HELLO_SCS` packet (type 1) and gets its
session id back (`{1}`); commands are text in `CMD` packets (type 3), answered by `CMD_REPLY` (4)
or `CMD_ERROR` (5). A data session opens with `HELLO_SDS` (type 2) carrying that session id in
braces, and then receives type 6 packets: the simulation time followed by the subscribed values,
all doubles. A type 8 packet on the data session sets all inputs at once, as doubles. Send Boolean
values in commands as `1`/`0`. `wsmsim.py` is a complete implementation.

## 7. Report and clean up

Report the scenario, what changed at which simulated time, the key values, and the packet count
and gaps. A launched executable leaves `<Model>_<id>_server.log` next to itself; remove the
whole `_wsm_simulate_temp/` when the user is done with the executable — commands per OS:
[Appendix → Temporary directories](#temporary-directories).

## Edge cases

- **`Unknown variable`** (subscribe, read) or **`Not an input variable`** (set): check the names
  with `info`.
- **`Not a valid parameter to set`**: after the start the parameter is not tunable; before it, the
  parameter is evaluated or structural. Set it at T=0, or change the model and rebuild.
- **Executable exits at once**: read `<Model>_<id>_server.log` in the build directory; a model
  that fails initialization or a wrong `.sim` path shows there.
- **Simulated time stops advancing while samples keep arriving** (`run` reports that it stopped
  short of `--duration`): the model is chattering on an event, e.g. a condition that switches the integrator of a saturated controller on and off.
  The server log shows `Event burst count reached warning threshold` and the expression causing
  it; reformulate that part of the model and rebuild.
- **Connection closed or refused on an attached run**: the simulation reached its stop time and
  exited; a simulation started elsewhere keeps the stop time from its own settings.
- **Web or other clients**: the server speaks TCP only; put a small bridge (WebSocket or
  server-sent events) in front of `wsmsim.py` for browsers.

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
