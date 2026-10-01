"""
Sampling profiler for a built Modelica simulation: shows which equation blocks
the run spends its time in.

Every sample is charged to the block it was taken in, so the report names the
blocks by share, the variables and components each one solves, and how each
block's cost divides between evaluating its equations and solving them. Use it
after report_blocks.py has shown the equation structure but not which part of it
is expensive; the block indices are the same in both reports.

The build must come from `wsm_run.py --mode diagnose`, which keeps both the debug
symbols that name the functions and the artifacts that map them to blocks.
`wsm_run.py --mode diagnose --profile` does the build and this report in one
step; running this script directly re-runs and re-samples a build that is already
there, skipping only the build.

Sampling uses each platform's own tool: the thread context and dbghelp on
Windows, `/usr/bin/sample` on macOS, `perf` on Linux.

Usage:
    python profile_sim.py --model path/to/M.mo --name Pkg.M [--seconds 60]
    python profile_sim.py --tempdir _wsm_diagnose_temp [--seconds 60]

Examples:
    python profile_sim.py --model Circuit.mo --name Circuit.SlowCase --seconds 90
    python profile_sim.py --tempdir /tmp/diag --top 25
"""

import argparse
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter

import blockmap

# Each needle is matched against the normalized name: "=" exact, "^" prefix,
# otherwise substring. First match wins, so order matters.
CATEGORIES = [
    ("medium: temperature_ph (h->T inversion)", ("temperature_ph",)),
    ("medium: other properties",
     ("Medium.density", "Medium.bulkModulus", "Medium.specificEnthalpy",
      "Medium.specificHeatCapacity", "Medium.dynamicViscosity",
      "Medium.kinematicViscosity", "Medium.thermalConductivity",
      "Medium.vaporPressure", "Medium.gasFraction")),
    ("transcendental math",
     ("Modelica.Math", "_wrapper", "^pow", "^sqrt", "^exp", "^log", "^atan",
      "^tanh", "^sinh", "^cosh", "=trunc", "=ceil", "=floor", "=fabs",
      "=d_int", "=d_sign", "=d_mod", "=sin", "=cos", "=tan", "=asin",
      "=acos", "=atan2", "=cbrt", "=hypot", "=fmod")),
    ("generated equation bodies",
     ("chunkFunction", "solveTearing", "solveMixed", "functionODE", "jacODE",
      "coloredJacobian", "markPreChange", "initialize_blocks",
      "residualFunc", "functionDAE")),
    ("Jacobian linear algebra",
     ("denseGE", "^dtrsm", "^dgemm", "^dlaswp", "^dgetr", "^dlamch", "^idamax",
      "^dscal", "^dger", "^dswap", "^dnrm2", "^daxpy", "^ddot", "^dlange",
      "^lsame", "DenseCopy", "DenseScale", "^SUNDls", "^SUNMat")),
    ("nonlinear solver",
     ("^hybrj", "^enorm", "^dogleg", "^qrfac", "^fdjac", "^r1updt", "^r1mpyq",
      "^newuoa", "NonlinearSolver", "ScalarLinearSystem", "LinearSystem",
      "KinsolSolver", "HybridSolver", "^kin", "^qform", "^dpmpar",
      "GuessIterator")),
    ("integrator and event handling",
     ("^CVode", "^cvode", "^dassl", "^DASSL", "^IDA", "^ida", "^ddas",
      "^ddai", "^ddaj", "^ddat", "^ddaw", "^ddan", "DASRTSolver",
      "solver_loop", "memory_state", "zeroCross", "eventHandling",
      "eventIteration", "^N_V")),
    # Each block solve is entered through a setjmp guard so a failure inside it
    # can be reported against the block. Saving the signal mask is what that
    # costs, and it is charged here rather than to the block's arithmetic.
    ("per-block error-handling guard",
     ("=setjmp", "=sigsetjmp", "=longjmp", "=siglongjmp", "=sigprocmask",
      "=sigaltstack", "=sigtramp", "=pthread_sigmask")),
    ("OS, I/O and allocator",
     ("^memcpy", "^memset", "^malloc", "^free", "emitResult")),
]

# Appended to the last category above; each platform's OS, allocator and libc
# helpers surface under different names.
# Matched after normalization, which strips the leading underscores these names
# carry in the symbol table.
PLATFORM_OS_NEEDLES = {
    "Windows": ("^Zw", "^Nt", "^Rtl", "^Ldr", "^chkstk", "security_check_cookie"),
    "Darwin": ("^platform_", "^xzm_", "^nanov2_", "^szone_", "^malloc_zone",
               "^write_nocancel", "^read_nocancel", "^close_nocancel",
               "^open_nocancel", "^dyld", "=fclose", "=fwrite"),
    "Linux": ("^int_malloc", "^int_free", "^memmove", "^libc_", "^GI_", "^dl_"),
}


def categories():
    """CATEGORIES with this platform's OS/allocator names folded into the last
    group, so a helper the report cannot name does not land in "other"."""
    extra = PLATFORM_OS_NEEDLES.get(platform.system(), ())
    if not extra:
        return CATEGORIES
    label, needles = CATEGORIES[-1]
    return CATEGORIES[:-1] + [(label, tuple(needles) + extra)]


def classify(frame):
    name = blockmap.split_frame(frame)[0]
    for label, needles in categories():
        for n in needles:
            if n.startswith("="):
                if name == n[1:]:
                    return label
            elif n.startswith("^"):
                if name.startswith(n[1:]):
                    return label
            elif n in name:
                return label
    if "." in name or name.startswith("Modelica"):
        return "model and library functions"
    return "other"


_launcher = None


def launcher():
    """wsm_run, which owns the platform table and the build-artifact lookup."""
    global _launcher
    if _launcher is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wsm_run
        _launcher = wsm_run
    return _launcher


def find_build(tempdir):
    """The most recent build in the temp dir -- newest, not first by name, so a
    temp dir reused across models yields the one that was just built."""
    exe = launcher()._find_built_exe(tempdir)
    if exe is None:
        sys.exit("ERROR: no built simulation found in %s -- run wsm_run.py "
                 "--mode diagnose first" % tempdir)
    sim = os.path.splitext(exe)[0] + ".sim"
    return exe, sim if os.path.isfile(sim) else None


def build(model, name, tempdir, extra):
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "wsm_run.py"),
           "--mode", "diagnose", "--model", model, "--name", name,
           "--no-sim", "--tempdir", tempdir] + extra
    if subprocess.call(cmd) != 0:
        sys.exit("ERROR: the model did not build; fix that before profiling")
    return find_build(tempdir)


def load_backend():
    """The launcher owns the platform table; each backend it names exposes
    sample(exe, sim, hz, seconds) -> (Counter of name -> samples, wall seconds,
    (ended_early, log_tail))."""
    try:
        module, tool = launcher().find_profiler()
    except RuntimeError as e:
        sys.exit("ERROR: %s\nUse report_blocks.py for the equation structure and "
                 "check_tearing.py for the torn systems instead." % e)
    if tool:
        os.environ["WSM_PROFILER"] = tool
    return __import__(module)


MIN_SAMPLES = 2000
MAX_RUNS = 200

RETIMED_SIM = "_profile_run.sim"

# The .sim init file carries the simulation interval on its root element, so the
# profiled run can be lengthened without rebuilding the model.
_SIM_END_RE = re.compile(r'(<simulation\b[^>]*?\send=")([^"]*)(")')
_SIM_START_RE = re.compile(r'<simulation\b[^>]*?\sstart="([^"]*)"')


def retime_sim(sim, stop_time, tempdir):
    """A copy of `sim` ending at `stop_time`. The original is left alone -- it is
    the build's own init file, and the user may still want to simulate with it."""
    if not sim:
        sys.exit("ERROR: --stop-time needs the build's .sim init file, which is "
                 "not in the temp dir")
    with open(sim, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    start = _SIM_START_RE.search(text)
    try:
        start = float(start.group(1)) if start else 0.0
    except ValueError:
        start = 0.0
    if stop_time <= start:
        sys.exit("ERROR: --stop-time %g is not after the start time %g"
                 % (stop_time, start))
    retimed, count = _SIM_END_RE.subn(
        lambda m: "%s%g%s" % (m.group(1), stop_time, m.group(3)), text, count=1)
    if not count:
        sys.exit("ERROR: --stop-time: no simulation interval found in %s" % sim)
    out = os.path.join(tempdir, RETIMED_SIM)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(retimed)
    return out


def sample_until(backend, exe, sim, hz, seconds, min_samples=MIN_SAMPLES,
                 result=False):
    """Sample the run, repeating it until `min_samples` have accumulated or the
    time budget is spent.

    A model that simulates faster than the sampler can fill a profile needs more
    runs, not a longer one: `seconds` caps a single run, so one pass over a
    100 ms model yields a hundred samples however high it is set."""
    stacks = Counter()
    wall = 0.0
    runs = 0
    info = (False, [])
    deadline = time.time() + seconds
    while runs < MAX_RUNS:
        left = deadline - time.time()
        if runs and left <= 0:
            break
        got, one_wall, info = backend.sample(exe, sim, hz, max(left, 0.5),
                                             result)
        runs += 1
        stacks.update(got)
        wall += one_wall
        if sum(stacks.values()) >= min_samples:
            break
        if not got and runs >= 3:
            break                # nothing is being sampled; more runs won't help
    return stacks, wall, info, runs


def report(stacks, wall, top, run_info=None, blocks=None, runs=1, result=False):
    """Print the profile. `stacks` maps a call stack (outermost frame first) to
    its sample count; a backend that samples only the instruction pointer gives
    one-frame stacks and the report degrades to that frame."""
    total = sum(stacks.values())
    ended_early, log_tail = run_info or (False, [])
    if not total:
        sys.exit("ERROR: no samples collected in %d run(s) over %.1f s. The "
                 "sampler needs about a second to attach, so a run shorter than "
                 "that ends before sampling starts: give --stop-time T to simulate "
                 "further (no rebuild), long enough for one run to take a few "
                 "seconds. If the runs already take that long, the sampler could "
                 "not attach -- check `wsm_run.py --mode info` for the resolved "
                 "profiler." % (runs, wall))
    print()
    print("Sampled %d stacks over %.1f s%s (%.0f Hz effective)"
          % (total, wall, " across %d runs" % runs if runs > 1 else "",
             total / wall if wall else 0))
    if ended_early:
        failed = any("Unsuccessful" in l or "[error" in l for l in log_tail)
        if failed:
            print("WARNING: the run failed before the time budget, so this "
                  "profile covers only the part that ran. Its last output:")
            for line in log_tail:
                print("    " + line)
        elif runs > 1:
            print("Each run finished on its own, before the time budget (%.1f s "
                  "in total); the profile covers all of them." % wall)
        else:
            print("The run finished on its own in %.1f s, before the time "
                  "budget; the profile covers all of it." % wall)
    if total < 500:
        print("WARNING: %d samples is thin evidence -- profile a slower case, "
              "or raise --seconds." % total)
    if not result:
        print("The profiled run wrote no result file, so writing one is not "
              "counted here.\nEvaluating the output section still is: it runs at "
              "every output point either way.")

    if blocks:
        _report_blocks(stacks, total, top, blocks)
        _report_components(stacks, total, blocks)
        _report_cost_split(stacks, total)
        print("\n" + _attribution_note(stacks))
    else:
        _report_functions(stacks, total, top)


def _attribution_note(stacks):
    total = sum(stacks.values())
    walked = sum(n for stack, n in stacks.items() if len(stack) > 1)
    if walked > 0.9 * total:
        return ("Each sample is charged to the innermost equation block on its "
                "stack, so a\nblock's share includes the solver and linear-algebra "
                "time spent solving it.")
    return ("Call stacks were available for %.0f%% of samples; the rest are charged "
            "to the\nblock whose own code they landed in, which counts time the "
            "solver spends on a\nblock outside it -- so a hard block's true cost is "
            "higher than shown."
            % (100.0 * walked / total if total else 0))


def _leaf(stack):
    return stack[-1]


_SOLVING = ("nonlinear solver", "Jacobian linear algebra")


def _attribute(stack, blocks):
    """The row of the innermost frame of `stack` that maps to a block, so a sample
    taken inside the solver is charged to the block being solved."""
    for depth in range(len(stack) - 1, -1, -1):
        key = blocks.key_for(stack[depth])
        if not key:
            continue
        if len(key[1]) > 1 and any(classify(f) in _SOLVING
                                   for f in stack[depth + 1:]):
            key = blocks.solver_key(stack[depth]) or key
        return key
    return None


def _report_blocks(stacks, total, top, blocks):
    charged = Counter()
    inside = {}                      # block key -> Counter of cost category
    for stack, n in stacks.items():
        key = _attribute(stack, blocks)
        charged[key] += n
        inside.setdefault(key, Counter())[classify(_leaf(stack))] += n

    rows = [(key, n) for key, n in charged.most_common() if key is not None]
    print("\n  share  where the time goes, by equation block")
    for key, n in rows[:top]:
        print("%7.2f %%  %s" % (100.0 * n / total, blocks.describe_key(key)))
        components = blocks.components_of(key)
        if components:
            print("           solves %s" % _some(components))
        sources = blocks.sources_of(key)
        if sources:
            ranked = sorted(sources, key=lambda p: -sources[p][1])
            print("           from %s" % _some(
                [blocks.short_class(p) for p in ranked]))
        parts = ["%s %.0f%%" % (label, 100.0 * c / n)
                 for label, c in inside[key].most_common(3)]
        print("           cost " + " | ".join(parts))
    tail = rows[top:]
    if tail:
        print("%7.2f %%  %d smaller blocks"
              % (100.0 * sum(n for _, n in tail) / total, len(tail)))
    if charged.get(None):
        print("%7.2f %%  outside the model's equations -- integration, result "
              "output, start-up" % (100.0 * charged[None] / total))


def _some(names, limit=4):
    shown = ", ".join(names[:limit])
    return shown + (", +%d more" % (len(names) - limit) if len(names) > limit else "")


def _report_components(stacks, total, blocks):
    """Roll the block time up per component, splitting each block's samples over
    the variables it solves."""
    shares = Counter()
    for stack, n in stacks.items():
        key = _attribute(stack, blocks)
        if key:
            for component, fraction in blocks.component_shares(key).items():
                shares[component] += n * fraction
    if not shares:
        return
    print("\n  share  by model component")
    for component, n in shares.most_common(10):
        print("%7.2f %%  %s" % (100.0 * n / total, component))


def _report_cost_split(stacks, total):
    """The whole run by kind of work, so the split is available without adding up
    the per-block ones."""
    grouped = Counter()
    for stack, n in stacks.items():
        grouped[classify(_leaf(stack))] += n
    print("\n  share  by kind of work, whole run")
    for label, n in grouped.most_common():
        print("%7.2f %%  %s" % (100.0 * n / total, label))


def _report_functions(stacks, total, top):
    """Fallback when the build artifacts that name the blocks are not available."""
    leaves = Counter()
    for stack, n in stacks.items():
        leaves[blockmap.split_frame(_leaf(stack))[0]] += n
    grouped = Counter()
    for sym, n in leaves.items():
        grouped[classify(sym)] += n
    print("\n  share  where the time goes")
    for label, n in grouped.most_common():
        print("%7.1f %%  %s" % (100.0 * n / total, label))
    print("\n  share  individual functions")
    for sym, n in leaves.most_common(top):
        print("%7.2f %%  %s" % (100.0 * n / total, sym[:100]))
    print("\nSelf time only: a helper like sqrt or exp is charged to itself, not\n"
          "to the equation that called it, so a category's true cost is at least\n"
          "what is shown.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="path to the .mo file or library directory")
    ap.add_argument("--name", help="full dotted model name")
    ap.add_argument("--tempdir", help="directory of an existing --mode diagnose build")
    ap.add_argument("--seconds", type=float, default=60.0,
                    help="how long to profile before stopping the run (default 60)")
    ap.add_argument("--hz", type=int, default=500, help="requested sample rate (default 500)")
    ap.add_argument("--top", type=int, default=20,
                    help="equation blocks to list (default 20)")
    ap.add_argument("--stop-time", type=float, metavar="T",
                    help="profile the model run out to this simulation time "
                         "instead of its own stop time. No rebuild -- use it when "
                         "the model finishes too fast to sample.")
    ap.add_argument("--result", action="store_true",
                    help="write a result file during the profiled run, so the "
                         "cost of writing one is included. Off by default: the "
                         "trajectory is the same either way, and a long run would "
                         "leave a large file behind.")
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES, metavar="N",
                    help="keep re-running the model until this many samples have "
                         "accumulated, or --seconds runs out (default %d)"
                         % MIN_SAMPLES)
    ap.add_argument("--load-library", action="append", default=[], metavar="NAME",
                    help="installed non-MSL library to load, repeatable")
    ap.add_argument("--load", action="append", default=[], metavar="PATH",
                    help="package.mo or .moe to load by path, repeatable")
    ap.add_argument("--msl", choices=["auto", "yes", "no"],
                    help="load MSL (default: yes when a library is loaded, "
                         "otherwise auto-detected from the model)")
    ap.add_argument("--msl-version", metavar="VER", help="force an MSL version")
    args = ap.parse_args()

    backend = load_backend()

    if args.tempdir and not (args.model or args.name):
        tempdir = args.tempdir
        exe, sim = find_build(args.tempdir)
    elif args.model and args.name:
        tempdir = args.tempdir or os.path.join(
            os.path.dirname(os.path.abspath(args.model)), "_wsm_diagnose_temp")
        if not os.path.isdir(tempdir):
            os.makedirs(tempdir)
        extra = []
        for lib in args.load_library:
            extra += ["--load-library", lib]
        for path in args.load:
            extra += ["--load", path]
        msl = args.msl or ("yes" if extra else "auto")
        extra += ["--msl", msl]
        if args.msl_version:
            extra += ["--msl-version", args.msl_version]
        exe, sim = build(args.model, args.name, tempdir, extra)
    else:
        ap.error("give either --model and --name, or --tempdir")

    stem = os.path.splitext(os.path.basename(exe))[0]
    if args.stop_time is not None:
        sim = retime_sim(sim, args.stop_time, tempdir)
    counts, wall, run_info, runs = sample_until(backend, exe, sim, args.hz,
                                                args.seconds, args.min_samples,
                                                args.result)
    report(counts, wall, args.top, run_info, blockmap.load(tempdir, stem), runs,
           args.result)


if __name__ == "__main__":
    main()
