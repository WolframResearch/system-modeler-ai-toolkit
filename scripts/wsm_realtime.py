"""Run a compiled System Modeler model as a real-time server and interact with it.

  python wsm_realtime.py info <exe-or-build-dir> [--model NAME]
  python wsm_realtime.py run  <exe-or-build-dir> --watch a,b --duration 20 [--scale 1]
                              [--set T:name=value ...] [--param T:name=value ...]
                              [--csv out.csv] [--print-every 1] [--interval 0.01]
                              [--step 0.01 --method explicit-euler]
  python wsm_realtime.py plot <exe-or-build-dir> --watch a,b [--sliders name:lo:hi,...]
                              [--toggles name,...] [--scale 1] [--window 60]
  python wsm_realtime.py cmd  --attach host:port [-c 'getVariableNames()' -c '...']
                              (no -c: read one command per line from stdin)

<exe-or-build-dir> is the simulation executable or a directory holding <Model>*.exe and its .sim
(a launcher build directory). --attach host:port uses a server that is already running instead.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wsmsim import (METHODS, NOT_STARTED, WsmError, WsmSimulation, find_simulation,  # noqa: E402
                    _strip_exe, sim_start_time)


def _error(message) -> None:
    sys.stdout.flush()
    print("ERROR:", message, file=sys.stderr)


def _open(args) -> WsmSimulation:
    if args.attach:
        host, port = args.attach.rsplit(":", 1)
        return WsmSimulation.attach(host, int(port))
    exe, sim = find_simulation(args.target, args.model)
    print("executable:", exe)
    end = args.end
    if end is None:
        if args.fast and getattr(args, "duration", None):
            end = sim_start_time(sim) + args.duration
        else:
            end = 1e6
    return WsmSimulation.launch(exe, sim, end=end, realtime=not args.fast, scale=args.scale,
                                step=args.step, method=args.method, interval=args.interval,
                                log_path=_strip_exe(exe) + "_server.log")


def _parse_value(text: str):
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        return float(text)


def _parse_events(specs: list) -> list:
    """['4:P1set=4500', ...] -> [(4.0, 'P1set', 4500)] sorted by time."""
    out = []
    for spec in specs or []:
        when, assignment = spec.split(":", 1)
        name, value = assignment.split("=", 1)
        out.append((float(when), name.strip(), _parse_value(value.strip())))
    return sorted(out, key=lambda e: e[0])


def _gaps(times: list) -> int:
    """Samples the server skipped: intervals clearly longer than the typical one."""
    steps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    if not steps:
        return 0
    typical = steps[len(steps) // 2]
    return sum(1 for d in steps if d > 1.5 * typical)


def cmd_info(args) -> int:
    with _open(args) as s:
        print("model:      ", s.scs.model_name())
        print("inputs:     ", ", ".join(s.inputs) or "(none)")
        print("outputs:    ", ", ".join(s.outputs) or "(none)")
        print("tunable:    ", ", ".join(s.scs.tunable_parameter_names()) or "(none)")
        print("states:     ", ", ".join(s.scs.state_names()) or "(none)")
        if s.inputs:
            label = "input start:" if s.scs.state() == NOT_STARTED else "input now:  "
            print(label, ", ".join("%s = %g" % kv for kv in s.get_values(s.inputs).items()))
    return 0


def _reached(t: float, target: float) -> bool:
    return t >= target - 1e-9 * max(1.0, abs(target))


def cmd_run(args) -> int:
    watch = [w for w in args.watch.split(",") if w]
    if not watch:
        _error("--watch needs at least one variable")
        return 2
    inputs = _parse_events(args.set)
    params = _parse_events(args.param)
    if args.fast and any(when > 0 for when, _, _ in inputs + params):
        _error("timed --set/--param changes need real-time pacing; drop --fast (use --scale to run faster)")
        return 2
    with _open(args) as s:
        unknown = [n for _, n, _ in inputs if n not in s.inputs]
        if unknown:
            _error("not input variables: %s (inputs are %s)" % (unknown, s.inputs))
            return 2
        started = s.scs.state() != NOT_STARTED
        tunable = s.scs.tunable_parameter_names()
        settable = tunable if started else s.scs.parameter_names()
        bad = [n for when, n, _ in params if n not in (settable if when <= 0 else tunable)]
        if bad:
            _error("cannot set parameters %s at those times (tunable: %s)" % (bad, ", ".join(tunable) or "none"))
            return 2
        for when, name, value in [e for e in params if e[0] <= 0]:
            s.set_parameters({name: value})
        sub = s.subscribe(watch)
        base = s.time()
        inputs = [(base + when, n, v) for when, n, v in inputs]
        params = [(base + when, n, v) for when, n, v in params if when > 0]
        target = base + args.duration
        if not started:
            s.start()
        pacing = ("paced by its own settings" if args.attach else
                  "without real-time pacing" if args.fast else "at %gx real time" % args.scale)
        print("running %s for %.1f simulated s from t = %g %s" % (s.scs.model_name(), args.duration, base, pacing))
        print(" ".join(["     time"] + [w.rjust(12) for w in watch]))
        next_print = base + args.print_every
        t = base
        wall_budget = None if args.fast else args.duration / args.scale + 30
        times = []
        fh = open(args.csv, "w", newline="", encoding="utf-8") if args.csv else None
        try:
            writer = csv.writer(fh) if fh else None
            if writer:
                writer.writerow(["time"] + watch)
            for t, row in s.stream(sub, seconds=wall_budget):
                times.append(t)
                while inputs and t >= inputs[0][0]:
                    _, name, value = inputs.pop(0)
                    s.set_inputs({name: value})
                    print("   >> input %s = %s sent at t = %.3f" % (name, value, t))
                while params and t >= params[0][0]:
                    _, name, value = params.pop(0)
                    s.set_parameters({name: value})
                    print("   >> parameter %s = %s sent at t = %.3f" % (name, value, t))
                if writer:
                    writer.writerow([t] + [row[w] for w in watch])
                if args.print_every and t >= next_print:
                    next_print += args.print_every
                    print(" ".join(["%9.3f" % t] + ["%12.5g" % row[w] for w in watch]))
                if _reached(t, target):
                    break
        except ConnectionError:
            sys.stdout.flush()
            print("the simulation closed the connection", file=sys.stderr)
        finally:
            if fh:
                fh.close()
                print("wrote", args.csv)
        print("packets: %d received, %d dropped here, %d gaps longer than the output interval; final time %.3f"
              % (s.sds.packets, s.sds.dropped, _gaps(times), t))
        if not _reached(t, target):
            _error("simulated time stopped at %.6g, short of %.6g: the simulation ended, runs slower than "
                   "real time, or is chattering on an event (see its server log)" % (t, target))
            return 1
    return 0


def cmd_cmd(args) -> int:
    """Send protocol commands verbatim; print each reply (or the server's error) as received."""
    interactive = not args.command and sys.stdin.isatty()
    with _open(args) as s:
        if interactive:
            print("connected to %s; commands end with an empty line" % s.scs.model_name())

        def run(text):
            try:
                print(s.scs.command_raw(text))
            except WsmError as e:
                print("Error:", str(e).split(" -> ", 1)[-1])

        if args.command:
            for text in args.command:
                run(text)
            return 0
        while True:
            try:
                text = input("> " if interactive else "").strip()
            except EOFError:
                break
            if not text:
                break
            run(text)
    return 0


def cmd_plot(args) -> int:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, CheckButtons, Slider
    except ImportError:
        from _env import reexec_under_managed_venv
        reexec_under_managed_venv(["matplotlib"])
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button, CheckButtons, Slider

    watch = [w for w in args.watch.split(",") if w]
    sliders = [tuple(x.split(":")) for x in (args.sliders or "").split(",") if x]
    toggles = [t for t in (args.toggles or "").split(",") if t]
    s = _open(args)
    sub = s.subscribe(watch)
    start_values = s.get_values([n for n, _, _ in sliders] + toggles) if (sliders or toggles) else {}
    if s.scs.state() == NOT_STARTED:
        s.start()

    n = len(watch)
    fig = plt.figure(figsize=(12, 2.2 * n + 1))
    fig.canvas.manager.set_window_title("System Modeler live: " + s.scs.model_name())
    axes = [fig.add_axes([0.07, 0.08 + (n - 1 - i) * 0.9 / n, 0.62, 0.9 / n - 0.05]) for i in range(n)]
    times = collections.deque(maxlen=200000)
    hist = {w: collections.deque(maxlen=200000) for w in watch}
    lines = []
    for ax, w in zip(axes, watch):
        (ln,) = ax.plot([], [], lw=1.2)
        ax.set_ylabel(w)
        ax.grid(True, alpha=0.3)
        lines.append(ln)
    axes[-1].set_xlabel("simulation time [s]")

    widgets = []
    y = 0.9
    for name, lo, hi in sliders:
        ax = fig.add_axes([0.78, y, 0.18, 0.03])
        sl = Slider(ax, name, float(lo), float(hi), valinit=float(start_values.get(name, lo)))
        sl.on_changed(lambda v, name=name: s.set_inputs({name: v}))
        widgets.append(sl)
        y -= 0.07
    if toggles:
        ax = fig.add_axes([0.78, y - 0.04 * len(toggles), 0.18, 0.05 * len(toggles)])
        state = {t: bool(start_values.get(t, 1)) for t in toggles}
        cb = CheckButtons(ax, toggles, [state[t] for t in toggles])

        def on_toggle(label):
            state[label] = not state[label]
            s.set_inputs({label: state[label]})
        cb.on_clicked(on_toggle)
        widgets.append(cb)
        y -= 0.05 * len(toggles) + 0.06
    paused = {"v": False}
    pause_btn = Button(fig.add_axes([0.78, y - 0.05, 0.085, 0.045]), "Pause/Run")

    def on_pause(_):
        paused["v"] = not paused["v"]
        s.suspend() if paused["v"] else s.resume()
    pause_btn.on_clicked(on_pause)
    widgets.append(pause_btn)
    if s.can_restart:
        restart_btn = Button(fig.add_axes([0.875, y - 0.05, 0.085, 0.045]), "Restart")

        def on_restart(_):
            s.restart()
            paused["v"] = False
            times.clear()
            for w in watch:
                hist[w].clear()
        restart_btn.on_clicked(on_restart)
        widgets.append(restart_btn)
    status = fig.text(0.78, 0.04, "", fontsize=9, family="monospace")

    def refresh():
        got = 0
        while True:
            try:
                sid, (t, vals) = s.sds.queue.get_nowait()
            except Exception:
                break
            if sid != sub:
                continue
            got += 1
            times.append(t)
            for w, v in zip(watch, vals):
                hist[w].append(v)
        if not got:
            return
        t_now = times[-1]
        t0 = max(0.0, t_now - args.window)
        xs = list(times)
        for ax, ln, w in zip(axes, lines, watch):
            ys = list(hist[w])
            ln.set_data(xs, ys)
            ax.set_xlim(t0, max(t_now, t0 + 1))
            vis = [v for t, v in zip(xs, ys) if t >= t0]
            if vis:
                lo, hi = min(vis), max(vis)
                pad = max((hi - lo) * 0.1, 1e-3)
                ax.set_ylim(lo - pad, hi + pad)
        status.set_text("t = %.1f s   packets %d   dropped %d" % (t_now, s.sds.packets, s.sds.dropped))
        fig.canvas.draw_idle()

    timer = fig.canvas.new_timer(interval=100)
    timer.add_callback(refresh)
    timer.start()
    try:
        plt.show()
    finally:
        s.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("target", nargs="?", default=".", help="simulation executable or its build directory")
        p.add_argument("--model", default=None, help="model name when target is a build directory (picks the newest <model>_*.exe)")
        p.add_argument("--attach", default=None, help="host:port of an already running server")
        p.add_argument("--scale", type=float, default=1.0, help="simulated seconds per wall second")
        p.add_argument("--fast", action="store_true", help="no real-time pacing: run as fast as possible")
        p.add_argument("--end", type=float, default=None,
                       help="stop time of the interactive run (default: open-ended; with run --fast, --duration)")
        p.add_argument("--step", type=float, default=None, help="solver step size for the interactive run")
        p.add_argument("--method", default=None, choices=METHODS, help="integrator for the interactive run")
        p.add_argument("--interval", type=float, default=None,
                       help="output interval, which is also the streaming interval (default: the model's)")

    p = sub.add_parser("info", help="list inputs, outputs, tunable parameters and states")
    common(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("run", help="run a scripted scenario and print/record watched variables")
    common(p)
    p.add_argument("--watch", required=True, help="comma-separated variables to stream")
    p.add_argument("--duration", type=float, default=20.0,
                   help="simulated seconds to run, counted from the start or, attached to a running simulation, from now")
    p.add_argument("--set", action="append", metavar="T:NAME=VALUE",
                   help="input change T simulated seconds into the run")
    p.add_argument("--param", action="append", metavar="T:NAME=VALUE",
                   help="parameter change T simulated seconds into the run (T=0 before the start; otherwise tunable only)")
    p.add_argument("--csv", default=None, help="write time + watched variables to this CSV")
    p.add_argument("--print-every", type=float, default=1.0, help="print a row every N simulated seconds (0: none)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("plot", help="live curves with sliders and toggles bound to inputs")
    common(p)
    p.add_argument("--watch", required=True)
    p.add_argument("--sliders", default=None, help="name:min:max,... input sliders")
    p.add_argument("--toggles", default=None, help="name,... Boolean inputs as check boxes")
    p.add_argument("--window", type=float, default=60.0, help="seconds of history shown")
    p.set_defaults(func=cmd_plot)

    p = sub.add_parser("cmd", help="send protocol commands verbatim and print the replies")
    common(p)
    p.add_argument("-c", "--command", action="append", metavar="COMMAND",
                   help="a protocol command, e.g. 'getVariableNames()'; repeatable. Without it, commands are read from stdin")
    p.set_defaults(func=cmd_cmd)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError, TimeoutError, ConnectionError, ValueError) as e:
        _error(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
