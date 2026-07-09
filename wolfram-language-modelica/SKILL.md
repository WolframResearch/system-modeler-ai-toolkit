---
name: wolfram-language-modelica
description: "Simulate and analyze Modelica models from within Wolfram Language / a notebook (WSM SystemModel* functions, WSMRealTimeSimulate) — extract numerical results and make custom plots. Use this skill whenever the user wants to work with a Modelica model inside WL / a notebook — running parameter sweeps, pulling time series into Wolfram arrays for analysis (e.g. AnomalyDetection, Predict, Classify, SystemModelCalibrate), validating against requirements (SystemModelValidate, Monte Carlo, uncertainty bands), training surrogates, making custom plots, or driving a live simulation interactively (pause/resume, change inputs or parameters mid-run, agent/LLM-in-the-loop). Triggers on phrases like 'simulate this model in WL', 'get the results into Wolfram Language', 'extract a time series', 'SystemModelSimulate', 'SystemModelPlot', 'sweep a parameter', 'validate against requirements', 'stays within limits', 'show me any violations', 'SystemModelValidate', 'failure plot', 'uncertainty plot', 'train a surrogate', 'real-time simulation', 'interactive simulation', 'change inputs while it runs', 'WSMRealTimeSimulate'."
---

# System Modeling with Wolfram Language

This skill covers how to drive Modelica simulation from Wolfram Language using the built-in `SystemModel*` family. Use this when the downstream work lives in WL, for example, analysis of simulated data, calibration, optimization, surrogates, custom plots.

For pure command-line simulation / validation with no WL work afterward, prefer the `simulate-modelica` or `validate-modelica` skills — they are faster because they avoid kernel startup and WL context.

## When to use which

| Goal | Use |
|------|-----|
| Does this `.mo` compile? | `validate-modelica` |
| Run a sim, get pass/fail + log | `simulate-modelica` |
| Debug torn systems, stiff init, blocks | `diagnose-modelica` |
| Pull time series into WL for `Predict` / `AnomalyDetection` / `Fit` | **this skill** |
| `SystemModelCalibrate`, `SystemModelParametricSimulate` | **this skill** |
| Requirement validation, uncertainty bands, surrogates | **this skill** |
| Live simulation you can pause / poke inputs & parameters mid-run | **this skill** (`WSMRealTimeSimulate`) |

## Official reference docs (LLM-friendly variant)

Every page of the official Wolfram documentation has an LLM-friendly Markdown
variant — append `.en.md` to the page URL. Fetch these on demand when you need
the full signature, all options, or more examples than this skill carries:

- Hub: `https://reference.wolfram.com/language/guide/SystemModelingOverview.en.md`
- Any `SystemModel*` function: `https://reference.wolfram.com/language/ref/<Name>.en.md`
  (e.g. `SystemModelSimulate.en.md`, `SystemModelCalibrate.en.md`, `SystemModelValidate.en.md`)
- `` WSMLink` `` (real-time) functions: `https://reference.wolfram.com/system-modeler/WSMLink/ref/<Name>.en.md`

The reference pages carry signatures and options but **not** the operational
gotchas in this skill — those are verified against live kernels, and several
(silent failures, headless-vs-notebook differences) are documented nowhere
else. Where this skill and a doc example conflict in a headless/agent context,
trust this skill.

## Prerequisites — Wolfram Language + the Wolfram MCP server

Everything in this skill is Wolfram Language code (`SystemModelSimulate`,
`SystemModelPlot`, `SystemModelCalibrate`, the requirement language, …). To run
it the assistant needs a way to evaluate WL, which means two things:

1. **Wolfram Language 14.3 or later** — **Mathematica** or **Wolfram|One** (the
   `SystemModel*` simulation functions are *not* included in the free Wolfram
   Engine). 
2. **A C++ compiler.** `SystemModelSimulate` compiles each model to a native
   executable before running it, so a working compiler toolchain must be
   available. Check (and fix) from within WL:
   ```wolfram
   SystemModel; (* Trigger loading of the system modeling functionality *)
   SystemModelConfiguration`VerifyCompiler[]    (* -> <|"Success" -> True|> when a working compiler is found *)
   SystemModelConfiguration`InstallCompiler[]   (* installs / configures a compiler if the check fails *)
   ```
3. **The Wolfram MCP server connected to your agent**, so the assistant can
   evaluate that WL on your machine.

**Check before installing.** First see whether Wolfram MCP tools (e.g. a
`WolframLanguageEvaluator`) are already available in this session. If they are,
skip setup and go straight to the workflow below.

**Install — same on Windows, macOS, and Linux.** In any Wolfram front end (a
Mathematica notebook or `wolframscript`), evaluate:

```wolfram
PacletInstall["Wolfram/AgentTools"];
Needs["Wolfram`AgentTools`"];
InstallMCPServer["ClaudeCode"]   (* or "ClaudeDesktop", "Cursor", … for other clients *)
```

This writes the server entry into the MCP client's config and runs the kernel
locally — no API key, nothing leaves the machine. **Then fully restart the
client** (quit completely; closing the window often just minimizes it to the
tray/menu bar).

**If anything goes wrong** — the paclet won't install, the server doesn't show
up in the client after restart, or evaluations fail — point the user to the
official setup and troubleshooting page:
**https://www.wolfram.com/artificial-intelligence/mcp/local/**

If the user **doesn't have Wolfram Language 14.3 or later** (Mathematica or
Wolfram|One), this skill can't run — point them to the page above and ask whether
they want to install it. Meanwhile, the command-line skills (`simulate-modelica`,
`validate-modelica`, `diagnose-modelica`) need only System Modeler, not WL, and
can cover compile / run / debug in the interim.

## Core workflow

### 1. Load the package

**From a file / package directory:**

```wolfram
sm = Import["/abs/path/to/package.mo", "MO"]   (* or "C:/..." on Windows *)
(* Returns SystemModel["PackageName", True] *)
```

**From a Modelica source string (useful for inline models, templates, or LLM-generated models):**

```wolfram
sm = ImportString[
"model Tiny
  Real x(start=0);
equation
  der(x) = 1 - x;
end Tiny;",
"MO"
]
(* Returns SystemModel["Tiny", True] *)
```

Notes:
- For multi-file packages, pass the top-level `package.mo`.
- The return value is a `SystemModel[...]` you can pass directly to `SystemModelSimulate`, `SystemModelPlot`, etc.
- You can also reference any loaded model by its full Modelica path as a string: `"MyPackage.SubPackage.MyModel"`.
- Modelica source always goes through `Import` / `ImportString` — `CreateSystemModel` is for building models from WL equations and does not accept raw Modelica source (fails with `SystemModel::nvr`).

### 2. Simulate

```wolfram
sim = SystemModelSimulate["MyPackage.MyModel", {tmin, tmax}]              (* simulates over the simulation interval {tmin, tmax} *)
```

```wolfram
sim = SystemModelSimulate["MyPackage.MyModel", {"var1", "var2", "var3"}, {tmin, tmax}]     (* store results for specific variables, more efficient when only some results are of interest *)
```
Note: the list controls exactly what is stored — parameters you don't name in
it are dropped too, so `sim["ParameterNames"]` returns `{}` unless the list
includes them (e.g. `{"var1", "k"}`). Simulate without a variable list to keep
everything.

```wolfram
sim = SystemModelSimulate["MyPackage.MyModel", {"var1", "var2", "var3"}, {tmin, tmax}, spec]     (* uses Association spec for initial values, parameters and inputs *)
```
Allowed spec keys:

| Key | Purpose | Example |
|-----|---------|---------|
| `"ParameterValues"` | Override tunable parameters | `"ParameterValues" -> {"k" -> 2.5, "m" -> 10}` |
| `"InitialValues"` | Override start values | `"InitialValues" -> {"x" -> 0.1}` |
| `"Inputs"` | Drive top-level inputs | `"Inputs" -> {"u" -> (Sin[2 * #] &)}` |

```wolfram
sim = SystemModelSimulate["MyPackage.MyModel", {"var1", "var2", "var3"}, {tmin, tmax}, <|"ParameterValues" -> {"k" -> 2.5, "m" -> 10}|>]     (* uses the indicated parameter values *)
```

Pass `ProgressReporting -> False` — it drops the progress UI, which makes
calls faster and keeps output clean. (Other options like `Method` for solver
choice are rarely needed; see the `SystemModelSimulate` reference page if a
model demands a specific solver.)

**Parameter sweeps** — pass a list for any parameter:

```wolfram
sweep = SystemModelSimulate["MyModel", {0, 10}, <|"ParameterValues" -> {"k" -> {1.0, 2.0, 5.0}}|>]
(* sweep is a list of SystemModelSimulationData objects *)
```

### 3. Extract numerical data

`SystemModelSimulate` returns a `SystemModelSimulationData` object. Several access patterns:

```wolfram
sim["Properties"]                (* list of properties this object supports *)
sim["VariableNames"]             (* list all time-dependent variables *)
sim["ParameterNames"]            (* list all parameters *)

(* An InterpolatingFunction or a Function over the simulation interval: *)
f = sim["var1"];
f[500.0]                         (* value of variable at t = 500.0 *)

(* Values at a single time: *)
sim[{"var1", "var2", "var3"}, t]                          (* list of variable values at t *)
sim[{"var1", "var2", "var3"}, 500.0]                      (* list of variable values at 500.0 *)

(* Values at a list of times: *)
sim[{"var1", "var2", "var3"}, {500.0, 700.0}]                      (* list of lists: values at 500.0 and 700.0 for each variable *)

(* Raw time/value pairs (faster than interpolation). Repeated times indicate events: *)
sim["RawData", {"var1", "var2"}]

(* All variables as a rules list, this is time consuming for large number of stored variables *)
sim["VariableValues"]

(* Association of parameter values, initial values and inputs used in the simulation call*)
sim["Configuration"]
```

### 4. Plot

```wolfram
SystemModelPlot[sim]                          (* default plots stored in the model — errors with SystemModelPlot::nov if the model has no stored plots; pass a variable list in that case *)
SystemModelPlot[sim, {"x", "y"}]              (* plot specific variables *)
SystemModelPlot[{simA, simB, simC}, {"x"}]    (* compare results for several simulations — auto legend *)
SystemModelPlot[model, ...]                   (* simulate + plot in one shot *)
```

Useful options: `PlotLegends`, `PlotStyle`, `Filling`, `TargetUnits`, `ScalingFunctions`.

For a custom plot with `Plot` or `ParametricPlot`:

```wolfram
(* with Plot *)
Plot[Evaluate[sim[{"x", "y"}, t]], {t, tmin, tmax}, PlotLegends -> {"x", "y"}]

(* with ParametricPlot *)
ParametricPlot[Evaluate[sim[{"x", "y"}, t]], {t, tmin, tmax}]
```

(Note: using `Evaluate` is important so `sim[...]` is resolved once, not at every plot point.)

### 5. Resample onto a uniform grid (common for ML)

```wolfram
vars = {"var1", "var2", "var3"};
ts = Range[tmin, tmax, dt];
mat = Transpose[sim[vars, ts]];
(* mat has Dimensions {Length[ts], Length[vars]} — ready for AnomalyDetection etc. *)
```

## Canonical end-to-end example

```wolfram
(* 1. Load *)
Import["/path/to/pkg/package.mo", "MO"];   (* use the OS-appropriate absolute path *)

(* 2. Simulate three scenarios *)
scenarios = {"pkg.Baseline", "pkg.Scenario1", "pkg.Scenario2"};
sims = SystemModelSimulate[#, {0, 1000}, ProgressReporting -> False] & /@ scenarios;

(* 3. Inspect what's in there *)
Take[First[sims]["VariableNames"], UpTo[10]]

(* 4. Extract a 3-variable time series from each scenario *)
variables = {"mIn.m_flow", "pTee.p", "mA.m_flow"};
ts = Range[0, 1000, 2.];
series = Through[sims[variables, ts]];
(* series is an array, has Dimensions {Length[scenarios], Length[variables], Length[ts]}, can be indexed with Part *)

(* 5. Compare with SystemModelPlot *)
SystemModelPlot[sims, variables]

(* 6. Downstream: anomaly detection trained on baseline *)
detector = AnomalyDetection[Transpose[series[[1]]]];
anomalyScores = detector[Transpose[series[[2]]], "RarerProbability"];
```

## Gotchas

- **Printing `SystemModelSimulationData` inside a List dumps every variable name.**
  A raw `sim` object displays compactly, but wrapping it in a `List` (e.g.
  evaluating `{sim1, sim2}` as the output of a cell) strips
  the compact box form and you get the entire variable-name list printed
  inline — hundreds of kilobytes of output per simulation.
  **Fix:** end the assignment cell with `;`, then either pass the list
  directly into consumers (`SystemModelPlot[sims, ...]`, extractions)
  without displaying it, or produce a compact summary:
  ```wolfram
  KeyTake[sim1["Summary"], {"ModelName", "SimulationInterval", "VariableValues"}]         (* single simulation sim1 *)

  "NumberOfSimulations" -> Length[sims]                                                   (* list of simulations sims *)
  ```

- **`AnomalyDetection[...]` has no `"AnomalyProbability"` property.** The continuous
  score is called `"RarerProbability"`, and its polarity is the opposite of
  what the name "anomaly probability" suggests: it is **high (→ 1) for typical
  samples** and **low (→ 0) for anomalies**. For an intuitive "higher =
  more anomalous" score, compute `1 - detector[x, "RarerProbability"]`.
  For a hard yes/no, `detector[x]` (or `"Decision"`) is already polarity-correct.

- **`SystemModelValidationData[...]["FirstFailureTime"]` and other properties return a Dataset, not a number.**
  On passing scenarios it is an empty Dataset; on failing scenarios it wraps
  the scalar in a row that also includes an empty `Configuration` column.
  Extract cleanly before displaying:
  ```wolfram
  prop = "FirstFailureTime";
  d = SystemModelValidationData[...][prop];
  With[{n = Normal[d, Dataset]},
    If[n === {}, "\[LongDash]", First[n][prop]]    (* "FirstFailureTime" for the first failure configuration, if there is one *)
  ];
  ```

- **Variable name mismatches.** Modelica uses dots: `pipe1.port_a.p`. Protected / mangled names can appear. Always run `sim["VariableNames"]` when in doubt instead of guessing.
- **`.mat` files from a kernel simulation aren't readable via `sim[...]` directly.** Those come from the WSM kernel simulation. To read them in WL, load via `SystemModelSimulationData[path]` — and even then, the file path must still exist. Prefer going through `SystemModelSimulate` end-to-end when you need data in WL.
- **Load `` WSMLink` `` in its own evaluation, before any code that uses it.**
  WL binds symbols at parse time, so a single evaluation containing both
  ``Needs["WSMLink`"]`` and `WSMRealTimeSimulate[...]` creates
  ``Global`WSMRealTimeSimulate`` *before* the package loads, and the call
  returns unevaluated (`Symbol::undefined`). Evaluate the `Needs` on its own
  first, then the code. If loading itself emits messages (e.g.
  `Set::write: Tag ... is Protected`), the load went wrong — don't dismiss it;
  restart the kernel and load cleanly, and report it if it persists.
- **Unit annotations.** `SystemModelPlot` respects Modelica `unit` annotations; variables without units show raw numbers.

## Requirements and validation

For anomaly detection, fault diagnosis, or safety-case work, Wolfram ships a
**requirement language** plus `SystemModelValidate` that expresses assertions
directly over the simulated trajectory — no scaffolding needed.

### The requirement language

Temporal operators that wrap a predicate over a free time variable `t`:

| Operator | Meaning |
|----------|---------|
| `SystemModelAlways[t, texpr]` | `texpr` holds for every `t` in the validation interval |
| `SystemModelAlways[t, cond, texpr]` | `texpr` holds whenever `cond[t]` is true (scoped "always") |
| `SystemModelEventually[t, texpr]` | `texpr` holds at some `t` |
| `SystemModelUntil[...]` | Hold until another condition fires |
| `SystemModelSustain[...]` | Hold continuously for at least a given duration |
| `SystemModelDelay[...]` | Shift a condition in time |

Predicates compose with `<`, `<=`, `>`, `>=`, `==`, `&&`, `||`, `!`, etc.,
and reference any variable from the model by bracket syntax `var[t]`, or parameter as `par`.

### Calling SystemModelValidate

```wolfram
(* Against a live model *)
val = SystemModelValidate[model, req]
val = SystemModelValidate[model, req, spec]

(* Against an already-computed SystemModelSimulationData *)
val = SystemModelValidate[sim, req]

(* Direct property extraction *)
SystemModelValidate[sys, req, "FailureIntervals"]
```

Unlike `SystemModelSimulate`, `SystemModelValidate` does **not** accept a bare
`{tmin, tmax}` as a positional argument — a simulation interval must be passed
inside `spec` as `"SimulationInterval" -> {tmin, tmax}`. Passing `{tmin, tmax}`
positionally leaves the call unevaluated.

Names in `"ParameterValues"` must match the model's parameters exactly, or the
call fails with `SystemModelValidate::pvf` ("not among the expected ones").
When unsure, list them first with `model["ParameterNames"]`.

`Method -> {"InterpolationPoints" -> n}` evaluates the requirement on an
`n`-point time grid — reported failure times snap to grid points, and fewer
points mean less post-processing on large sweeps.

`spec` is an `Association` with any of:

```wolfram
<|
  "InitialValues"      -> {v1 -> val1, ...},
  "ParameterValues"    -> {p1 -> val1, ...},     (* accepts lists / intervals / distributions *)
  "Inputs"             -> {in1 -> fun1, ...},
  "SimulationInterval" -> {tmin, tmax},
  "SimulationCount"    -> 200,                    (* for stochastic sweeps *)
  "MaxFailureIntervals"-> Automatic
|>
```

### SystemModelValidationData properties

| Property | Returns |
|----------|---------|
| `"SuccessProbability"` | Overall pass/fail or probability across a sweep |
| `"FailureIntervals"` | Time intervals where the requirement was violated |
| `"FirstFailureTime"` | First `t` where a failure occurred |
| `"Configuration"` | Parameter/initial-value/inputs that produced a failure |
| `"FailurePlot"` | Pass/fail step chart over time (index selects the failure configuration, e.g. `val["FailurePlot", 1]`) |
| `"FailureIntervalsPlot"` | Time-window diagram of failure intervals |

For a plot of the variable itself against its requirement bound with the
failure intervals shaded, validate an existing simulation and combine
trajectory, bound and intervals:

```wolfram
requirementFailurePlot[sim_, var_, bound_, val_] :=
 Module[{ints, ymin, ymax, pad, tspan},
  ints = Join @@ (#FailureIntervals & /@ Normal[val["FailureIntervals"]]);
  {ymin, ymax} = MinMax[Join[sim[var]["ValuesOnGrid"], {bound}]];
  pad = 0.08 (ymax - ymin);
  tspan = sim["SimulationInterval"];
  SystemModelPlot[sim, var,
   Prolog -> {Opacity[0.12], Red,
     Rectangle[{Min[#], ymin - pad}, {Max[#], ymax + pad}] & /@ ints},
   Epilog -> {Dashed, Red, Line[{{tspan[[1]], bound}, {tspan[[2]], bound}}]},
   PlotRange -> {ymin - pad, ymax + pad}]]

sim = SystemModelSimulate[model, 1000];
val = SystemModelValidate[sim, SystemModelAlways[t, "tank1.level"[t] < 0.45]];
requirementFailurePlot[sim, "tank1.level", 0.45, val]
```

This is the single-run form (validate the `sim` you plot); for a sweep, pick
one configuration's intervals instead of joining all rows.

### Uncertainty bands

`SystemModelUncertaintyPlot[sys, spec]` plots median and quantile bands over a
stochastic sweep. It takes the same uncertainty spec as `SystemModelValidate`
(`"ParameterValues"`, `"SimulationCount"`, ...), with the plotted variables
under `"Outputs"`:

```wolfram
SystemModelUncertaintyPlot[model, <|
  "Outputs" -> {"tank1.level"},
  "ParameterValues" -> {"inflow.qFlow" -> NormalDistribution[0.001, 0.0001]},
  "SimulationCount" -> 200|>,
  Method -> <|"SimulationMethod" -> {"InterpolationPoints" -> 25}|>]
```

It is a two-argument form: passing variables positionally leaves the call
unevaluated. Its interpolation-points setting nests under the
`"SimulationMethod"` key (unlike `SystemModelValidate`'s flat `Method` list).

### Surrogate models for fast repeated evaluation

When a workflow needs many evaluations across a parameter range (optimization,
Pareto sweeps, interactive exploration), train a surrogate once and evaluate
it in milliseconds instead of resimulating:

```wolfram
sur = SystemModelSurrogateTrain[model, <|
  "Outputs" -> {"tank1.level", "tank2.level"},
  "ParameterValues" -> {"inflow.qFlow" -> CenteredInterval[0.001, 0.0002]},
  "SimulationCount" -> 200, "SimulationInterval" -> {0, 1000},
  "ReservoirNeuronsCount" -> 100, "InterpolationPoints" -> 100|>];

{level1Fun, level2Fun} = sur["ParametricFunction"];   (* one function per output *)
(level1Fun @@ {0.0011})[500]                          (* trajectory value at t = 500 *)
```

- Same spec family as `SystemModelValidate` / `SystemModelUncertaintyPlot`,
  plus training hyperparameters as spec keys: `"ReservoirNeuronsCount"`,
  `"InterpolationPoints"`, `"CentroidsCount"`, `"CholeskyFactorDensity"`.
  Bigger reservoirs are not automatically better — sweep reservoir size ×
  sample count and pick the knee of `sur["MeanLoss"]` (a per-output table).
- For multi-parameter design spaces, pass an explicit joint-sample matrix:
  `"ParameterValues" -> {{"p1", "p2"} -> samples}` (n×d rows, e.g. Latin
  Hypercube). Training then runs exactly those n samples — omit
  `"SimulationCount"`.
- With one output, `"ParametricFunction"` is a single function; with several,
  a list in `"Outputs"` order. Call as `fun @@ point`; the result is a
  trajectory `InterpolatingFunction` of time.
- Surrogates serialize: `Export["sur.wxf", sur, "WXF"]`, `Import` back —
  train once, reuse across sessions.
- If the downstream use is scalar objectives (cycle time, integrated losses,
  peaks), compute them as variables inside the Modelica model and include
  them in `"Outputs"` — applying quadrature or root-finding to
  surrogate-predicted trajectories compounds error.
- Other properties: `"SystemModel"` (use like any model), `"Net"`,
  `"SimulationCount"`, error plots `"RMSEPlot"` / `"MAEPlot"` / `"RRMSEPlot"`.
  Check an error plot (or spot-check against a real simulation) before
  trusting a surrogate.

### Why this matters for anomaly detection

A physics-based requirement is already a detector. Two patterns worth knowing:

**1. Mass / energy balance as a hard requirement.** In a pipe network:

```wolfram
leakFree = SystemModelAlways[t, Abs["mIn.m_flow"[t] - "mA.m_flow"[t] - "mB.m_flow"[t]] < 0.5];

val = SystemModelValidate[sim, leakFree];

val["ValidationSucceeded"]
(* True / False - flags a leak instantly *)

val["FailureIntervals"]
(* Dataset with failure intervals *)
```

A detector you can explain to a CIO in one sentence, derived from first principles, with zero training data.

**2. Physics-based baseline envelope.** For signatures that don't come from a
conservation law, run the healthy model once, build a tolerance band around
each channel, and validate future runs against it.

**Do not splice a raw `InterpolatingFunction` (i.e. `simBaseline["pTee.p", t]`
or `simBaseline["pTee.p"]`) directly into the requirement** — the validator
walks the requirement expression looking for model variables, descends into the
InterpolatingFunction's packed-array internals, and fails with `SystemModel::nvr`
(`"Developer\`PackedArrayForm" is not a valid identifier`) /
`SystemModelValidate::bms`. Instead, capture the baseline trajectory in a
`NumericQ`-guarded wrapper function so the validator treats it as opaque and
only ever evaluates it at numeric sample times:

```wolfram
simBaseline = SystemModelSimulate["pkg.Baseline", {0, T}];
simScenario1 = SystemModelSimulate["pkg.Scenario1", {0, T}];

ref = simBaseline["pTee.p"];              (* the InterpolatingFunction *)
gref[tt_?NumericQ] := ref[tt];            (* opaque numeric-guarded reference *)
req = SystemModelAlways[t, Abs["pTee.p"[t] - gref[t]] < 0.05 * Abs[gref[t]]];

val = SystemModelValidate[simScenario1, req];

val["ValidationSucceeded"]
```

### When to use what

| Situation | Use |
|-----------|-----|
| A conservation law or a clean inequality defines "healthy" | Requirement + `SystemModelValidate` |
| Signature is multivariate / subtle / data-driven | `AnomalyDetection` on extracted channels |
| Need both a *yes/no* certificate AND continuous anomaly scoring | Layer them — requirement for the hard gate, `AnomalyDetection` for early warning |
| Hardware-in-the-loop, formal safety case | Requirement language — it's the proof artifact you hand to auditors |

The combination is the Wolfram story: physics-aware requirements set the
floor (no false negatives for *known* faults), statistical anomaly detection
catches the unknown ones.

## Parameter calibration (fitting a model to measured data)

`SystemModelCalibrate` takes measured data, a model, and a list of parameters
to tune, and returns a model with calibrated parameter values, or, if specified
a `CalibratedSystemModel` object with information on the fitted values,
residuals, and prediction bands.

### Signature

```wolfram
SystemModelCalibrate[data, model, params]
SystemModelCalibrate[data, model, params, spec]
SystemModelCalibrate[..., "prop"]     (* direct property extraction *)
```

The bare `SystemModelCalibrate[data, model, params]` form returns a **calibrated
`SystemModel`** (ready to simulate), *not* an information object — so
`cal["CalibratedParameters"]` / `cal["RMSE"]` on it will **not** resolve. To get
the fitted values, residuals, or bands, either use the direct property form
`SystemModelCalibrate[..., "CalibratedParameters"]` or grab the info object once
with `SystemModelCalibrate[..., "CalibratedSystemModel"]` and query that.

The measured data's time span must be consistent with the model's simulation
interval, otherwise calibration fails with `SystemModelCalibrate::bvs`. Pass
`spec` with `"SimulationInterval" -> {tmin, tmax}` (or supply data only within
the model's interval).

- `data` is an `Association` mapping the measured variable name to a list of
  `{t_i, y_i}` pairs: `<|"sensor.p" -> {{0., 1.2e5}, {0.1, 1.4e5}, ...}|>`.
  Multiple variables can be calibrated against simultaneously by adding more
  entries to the association.
- `model` is a `SystemModel[...]` or model-name string.
- `params` is a list of parameter names or `{name, initial_guess}` pairs:
  `{{"compressor.a0", 100000.}, {"compressor.a1", 1000.}}`.
  Initial guesses far from the truth slow convergence but don't prevent it.

### Key properties of the result

| Property | What it gives you |
|----------|-------------------|
| `"CalibratedParameters"` | The fitted values as a rules list, ready to pass into `SystemModelSimulate` via `"ParameterValues"`. |
| `"CalibratedSystemModel"` | Information object with properties. |
| `"ParameterConfidence"` | Uncertainty on each fitted parameter. |
| `"RMSE"` | Root-mean-square residual between measured and predicted output. |
| `"SinglePredictionBandsPlot"` | Visual diagnostic: measured vs. predicted with 95% bands. |

### Practical tips

- **Parameters live on the component, not the testbench.** Reference them with
  their full Modelica path: `"compressor.a0"`, not `"a0"`.
- **Starting guesses matter for robustness.** Order-of-magnitude right is
  fine; being off by a sign will usually still converge but slowly. Bad
  starting guesses with narrow parameter bounds is where calibrations get
  stuck.

## Interactive exploration with sliders (`SystemModelManipulate`)

For a **notebook `Manipulate` over model parameters and initial values** —
sliders that re-simulate and re-plot on release — use the Function Repository
resource:

```wolfram
ResourceFunction["SystemModelManipulate"][model, {"inflow.qFlow", 0.0005, 0.0015}]
```

With no control spec it exposes all top-level parameters and initial values;
controls follow `Manipulate` syntax (`{u, umin, umax}`, `{{u, uinit}, ...}`,
discrete value lists). Its defaults are pre-tuned so slow models stay stable
(`ContinuousAction -> False`, `SynchronousUpdating -> False` — simulate on
slider release, not on every drag tick). Prefer this over hand-rolling
`Manipulate[SystemModelPlot[SystemModelSimulate[...]], ...]`, which with
default `Manipulate` settings re-simulates on every drag tick. First use
fetches the resource from the cloud.

## Real-time interactive simulation (`WSMRealTimeSimulate`)

For a **live simulation you interact with while it runs** — pause/resume, change
inputs or parameters mid-run, read variable values at the current sim time —
use `WSMRealTimeSimulate` from the `` WSMLink` `` package instead of the batch
`SystemModelSimulate`. This is the right tool for turn-based / agent-in-the-loop
setups (an LLM or optimizer making sequential decisions against a running
model), hardware-style demos, and injecting disturbances mid-run. It avoids the
extract-final-state / re-initialize plumbing that chunked batch simulation
would need: hidden states carry over automatically because the simulation never
stops.

Works in standalone Wolfram Language — no separate System Modeler installation
is needed. The model must already be loaded (e.g. via `Import[..., "MO"]`).

### Recipe

```wolfram
Needs["WSMLink`"];

conn = WSMRealTimeSimulate["MyModel", stopTime,
  Method -> {"WriteSimulationData" -> True,   (* log the trajectory for later retrieval *)
             "SimulationRate" -> 10}]         (* 10 sim-seconds per wall-second *)
(* conn is a WSMSimulationConnection; the simulator runs as a separate local process *)

conn["Start"];                                       (* run *)
WSMLink`Simulate`SetInputs[conn, "u" -> 2];          (* change a top-level input, effective immediately *)
Pause[3];                                            (* let it run 3 wall-seconds = 30 sim-seconds *)
conn["Pause"];                                       (* freeze sim time *)

conn[{"y", "x"}]                                     (* read live values at current sim time *)

WSMLink`Simulate`SetParameters[conn, "k" -> 5];      (* parameters can change mid-run too *)
conn["Start"];                                       (* resume — states carried over *)
...
conn["Stop"];
sd = Quiet@Check[conn["SimulationData"], $Failed];   (* best-effort — unreliable headless, see gotchas *)
If[sd =!= $Failed, WSMPlot[sd, {"y"}]];
conn["Close"];                                       (* kill the simulator process when done *)
```

Other useful pieces: ``WSMLink`Simulate`SetInputs[conn, "u" -> Function[...], RefreshRate -> 0.5]``
(input driven by a WL function evaluated periodically),
``WSMLink`Simulate`AddDataMonitor[conn, f, vars]`` (callback when variables
update — event triggers like "cash < 0 → stop"), and `WSMRealTimePlot` for a
continuously updating plot in a notebook front end.

### Turn-based agent loop (the pattern that works)

```wolfram
(* one turn: run a fixed chunk of sim time, then hand control to the agent *)
conn["Start"]; Pause[turnWallSeconds]; conn["Pause"]; Pause[0.3];  (* let pause settle *)
now  = First[conn[{"clk"}]];        (* ACTUAL sim time — see gotchas: never assume it *)
obs  = conn[{"revenue", "cash"}];   (* observables for the agent *)
(* ... agent decides ... *)
WSMLink`Simulate`SetInputs[conn, {"price" -> p, "adBudget" -> a}];
(* next turn *)
```

The connection object persists in the kernel session, so an agent driving the
loop through separate evaluator calls (e.g. over MCP) works — create `conn`
once, keep using it across calls.

### Driving the connection headless — do it this way

The notebook front end papers over several connection behaviors that surface
when WSMLink is driven headless (e.g. over MCP). These rules keep the loop
solid:

- **Read everything through live variable reads.** `conn[{"y", ...}]` is
  reliable headless. Don't branch on `conn["Time"]` or `conn["State"]` — they
  return stale values (`"Time"` stuck near 0; `"State"` reporting `"Running"`
  after a successful `Pause`/`Stop`, or `"NotStarted"` while the simulation is
  demonstrably running).
- **For sim time, put a clock state in the model and live-read it.** Plain
  `time`, or an alias like `tclock = time`, is alias-eliminated and reads back
  as `0.` over the connection. A genuine state works:
  ```modelica
  Real clk(start = 0, fixed = true);
  equation
    der(clk) = 1;   // clk == sim time, live-readable via conn[{"clk"}]
  ```
- **Timestamp each turn from `clk`, never by arithmetic.** Each Start→Pause
  window overshoots by roughly 10–50 ms of wall-clock command latency, which
  becomes `latency × SimulationRate` of extra sim time (measured: +0.03–0.05
  sim-s per window at rate 1; up to +4 sim-s at rate 100). The error is always
  positive, per-window jitter, and does not accumulate beyond that — but it
  means `nTurns × Pause × rate` drifts from the truth. Read `clk` back after
  each pause instead.
- **Collect the trajectory yourself while the simulation runs** — log the
  observables you need at each turn with live reads, or accumulate them with
  ``WSMLink`Simulate`AddDataMonitor``. `conn["SimulationData"]` is unreliable
  headless: it always fails while paused mid-run, and often fails with
  `WSMSimulationConnection::nos` even after `conn["Stop"]` or natural
  completion, regardless of `"WriteSimulationData" -> True` or a stored-vars
  list at creation. Treat a successful retrieval as a bonus, not a plan.
- **Expose every decision knob as a top-level `input`.** `SetInputs` targets
  only declared top-level `input` variables; knobs buried inside components
  (time tables, ramp/pulse sources) must first be promoted to top-level
  `input`s in a model variant.

## Common follow-on tools

Once data is in WL, the useful downstream functions are:

| Tool | Use |
|------|-----|
| `SystemModelValidate` + `SystemModelAlways` / `SystemModelEventually` | Requirement-based validation (mass balance, envelopes, safety bounds) |
| `SystemModelUncertaintyPlot` | Median/quantile uncertainty bands from stochastic parameter sweeps |
| `SystemModelSurrogateTrain` | Fast trained surrogate for repeated evaluation across a parameter range |
| `ResourceFunction["SystemModelManipulate"]` | Slider-driven interactive exploration of parameters/initial values |
| `AnomalyDetection` | Statistical detector trained on baseline residuals |
| `Predict` / `Classify` | Supervised models trained on simulated scenarios |
| `FindFit` / `NonlinearModelFit` | Parameter identification from data |
| `ModelFit` | Fit/select empirical models on extracted data, with cross-validation |
| `SystemModelCalibrate` | Direct Modelica-aware calibration against measurements |
| `SystemModelParametricSimulate` | Pre-compiled parametric simulator (fast sweeps) |
| `SystemModelLinearize` | Extract a linear model around an operating point |
| `PredictorMeasurements` | Evaluate model performance |

### ModelFit usage notes

`ModelFit` distills sweep or trajectory data into an empirical formula — e.g.
fitting steady-state level vs. flow recovers the valve's quadratic law:

```wolfram
ModelFit[data, {PolynomialModel[1], PolynomialModel[2], PowerModel[]},
  {"Name", "Expression", "RSquared"}]
```

Two traps:

- `ModelFit[data, model]` returns the fitted model as a **callable function**.
  Request properties in the **third argument** — `fit["Expression"]` does not
  query a property, it silently *evaluates the model at the string*.
- For model selection, pass **model objects** (`PolynomialModel[2]`,
  `PowerModel[]`, ...). A list of string names (`{"Linear", "Quadratic"}`)
  fails with `ModelFit::nofit` even on clean data; string names work only in
  the single-model form.

## Writing results to disk

```wolfram
(* Native WL — fast round-trip, keeps InterpolatingFunctions *)
DumpSave["sim.mx", sim];
Get["sim.mx"];      (* restores the symbol `sim` in place — do NOT write `sim = Get[...]` *)

(* Portable / CSV — for handoff to Python etc. *)
Export["sim.csv", sim[variables, times]];
```

**Do not write `sim = Get["sim.mx"]`.** `Get` on a `DumpSave` file restores the
saved symbol (`sim`) *in place* and itself returns `Null`, so the assignment
would immediately clobber the just-restored value with `Null`. Just evaluate
`Get["sim.mx"]` (or `<< "sim.mx"`) on its own — `sim` is valid afterward.
