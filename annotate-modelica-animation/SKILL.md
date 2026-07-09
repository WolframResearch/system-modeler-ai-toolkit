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
get it right and confirm with `validate-modelica`.

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
