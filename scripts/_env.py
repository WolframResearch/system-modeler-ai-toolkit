"""
Shared Python-environment bootstrap for the System Modeler skill scripts.

Some scripts (plot_mat.py, check_sanity.py) need third-party packages
(DyMat, matplotlib, numpy, scipy) that are usually NOT present on the
interpreter an agent happens to invoke — and a bare `pip install` fails on
PEP 668 "externally-managed" interpreters (Homebrew, system Python, …).

This module provides a managed virtual environment so those scripts "just
work" without the caller having to think about it:

    from _env import reexec_under_managed_venv
    reexec_under_managed_venv(["DyMat", "matplotlib", "numpy"])

If the required modules are already importable, this is a no-op. Otherwise it
creates (once) a cached venv, installs the packages, and re-executes the
current script under that venv's interpreter with the same arguments.

The venv location can be overridden with $WSM_SKILLS_VENV. It defaults to a
per-user cache dir so it is shared across all the skills and survives between
sessions.
"""

import importlib
import os
import shutil
import subprocess
import sys
import time

# Map an importable module name -> the pip distribution that provides it,
# for the cases where they differ.
_PIP_NAME = {
    "DyMat": "DyMat",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "scipy": "scipy",
}

# Runtime dependencies that a module needs at import time but does not declare
# as a pip dependency. DyMat 0.7 does `import scipy.io` / `import numpy` at the
# top of its __init__ but only lists numpy in its metadata, so a bare
# `pip install DyMat` leaves it un-importable until scipy is also present.
_EXTRA_DEPS = {
    "DyMat": ["numpy", "scipy"],
}


def _expand(modules):
    """Add undeclared runtime dependencies, preserving order, de-duplicated."""
    out = []
    for m in modules:
        for dep in _EXTRA_DEPS.get(m, []):
            if dep not in out:
                out.append(dep)
        if m not in out:
            out.append(m)
    return out

# Guard env var: set inside the managed venv so a failed install can't loop.
_REEXEC_FLAG = "WSM_SKILLS_ENV_ACTIVE"

# Marker file written inside the venv once python + pip are fully set up. A
# venv directory without it is the leftover of an interrupted bootstrap (the
# classic symptom is "No module named pip") and is rebuilt — it's just a cache.
_READY_MARKER = ".wsm-skills-ready"


def _default_venv_dir():
    override = os.environ.get("WSM_SKILLS_VENV")
    if override:
        return os.path.abspath(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "wsm-skills", "venv")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "wsm-skills", "venv")


def venv_python(venv_dir):
    """Path to the python interpreter inside a venv (per OS)."""
    if sys.platform.startswith("win"):
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _missing(modules):
    """Return the subset of `modules` that cannot be imported here."""
    missing = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    return missing


def _pid_alive(pid):
    """True if ``pid`` is running, False if not, None if it can't be determined
    (e.g. a platform where signal 0 isn't supported)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    except (OSError, AttributeError):
        return None  # can't tell
    return True


def _acquire_lock(lock_path, log, timeout=1800, stale_after=1800):
    """Atomically create ``lock_path`` (O_CREAT|O_EXCL) so only one process
    bootstraps/installs at a time; others wait here until it is released.

    A lock is only stolen when the holder is clearly gone: its PID is dead, or
    (when liveness can't be determined) it is older than ``stale_after``. A holder
    that is still running is never stolen, however long its install takes — so a
    slow first-time ``pip install`` can't be killed out from under itself."""
    deadline = time.time() + timeout
    waiting = False
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, ("%d\n" % os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            pass
        try:
            holder = int((open(lock_path).read().strip() or "0"))
        except (OSError, ValueError):
            holder = 0
        alive = _pid_alive(holder)
        try:
            age = time.time() - os.path.getmtime(lock_path)
        except OSError:
            continue  # lock released between the two checks; retry right away
        if alive is False or (alive is None and age > stale_after):
            try:
                os.unlink(lock_path)
            except OSError:
                pass
            continue
        if time.time() > deadline:
            raise RuntimeError(
                "[wsm-skills] timed out waiting for venv lock %s — if no other "
                "install is running, delete it and retry" % lock_path)
        if not waiting:
            log("[wsm-skills] waiting for a concurrent bootstrap (lock: %s)" % lock_path)
            waiting = True
        time.sleep(0.5)


def ensure_managed_venv(modules, quiet=False):
    """
    Make sure a managed venv exists and contains `modules`.
    Returns the path to the venv's python interpreter.
    """
    modules = _expand(modules)
    venv_dir = _default_venv_dir()
    py = venv_python(venv_dir)
    ready = os.path.join(venv_dir, _READY_MARKER)
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr))

    # Is everything already importable in that venv?
    check = "import importlib,sys;" + "".join(
        "importlib.import_module(%r);" % m for m in modules
    )

    def _have():
        return subprocess.call([py, "-c", check],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    # Fast path (no lock): fully bootstrapped venv that already has everything.
    if os.path.isfile(ready) and os.path.isfile(py) and _have():
        return py

    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)
    lock = venv_dir + ".lock"
    _acquire_lock(lock, log)
    try:
        # Re-check under the lock: a concurrent process may have done the work.
        if os.path.isdir(venv_dir) and not os.path.isfile(ready):
            # Interrupted bootstrap — the venv is a disposable cache: rebuild it.
            log("[wsm-skills] removing incomplete venv at %s" % venv_dir)
            shutil.rmtree(venv_dir, ignore_errors=True)
        if not os.path.isfile(py):
            log("[wsm-skills] creating managed venv at %s" % venv_dir)
            subprocess.check_call([sys.executable, "-m", "venv", venv_dir], timeout=300)
            subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "-q", "pip"],
                                  timeout=600)
            with open(ready, "w") as f:
                f.write("ok\n")
        if not _have():
            pkgs = [_PIP_NAME.get(m, m) for m in modules]
            log("[wsm-skills] installing into managed venv: %s" % " ".join(pkgs))
            # bounded so a hung pip releases the lock (via finally) instead of
            # blocking every other process until its own lock timeout
            subprocess.check_call([py, "-m", "pip", "install", "-q", *pkgs], timeout=1800)
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass
    return py


def reexec_under_managed_venv(modules, quiet=False):
    """
    If `modules` are importable in the current interpreter, do nothing.
    Otherwise create/reuse the managed venv, install them, and re-exec the
    current process under the venv python with identical arguments.

    Call this at the very top of a script, before importing the heavy deps.

    Uses a child subprocess rather than os.exec* so behaviour is identical on
    Windows, macOS and Linux (os.exec* has no true exec on Windows and can
    return control to the shell before the child finishes).
    """
    modules = _expand(modules)
    if not _missing(modules):
        return  # current interpreter already has everything
    if os.environ.get(_REEXEC_FLAG):
        # We are already inside the managed venv and STILL can't import.
        # Don't loop — let the normal ImportError surface a clear message.
        return
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 in ("", "-c") or not os.path.isfile(os.path.abspath(argv0)):
        # Not launched as a script file (e.g. `python -c ...`): there is nothing
        # meaningful to re-exec, so don't try to run the bogus `-c` path. Use
        # reexec_module_under_managed_venv for `python -m` entry points.
        return
    py = ensure_managed_venv(modules, quiet=quiet)
    if os.path.abspath(py) == os.path.abspath(sys.executable):
        return  # we already are the managed interpreter
    env = dict(os.environ)
    env[_REEXEC_FLAG] = "1"
    if not quiet:
        print("[wsm-skills] re-running under managed venv: %s" % py, file=sys.stderr)
    completed = subprocess.run([py, os.path.abspath(sys.argv[0]), *sys.argv[1:]], env=env)
    sys.exit(completed.returncode)


def reexec_module_under_managed_venv(module, modules, package_root=None, quiet=False):
    """Like :func:`reexec_under_managed_venv`, but for a package module run with ``python -m``.

    Re-execs ``python -m <module>`` (not the script file) so the package's relative imports keep
    working. ``package_root`` is the directory that must be on ``sys.path`` for ``module`` to
    resolve (the package's parent); it is prepended to ``PYTHONPATH`` while the caller's cwd is
    preserved, so relative-path CLI arguments keep resolving the same way in the child.
    """
    modules = _expand(modules)
    if not _missing(modules):
        return
    if os.environ.get(_REEXEC_FLAG):
        return
    py = ensure_managed_venv(modules, quiet=quiet)
    if os.path.abspath(py) == os.path.abspath(sys.executable):
        return
    env = dict(os.environ)
    env[_REEXEC_FLAG] = "1"
    if package_root:
        prev = env.get("PYTHONPATH")
        env["PYTHONPATH"] = package_root + ((os.pathsep + prev) if prev else "")
    if not quiet:
        print("[wsm-skills] re-running under managed venv: %s" % py, file=sys.stderr)
    completed = subprocess.run([py, "-m", module, *sys.argv[1:]], env=env)
    sys.exit(completed.returncode)
