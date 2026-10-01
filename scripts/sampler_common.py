"""
Shared plumbing for the per-platform sampling backends of profile_sim.py:
starting the built simulation, timing the sampling window, and keeping the last
lines of the run's own output for the report.
"""

import os
import subprocess
import tempfile
import time


def launch(exe, sim, result=False):
    """Start the built simulation with its output captured. Returns (proc, log).

    With no result file asked for, the run computes the same trajectory but writes
    nothing: the profile then measures the model rather than the disk, and a long
    run does not leave hundreds of megabytes behind."""
    cmd = [exe]
    if sim:
        cmd += ["-f", sim]
    if result:
        cmd += ["-r", os.path.join(os.path.dirname(exe), "_profile_run.mat")]
    log = tempfile.TemporaryFile()
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log), log


def normalize(name):
    """Undo the code generator's `$`-escapes and drop the decoration underscore.
    Every backend applies it, so the report classifies and prints the same names
    on every platform."""
    out = (name.replace("$u", "_").replace("$_", ".")
               .replace("$B", "[").replace("$b", "]"))
    return out.lstrip("_").lstrip("$") or name


def tail_log(handle, encoding="utf-8", lines=6):
    try:
        handle.seek(0)
        text = handle.read().decode(encoding, "replace").strip().splitlines()
        handle.close()
        return [l.strip() for l in text[-lines:] if l.strip()]
    except Exception:
        return []


def wait_for_sampler(sampler, proc, started, seconds, on_target_exit=None):
    """Block until the external sampler finishes, watching the simulation so a run
    that ends before the budget is timed by its own length. Returns
    (wall_seconds, ended_early)."""
    died_at = None
    while sampler.poll() is None:
        if died_at is None and proc.poll() is not None:
            died_at = time.time()
            if on_target_exit:
                on_target_exit()
        time.sleep(0.05)
    if died_at is None and proc.poll() is not None:
        died_at = time.time()
    wall = (died_at - started) if died_at else min(time.time() - started, seconds)
    return wall, proc.poll() is not None


def stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait()
