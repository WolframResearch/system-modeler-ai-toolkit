#!/usr/bin/env python3
"""
Cross-platform launcher for WSMKernelX (Wolfram System Modeler command-line kernel).

This is the single place where all OS-specific knowledge lives:
  - where System Modeler is installed (macOS / Windows / Linux),
  - what the kernel binary is called and where it sits inside the install,
  - which Modelica Standard Library version to load and the paths to its files,
  - how to run the kernel with a working C/C++ compiler on each platform
    (direct on macOS/Linux; through the Visual Studio dev environment on Windows).

The validate / simulate / diagnose skills call this instead of hand-writing
.mos scripts and .bat files with hardcoded "C:\\Program Files\\..." paths.

Discovery order for the install root:
  1. --wsm-home argument
  2. $WSM_HOME / $SYSTEMMODELER_HOME environment variable
  3. platform default search globs (newest version wins)

Usage:
    python wsm_run.py --mode validate  --model path/to/M.mo --name M
    python wsm_run.py --mode simulate  --model path/to/M.mo --name Pkg.M
    python wsm_run.py --mode diagnose  --model path/to/M.mo --name M
    python wsm_run.py --mode info        # just print the discovered configuration
    python wsm_run.py --mode libraries   # list installed non-MSL libraries (--library NAME to resolve one)

Common options:
    --msl {auto,yes,no}     load MSL dependencies (auto = scan model for "Modelica.")
    --msl-version VER       force an MSL version, e.g. 4.1.0 (default: newest 4.x found)
    --load-library NAME     locate an installed non-MSL library by name and load it
                            before the model, repeatable (e.g. Hydraulic; see --mode libraries)
    --tempdir DIR           working dir (default: <model-dir>/_wsm_<mode>_temp)
    --wsm-home PATH         install root override
    --debug                 diagnose: also emit compiler per-stage dumps + exec stats
    --kernel-arg ARG        advanced raw kernel flag, repeatable (prefer --debug)
    --timeout SECONDS       kill the run after this long (default 180)
    --arch ARCH             Windows VS architecture (default amd64; or set $WSM_ARCH)
    --no-run                generate the .mos (and .bat on Windows) but do not run

On success the kernel writes "<mode>.out.json" into the temp dir; this script
prints the path to that file (and, for diagnose, leaves all +g build artifacts
in place for the report scripts).
"""

import argparse
import glob
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import time
from xml.sax.saxutils import escape as _xml_escape


# ----------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------

def _version_key(text):
    """Sortable key from a version-ish string; missing -> (0,)."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def _search_patterns():
    """The glob patterns searched for an install root, per platform (newest match
    wins). Returned regardless of whether anything matches, so a 'not found' error
    can show the user exactly where we looked."""
    system = platform.system()
    if system == "Darwin":
        return [
            "/Applications/SystemModeler*.app/Contents",
            "/Applications/Wolfram System Modeler*.app/Contents",
            "/Applications/*System*Modeler*.app/Contents",
        ]
    if system == "Windows":
        bases = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        seen, pats = set(), []
        for base in bases:  # ProgramFiles/ProgramW6432 are usually identical
            pat = os.path.join(base, "Wolfram Research", "System Modeler *")
            if pat not in seen:
                seen.add(pat)
                pats.append(pat)
        return pats
    # Linux and other Unix
    home = os.path.expanduser("~")
    return [
        "/usr/local/Wolfram/SystemModeler/*",
        "/usr/local/Wolfram/WolframSystemModeler/*",
        "/opt/Wolfram/SystemModeler/*",
        "/opt/Wolfram/WolframSystemModeler/*",
        os.path.join(home, "Wolfram", "SystemModeler", "*"),
    ]


def _candidate_roots():
    """Platform-specific list of possible install roots that actually exist."""
    roots = []
    for pat in _search_patterns():
        roots += glob.glob(pat)
    # de-duplicate, keep only directories
    seen, out = set(), []
    for r in roots:
        rp = os.path.realpath(r)
        if rp not in seen and os.path.isdir(rp):
            seen.add(rp)
            out.append(r)
    return out


def _kernel_in_root(root):
    """Return the kernel binary path inside `root`, or None."""
    for rel in ("MacOS/WSMKernelX", "bin/WSMKernelX.exe", "bin/WSMKernelX"):
        cand = os.path.join(root, *rel.split("/"))
        if os.path.isfile(cand):
            return cand
    return None


def _root_version(root):
    """Best-effort version string for an install root."""
    plist = os.path.join(root, "Info.plist")
    if os.path.isfile(plist):
        try:
            with open(plist, "rb") as fh:
                data = plistlib.load(fh)
            v = data.get("CFBundleShortVersionString") or data.get("CFBundleVersion")
            if v:
                return v
        except Exception:
            pass
    # fall back to a version number embedded in the path (e.g. ".../System Modeler 15.1")
    return os.path.basename(root.rstrip("/\\"))


def find_install(wsm_home=None):
    """
    Resolve the install root and kernel binary.
    Returns (root, kernel_path, version). Raises RuntimeError if not found.
    """
    explicit = wsm_home or os.environ.get("WSM_HOME") or os.environ.get("SYSTEMMODELER_HOME")
    candidates = []
    if explicit:
        explicit = os.path.expanduser(explicit)
        # accept either the install root or the .app bundle; normalise to a root with a kernel
        for r in (explicit, os.path.join(explicit, "Contents")):
            if _kernel_in_root(r):
                candidates.append(r)
                break
        if not candidates:
            raise RuntimeError(
                "WSM install override '%s' does not contain a WSMKernelX binary "
                "(looked for MacOS/WSMKernelX, bin/WSMKernelX[.exe])." % explicit)
    else:
        candidates = [r for r in _candidate_roots() if _kernel_in_root(r)]
        if not candidates:
            searched = "\n".join("  " + p for p in _search_patterns())
            raise RuntimeError(
                "Could not locate a Wolfram System Modeler installation on this "
                "%s machine.\nSearched these standard locations (none contained a "
                "WSMKernelX binary):\n%s\n\n"
                "If System Modeler is installed somewhere non-standard, ASK THE USER "
                "for the install root, then re-run with --wsm-home <path> (or set "
                "WSM_HOME). The root is the directory that contains the kernel, e.g.\n"
                "  macOS:   /Applications/SystemModeler.app/Contents  (MacOS/WSMKernelX)\n"
                "  Windows: C:\\Program Files\\Wolfram Research\\System Modeler 15.1  (bin\\WSMKernelX.exe)\n"
                "  Linux:   /usr/local/Wolfram/SystemModeler/15.1  (bin/WSMKernelX)"
                % (platform.system(), searched))
    # newest version wins
    candidates.sort(key=lambda r: _version_key(_root_version(r)))
    root = candidates[-1]
    return root, _kernel_in_root(root), _root_version(root)


def find_msl(root, version=None):
    """
    Locate MSL files under the install root.
    Returns a dict of the four loadFile targets, or None if no MSL found.
    `version` forces a specific "Modelica X.Y.Z" directory.
    """
    libdirs = glob.glob(os.path.join(root, "L", "Modelica *"))
    if not libdirs:
        return None
    if version:
        match = [d for d in libdirs if os.path.basename(d) == "Modelica " + version]
        if not match:
            raise RuntimeError(
                "MSL version %s not found under %s (available: %s)"
                % (version, os.path.join(root, "L"),
                   ", ".join(sorted(os.path.basename(d).replace("Modelica ", "") for d in libdirs))))
        modelica_dir = match[0]
    else:
        # prefer newest 4.x, else newest overall
        v4 = [d for d in libdirs if os.path.basename(d).startswith("Modelica 4")]
        pool = v4 if v4 else libdirs
        pool.sort(key=lambda d: _version_key(os.path.basename(d)))
        modelica_dir = pool[-1]
    files = {
        "complex": os.path.join(modelica_dir, "Complex.mo"),
        "services": os.path.join(modelica_dir, "ModelicaServices", "package.mo"),
        "wsmservices": os.path.join(root, "SystemFiles", "Resources", "msl-support", "WSMServices.mo"),
        "modelica": os.path.join(modelica_dir, "Modelica", "package.mo"),
    }
    missing = [k for k, p in files.items() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(
            "MSL directory %s is missing expected files: %s"
            % (modelica_dir, ", ".join(missing)))
    files["version"] = os.path.basename(modelica_dir).replace("Modelica ", "")
    return files


def find_vsdevcmd(override=None):
    """Windows only: locate VsDevCmd.bat. Returns path or None."""
    explicit = override or os.environ.get("WSM_VSDEVCMD")
    if explicit and os.path.isfile(explicit):
        return explicit
    bases = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    hits = []
    for base in bases:
        hits += glob.glob(os.path.join(base, "Microsoft Visual Studio", "*", "*",
                                       "Common7", "Tools", "VsDevCmd.bat"))
    hits.sort(key=_version_key)
    return hits[-1] if hits else None


# ----------------------------------------------------------------------------
# Installed-library discovery
# ----------------------------------------------------------------------------
# MSL is handled by --msl / find_msl above. This section finds *every other*
# library the machine has: bundled ones under <root>/L, libraries the user
# installed from the Library Store (per-user LibraryArchives), and any custom
# library folders configured in Model Center. The general logic here mirrors the
# Hydraulic-specific create-hydraulic-model/Hydraulic/locate.py (kept separate so
# that skill still works when symlinked without this scripts/ folder).

def _library_config_dirs():
    """Per-user SystemModeler config dirs to search, per platform (existing or not).
    Same locations as Hydraulic/locate.py._config_dirs."""
    system = platform.system()
    home = os.path.expanduser("~")
    if system == "Windows":
        bases, seen = [], set()
        for b in (os.environ.get("APPDATA"), os.path.join(home, "AppData", "Roaming")):
            if b and b not in seen:
                seen.add(b)
                bases.append(b)
        return [os.path.join(b, "SystemModeler") for b in bases]
    if system == "Darwin":
        return [
            os.path.join(home, "Library", "Application Support", "SystemModeler"),
            os.path.join(home, "Library", "Application Support", "Wolfram", "SystemModeler"),
        ]
    # Linux and other Unix
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return [
        os.path.join(home, ".systemmodeler"),
        os.path.join(home, ".SystemModeler"),
        os.path.join(xdg, "SystemModeler"),
        os.path.join(home, ".Wolfram", "SystemModeler"),
    ]


def _settings_files():
    """Model Center settings file(s) that may hold custom library paths, newest first.
    Qt QSettings storage differs per platform; on Windows the store is the registry,
    handled separately in settings_custom_paths()."""
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Darwin":
        pats = [
            os.path.join(home, "Library", "Preferences", "com.wolfram.SystemModeler*.plist"),
            os.path.join(home, "Library", "Preferences", "com.wolfram.SystemModeler.plist"),
        ]
    elif system == "Windows":
        return []  # registry — see settings_custom_paths()
    else:
        pats = [os.path.join(home, ".config", "Wolfram", "SystemModeler*.conf")]
    hits = []
    for pat in pats:
        hits += glob.glob(pat)
    # newest version-suffixed file wins (e.g. SystemModeler150103.conf)
    hits.sort(key=lambda p: _version_key(os.path.basename(p)))
    return list(reversed(hits))


def _clean_setting_list(raw):
    """Split a Qt QSettings string-list value into paths. `@Invalid()` means unset."""
    if not raw or raw.strip() in ("@Invalid()", ""):
        return []
    out = []
    for part in raw.split(","):
        p = part.strip().strip('"')
        if p:
            out.append(os.path.expanduser(p))
    return out


def settings_custom_paths():
    """Extra library search directories the user added in Model Center
    (LibrarySetup/libraryCustomPaths). Best-effort: returns [] on any read failure."""
    system = platform.system()
    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Wolfram\SystemModeler\LibrarySetup")
            try:
                raw, _ = winreg.QueryValueEx(key, "libraryCustomPaths")
            finally:
                winreg.CloseKey(key)
            return _clean_setting_list(raw if isinstance(raw, str) else "")
        except Exception:
            return []
    for path in _settings_files():
        try:
            if path.endswith(".plist"):
                with open(path, "rb") as fh:
                    data = plistlib.load(fh)
                # QSettings nests groups as slash-joined keys or nested dicts
                val = data.get("LibrarySetup", {})
                raw = val.get("libraryCustomPaths") if isinstance(val, dict) \
                    else data.get("LibrarySetup/libraryCustomPaths")
                if isinstance(raw, (list, tuple)):
                    return [os.path.expanduser(str(p)) for p in raw if p]
                paths = _clean_setting_list(raw if isinstance(raw, str) else "")
            else:
                import configparser
                cp = configparser.ConfigParser(interpolation=None, strict=False)
                cp.read(path, encoding="utf-8")
                if not cp.has_option("LibrarySetup", "libraryCustomPaths"):
                    continue
                paths = _clean_setting_list(cp.get("LibrarySetup", "libraryCustomPaths"))
            if paths:
                return paths
        except Exception:
            continue
    return []


def _split_lib_dir(basename):
    """Split a library folder name into (name, version).
    `"Hydraulic 2.1"` -> ("Hydraulic", "2.1"); `"Modelica 4.1.0"` -> ("Modelica", "4.1.0");
    a folder with no trailing version -> (basename, "")."""
    parts = basename.rsplit(" ", 1)
    if len(parts) == 2 and re.search(r"\d", parts[1]):
        return parts[0], parts[1]
    return basename, ""


def _library_globs(root):
    """(glob_pattern, source) pairs covering every place a library can live.
    A pattern's parent-of-parent is the '<Name> <ver>' folder we parse."""
    globs = []
    if root:
        # bundled: <root>/L/<Name ver>/package.*
        globs.append((os.path.join(root, "L", "*"), "bundled"))
    for cfg in _library_config_dirs():
        # installed archives: <cfg>/LibraryArchives/<uuid>/<Name ver>/package.*
        globs.append((os.path.join(cfg, "LibraryArchives", "*", "*"), "installed"))
    for cp in settings_custom_paths():
        # Model Center custom folder: <path>/<Name ver>/package.*
        globs.append((os.path.join(cp, "*"), "custom"))
    return globs


def discover_libraries(root):
    """Every library found on this machine (excluding MSL, which --msl handles).

    Returns a list of dicts sorted by (name, version):
        {"name", "version", "source": bundled|installed|custom, "package": <abs path>}
    De-duplicated by the real path of the package file, since the same library can
    be reached through more than one search location (or a symlink). A library
    folder holds a plain `package.mo` or an encrypted `package.moe`, never both."""
    libs = []
    seen = set()   # package-file realpath
    for base_glob, source in _library_globs(root):
        for ext in ("mo", "moe"):
            for pkg in glob.glob(base_glob + os.sep + "package." + ext):
                if not os.path.isfile(pkg):
                    continue
                rp = os.path.realpath(pkg)
                if rp in seen:
                    continue
                name, version = _split_lib_dir(os.path.basename(os.path.dirname(pkg)))
                if name == "Modelica":
                    continue  # MSL: loaded via --msl / find_msl, not here
                seen.add(rp)
                libs.append({
                    "name": name, "version": version, "source": source,
                    "package": os.path.abspath(pkg),
                })
    libs.sort(key=lambda r: (r["name"].lower(), _version_key(r["version"])))
    return libs


def _env_library_override(name):
    """Explicit override for one library: $WSM_LIBRARY_<NAME> (non-alnum -> _)."""
    return os.environ.get("WSM_LIBRARY_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper())


def resolve_library(root, name, version=None, override=None):
    """Resolve one library name to its package file, or None if not found.

    Order: explicit `override` (file or dir), then $WSM_LIBRARY_<NAME>, then the
    discovered set (exact version if given, else newest). An override dir is scanned
    for package.moe/package.mo."""
    explicit = override or _env_library_override(name)
    if explicit:
        explicit = os.path.expanduser(explicit)
        if os.path.isdir(explicit):
            for ext in ("moe", "mo"):
                cand = os.path.join(explicit, "package." + ext)
                if os.path.isfile(cand):
                    return os.path.abspath(cand)
            return None
        return os.path.abspath(explicit) if os.path.isfile(explicit) else None

    matches = [l for l in discover_libraries(root) if l["name"] == name]
    if not matches:  # case-insensitive fallback
        matches = [l for l in discover_libraries(root) if l["name"].lower() == name.lower()]
    if version:
        matches = [l for l in matches if l["version"] == version]
    if not matches:
        return None
    src_rank = {"installed": 2, "custom": 1, "bundled": 0}
    matches.sort(key=lambda l: (_version_key(l["version"]), src_rank.get(l["source"], 0)))
    return matches[-1]["package"]


def _library_search_locations(root):
    """Human-readable list of where we looked (for 'not found' messages)."""
    return [g[0] + os.sep + "package.{mo,moe}" for g in _library_globs(root)]


# ----------------------------------------------------------------------------
# Script generation + execution
# ----------------------------------------------------------------------------

def _fwd(path):
    """Modelica loadFile wants forward slashes on every platform. The result is
    interpolated into a Modelica string literal, so a double quote in the path
    (legal on POSIX) is escaped; backslashes are already gone (turned into /)."""
    return os.path.abspath(path).replace("\\", "/").replace('"', '\\"')


def model_uses_msl(model_path):
    """Heuristic: does the model reference the Modelica Standard Library?"""
    try:
        with open(model_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return True  # safest default: load MSL
    return re.search(r"\bModelica\s*\.", text) is not None


def warn_msl_dialect(paths, msl_version):
    """
    Warn when a model uses MSL-3.2 names while a 4.x MSL is loaded. These are the
    classic rename traps that flatten with confusing "not found" errors:
      * Modelica.SIunits.*   -> Modelica.Units.SI.*   (MSL 4.0)
      * <Source>(freqHz=...) -> <Source>(f=...)       (MSL 4.0)
    Heuristic and non-fatal; just prints a hint to stderr. `paths` is one or more
    .mo files (a whole directory-form library is scanned at once, deduped).
    """
    if not msl_version or not str(msl_version).startswith("4"):
        return
    text = ""
    for p in ([paths] if isinstance(paths, str) else paths):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                text += fh.read() + "\n"
        except OSError:
            continue
    hits = []
    if re.search(r"\bModelica\s*\.\s*SIunits\b", text):
        hits.append("`Modelica.SIunits.*` -> use `Modelica.Units.SI.*`")
    if re.search(r"\bfreqHz\b", text):
        hits.append("`freqHz=` -> use `f=` (e.g. SineVoltage, sources)")
    for h in hits:
        print("WARNING: MSL %s is loaded but the model uses an MSL-3.2 name: %s"
              % (msl_version, h), file=sys.stderr)


def _library_root_for(mo_file):
    """If mo_file sits inside a directory-form library (its folder, or an ancestor,
    holds a package.mo), return that library's top-level package.mo. Otherwise None.

    A directory-form library stores one class per file with a `package.mo` at each
    level; loading a single class file alone fails because its `within Lib;` clause
    needs the whole package present. The kernel loads the entire tree when handed
    the top package.mo (it follows package.order), so that is what we resolve to."""
    d = os.path.dirname(os.path.abspath(mo_file))
    if not os.path.isfile(os.path.join(d, "package.mo")):
        return None
    root = d
    while True:
        parent = os.path.dirname(root)
        if parent and parent != root and os.path.isfile(os.path.join(parent, "package.mo")):
            root = parent
        else:
            break
    return os.path.join(root, "package.mo")


def _mo_tree(root_dir):
    """Every .mo file under root_dir (for MSL auto-detection / dialect scanning)."""
    out = []
    for dirpath, _dirs, files in os.walk(root_dir):
        for f in files:
            if f.endswith(".mo"):
                out.append(os.path.join(dirpath, f))
    return out


def resolve_model_target(model_arg):
    """Map the --model argument to what the kernel should loadFile.

    Returns (load_path, scan_paths, temp_base, kind) or None if the path does not
    exist / a directory has no package.mo:
      * load_path  : the .mo to loadFile (a directory-form library's top package.mo,
                     or a single-file model as given).
      * scan_paths : .mo files to scan for MSL auto-detection / dialect warnings.
      * temp_base  : directory to place the _wsm_<mode>_temp dir in.
      * kind       : "package" or "single" (for user messaging).

    A --model that points at a directory, at a package.mo, or at a class file that
    lives inside a package is resolved up to that package's root package.mo so the
    whole library is loaded; a plain standalone .mo file is loaded as given."""
    ap = os.path.abspath(model_arg)
    if os.path.isdir(ap):
        pkg = os.path.join(ap, "package.mo")
        if not os.path.isfile(pkg):
            return None
        root = _library_root_for(pkg) or pkg
        root_dir = os.path.dirname(root)
        return (root, _mo_tree(root_dir), root_dir, "package")
    if os.path.isfile(ap):
        root = _library_root_for(ap)
        if root:
            return (root, _mo_tree(os.path.dirname(root)), os.path.dirname(ap), "package")
        return (ap, [ap], os.path.dirname(ap), "single")
    return None


# The kernel prints this line when an uncaught exception aborts it before the error
# is reported. Its presence means a *real* error escaped the test function's catch --
# NOT that the failure is an unknowable compiler crash. The real message is recovered
# by re-running the same call without +g (rerun_without_g).
FATAL_EXCEPTION_TOKEN = "Fatal error: exception"

MODE_CALL = {"validate": "instantiateModelTest", "simulate": "simTest", "diagnose": "simTest"}

# staged entry points for diagnostics (override the default with --call)
CALL_ALIAS = {
    "instantiate": "instantiateModelTest",
    "build": "buildModelTest",
    "sim": "simTest",
}


# A Modelica class name: dotted identifiers, each plain (`Pkg.Model`) or quoted
# (`'my model'`). The name is interpolated verbatim into the generated .mos, so
# reject anything else to keep a stray value from injecting script.
_IDENT_SEG = r"(?:[A-Za-z_]\w*|'[^'\n]*')"
_MODEL_NAME_RE = re.compile(r"^\.?" + _IDENT_SEG + r"(?:\." + _IDENT_SEG + r")*$")


def _is_model_name(name):
    return bool(name) and _MODEL_NAME_RE.match(name) is not None


def build_mos(mode, model_path, name, msl_files, call=None, extra_loads=None):
    lines = []
    if mode in ("simulate", "diagnose"):
        lines.append('mce_setOption("allowConditionedSolvability", true);')
    if mode == "diagnose":
        lines.append('mce_setOption("logSelectedStates", true);')
        lines.append('mce_setOption("logindexreduction", true);')
    if msl_files:
        lines.append('loadFile("%s");' % _fwd(msl_files["complex"]))
        lines.append('loadFile("%s");' % _fwd(msl_files["services"]))
        lines.append('loadFile("%s");' % _fwd(msl_files["wsmservices"]))
        lines.append('loadFile("%s");' % _fwd(msl_files["modelica"]))
    for extra in (extra_loads or []):
        lines.append('loadFile("%s");' % _fwd(extra))
    lines.append('loadFile("%s");' % _fwd(model_path))
    test_call = CALL_ALIAS[call] if call else MODE_CALL[mode]
    lines.append("%s(%s);" % (test_call, name))
    # The *Test calls print/persist their own errors when exception catching is on (not
    # under +g; see kernel-flags note in main()); the opaque-abort case is recovered by
    # rerun_without_g. So no test-harness helpers are emitted here.
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Parameter override / sweep (reuse one compiled executable, no recompile)
# ----------------------------------------------------------------------------
# A built model produces an executable plus a `.sim` XML init file in which every
# tunable parameter appears as a <variable name="..." equationBound="value" .../>
# line. To re-run with new parameter values we edit that file and run the exe with
# `-f <sim> -r <result.mat>` — no recompilation. This is the big time saver for
# parameter studies (resonance/cutoff/etc.).

_VAR_NAME_RE = re.compile(r'name="([^"]+)"')
_VAR_INITTYPE_RE = re.compile(r'initType="([^"]+)"')
# ' value="..."' — the leading space avoids matching defaultValue/absoluteValue.
_VAR_VALUE_RE = re.compile(r'\svalue="[^"]*"')


def classify_params(sim_text, names):
    """
    Split requested parameter names by whether the simulation runtime will honor
    a `value=` override in the .sim. The runtime only applies `value` when
    initType == "exact"; calculated/approx/etc. are ignored,
    and constant-folded (structural) parameters are absent from the .sim entirely.
      overridable  -> present and initType="exact": edit in place, NO rebuild
      needs_rebuild-> present but not exact (value would be ignored)
      missing      -> not in the .sim (structural / constant-folded / typo)
    Returns (overridable, needs_rebuild, missing), preserving request order.
    """
    inittypes = {}
    for line in sim_text.splitlines():
        if line.lstrip().startswith("<variable "):
            m = _VAR_NAME_RE.search(line)
            if m and m.group(1) in names:
                it = _VAR_INITTYPE_RE.search(line)
                inittypes[m.group(1)] = it.group(1) if it else ""
    overridable, needs_rebuild, missing = [], [], []
    for n in names:
        if n not in inittypes:
            missing.append(n)
        elif inittypes[n] == "exact":
            overridable.append(n)
        else:
            needs_rebuild.append(n)
    return overridable, needs_rebuild, missing


def parse_assignments(spec):
    """'a=1,b=2.5e-6' -> {'a':'1','b':'2.5e-6'} (order preserved)."""
    out = {}
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError("expected name=value, got %r" % part)
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def apply_overrides_to_sim(sim_text, overrides):
    """Return (new_text, set_of_names_changed) with the `value=` attribute set.
    The runtime reads `value` (not `equationBound`) as the parameter/start value
    when initType="exact"."""
    changed = set()
    out_lines = []
    for line in sim_text.splitlines(keepends=True):
        if line.lstrip().startswith("<variable "):
            m = _VAR_NAME_RE.search(line)
            if m and m.group(1) in overrides:
                # Escape for an XML double-quoted attribute so a value containing
                # " & < > can't produce malformed .sim XML. A function replacement
                # keeps re.sub from interpreting backslashes/\g in the value.
                repl = ' value="%s"' % _xml_escape(overrides[m.group(1)], {'"': "&quot;"})
                if _VAR_VALUE_RE.search(line):
                    line = _VAR_VALUE_RE.sub(lambda _m: repl, line, count=1)
                else:  # inject value right after name="..."
                    line = line.replace(m.group(0), m.group(0) + repl, 1)
                changed.add(m.group(1))
        out_lines.append(line)
    return "".join(out_lines), changed


# Slack subtracted from a recorded run-start time before mtime comparisons, so a
# coarse filesystem timestamp (e.g. FAT's 2 s granularity) cannot make an artifact
# the current run just built look stale.
_MTIME_SLACK = 2.0


def _fresh(path, since):
    """True when `path` exists and was (re)written by the current run (mtime >=
    since). Guards a reused --tempdir against stale artifacts from earlier runs."""
    try:
        return os.path.getmtime(path) >= since
    except OSError:
        return False


def _newest(tempdir, suffix, newer_than=None):
    hits = [os.path.join(tempdir, f) for f in os.listdir(tempdir) if f.endswith(suffix)]
    if newer_than is not None:
        hits = [p for p in hits if _fresh(p, newer_than)]
    hits.sort(key=lambda p: os.path.getmtime(p))
    return hits[-1] if hits else None


def _find_built_exe(tempdir, newer_than=None):
    """Locate the executable produced by buildModelTest.

    The toolchain names it ``*.exe`` on every platform, so that is the primary
    match. As a safety net on Unix (where a future/non-standard build might emit an
    extension-less binary) we also accept the newest executable, extension-less
    regular file. `newer_than` restricts the search to artifacts of the current run.
    Returns the path, or None if nothing runnable was produced."""
    exe = _newest(tempdir, ".exe", newer_than)
    if exe:
        return exe
    if platform.system() != "Windows":
        cands = []
        for f in os.listdir(tempdir):
            p = os.path.join(tempdir, f)
            if os.path.isfile(p) and not os.path.splitext(f)[1] and os.access(p, os.X_OK):
                if newer_than is not None and not _fresh(p, newer_than):
                    continue
                cands.append(p)
        cands.sort(key=os.path.getmtime)
        if cands:
            return cands[-1]
    return None


def _safe_label(s):
    return re.sub(r'[^A-Za-z0-9._+-]', "_", s)


# Lines that usually carry the *actual* model/kernel diagnostic. Used to pull the
# real message out of a noisy log when the run failed (see surface_kernel_error).
_DIAGNOSTIC_RE = re.compile(
    r"""(?ix)              # case-insensitive, verbose
    \berror\b | \bwarning\b | \bassert(?:ion)?\b |
    \bmust\ be\b | out\ of\ bounds | not\ assigned | cannot\ be\ |
    \bsingular\b | underdetermin | overdetermin | too\ (?:few|many) |
    division\ by\ zero | \bfail(?:ed|ure)?\b | no\ such\ file |
    could\ not | unable\ to | index\ reduction | not\ found
    """
)

# Simulation-runtime failure markers. A model can build cleanly and still fail at
# initialization / integration (e.g. a violated assert), in which case simTest returns
# success with a .mat but the real failure only shows in the _res.log severity tags.
# These let the launcher flag such a run as failed so the message is surfaced.
_SIM_ERROR_RE = re.compile(
    r"(?i)\[\s*error\s*;|Error in initialization|Integration failed|"
    r"Simulation (?:failed|aborted)|nonlinear solver failed")


def grep_diagnostic_lines(text):
    """Return the readable diagnostic lines from kernel output (deduped, in order).
    The *Test functions print these directly ("instantiateModelTest Error: ...",
    runtime "[error ;ASSERT ...] ..."); this pulls them out of an otherwise noisy log."""
    seen, hits = set(), []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("[execstat]") or FATAL_EXCEPTION_TOKEN in s:
            continue
        if _DIAGNOSTIC_RE.search(s) and s not in seen:
            seen.add(s)
            hits.append(s)
    return hits


def errors_from_out_json(out_json):
    """Pull human-readable error/warning messages out of a <mode>.out.json the test
    functions write. The file is a JSON array; messages live under [i].messages."""
    try:
        with open(out_json, "r", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    msgs = []
    for entry in (data if isinstance(data, list) else [data]):
        if not isinstance(entry, dict):
            continue
        m = entry.get("messages") or {}
        for kind in ("internal_errors", "errors", "warnings"):
            for item in (m.get(kind) or []):
                if isinstance(item, dict) and item.get("message"):
                    loc = item.get("location") or item.get("file") or ""
                    msgs.append(("%s: %s" % (loc, item["message"])).strip(": "))
    return msgs


def surface_kernel_error(combined_output, tempdir, recover=None):
    """When a run fails, surface the *real* diagnostic prominently (to the tail of a
    redirected log) instead of leaving only the opaque "Fatal error: exception ...(_)".

    Strategy, in order: (1) grep the readable error lines the test functions already
    print; (2) read messages from any <mode>.out.json in the temp dir; (3) if the
    kernel aborted opaquely and produced nothing readable, invoke `recover` (a
    zero-arg callable that re-runs the same call with +g stripped, so exception
    catching is on, and returns the recovered messages). Always prints a short note
    so a normal model error is not mistaken for a compiler crash."""
    text = combined_output or ""
    fatal = FATAL_EXCEPTION_TOKEN in text
    hits = grep_diagnostic_lines(text)

    json_msgs = []
    for f in sorted(os.listdir(tempdir)) if os.path.isdir(tempdir) else []:
        if f.endswith(".out.json"):
            json_msgs += errors_from_out_json(os.path.join(tempdir, f))

    recovered = []
    if fatal and not hits and not json_msgs and recover is not None:
        print("\n[wsm_run] kernel aborted opaquely under +g; re-running the same call "
              "without +g to recover the real error...", file=sys.stderr)
        try:
            recovered = recover() or []
        except Exception as e:  # recovery is best-effort; never mask the original
            print("[wsm_run] recovery pass failed: %s" % e, file=sys.stderr)

    if not (fatal or hits or json_msgs or recovered):
        return  # genuinely nothing to surface

    print("\n=== actual kernel diagnostic ===", file=sys.stderr)
    if fatal:
        print("The kernel hit an uncaught exception ('Fatal error: exception ...(_)') "
              "and aborted before reporting it. This is a NORMAL error (assertion / "
              "parameter / data-file / type / lookup), NOT necessarily a compiler bug. "
              "The real message is below.", file=sys.stderr)
    for label, items in (("recovered (re-run without +g)", recovered),
                         ("from out.json", json_msgs),
                         ("from the run output (last 40)", hits[-40:])):
        if items:
            print("\n-- %s --" % label, file=sys.stderr)
            for it in items:
                print("  %s" % it, file=sys.stderr)
            break  # the first non-empty source is the most authoritative
    if fatal and not (recovered or json_msgs or hits):
        print("  (no readable error surfaced even after re-running with exception "
              "catching on -> this is likely a genuine compiler/internal crash; re-run "
              "with --debug and report it to Wolfram with the model)", file=sys.stderr)
    print("=== end kernel diagnostic ===", file=sys.stderr)


def rerun_without_g(kernel, args, msl_files, parent_tempdir, kernel_flags,
                    effective_call, arch, vsdevcmd):
    """Recover the real error after an opaque "+g" abort by re-running the SAME call
    with the +g flag stripped. Without +g the kernel catches exceptions, so the
    *Test function reports the error -- wherever it occurs (flatten, translate, or
    simulation) -- instead of aborting on the uncaught-exception line. A flatten error
    still aborts before the C++ build, so this stays cheap for the common case; a
    build/sim error pays one rebuild, which is unavoidable to reach the stage that
    failed.

    Returns the recovered human-readable messages (from the re-run's <mode>.out.json,
    falling back to the readable lines it printed), or [] if nothing was recovered."""
    rec_dir = os.path.join(parent_tempdir, "_recover_no_g")
    os.makedirs(rec_dir, exist_ok=True)
    mos_name = "recover.mos"
    with open(os.path.join(rec_dir, mos_name), "w", encoding="utf-8") as fh:
        fh.write(build_mos(args.mode, args.model, args.name, msl_files,
                           effective_call, extra_loads=args.extra_loads))
    flags = [f for f in kernel_flags if f != "+g"]  # the one flag that hides the error
    try:
        proc = run_kernel(kernel, rec_dir, mos_name, flags, args.mode,
                          args.timeout, arch, vsdevcmd, False)
    except (subprocess.TimeoutExpired, RuntimeError):
        return []
    msgs = []
    for f in sorted(os.listdir(rec_dir)):
        if f.endswith(".out.json"):
            msgs += errors_from_out_json(os.path.join(rec_dir, f))
    if not msgs and proc is not None:
        # No structured error list -> fall back to the readable lines the kernel printed
        # now that exception catching is on (e.g. a runtime "[error ;ASSERT ...]").
        msgs = grep_diagnostic_lines((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return msgs


def run_mat_summary(mat_path, variables):
    """Print a compact summary of `variables` from a .mat via mat_summary.py
    (which self-provisions DyMat in a managed venv)."""
    if not mat_path:
        print("(--report: no .mat produced)", file=sys.stderr)
        return
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mat_summary.py")
    if not os.path.isfile(script):
        print("(--report: mat_summary.py not found)", file=sys.stderr)
        return
    subprocess.run([sys.executable, script, mat_path] + list(variables))


def quiet_outcome(out_json, proc, tempdir, since=None):
    """A single terse line: build/flatten status + integration time + result file.
    `since` restricts the reported .mat to one produced by the current run."""
    status = ""
    if out_json and os.path.isfile(out_json):
        try:
            with open(out_json, encoding="utf-8") as fh:
                st = json.load(fh)[0].get("status", {})
            # only the pass/fail stages; skip the (often empty) message arrays
            status = " ".join("%s=%s" % (k, st[k]) for k in ("flatten", "build", "result")
                              if k in st)
        except Exception:
            pass
    out = (proc.stdout or "") if proc else ""
    m = re.search(r"Integration took ([\d.]+) seconds", out)
    extra = (" int=%ss" % m.group(1)) if m else ""
    mat = _newest(tempdir, ".mat", since)
    matpart = (" -> %s" % os.path.basename(mat)) if mat else ""
    return (status or ("rc=%d" % (proc.returncode if proc else -1))) + extra + matpart


def run_param_studies(exe, base_sim, tempdir, runs, timeout):
    """
    runs: list of (label, {param: value}). For each, write a patched .sim and run
    the exe to its own .mat. Returns list of dicts with label/result/ok/missing.
    """
    with open(base_sim, "r", encoding="utf-8", errors="replace") as fh:
        base_text = fh.read()
    exe_abs = os.path.abspath(exe)
    results = []
    for i, (label, overrides) in enumerate(runs):
        text, changed = apply_overrides_to_sim(base_text, overrides)
        missing = [k for k in overrides if k not in changed]
        # index-prefix the filename so two sweep values that sanitize to the same
        # label (e.g. "1/2" and "1_2") don't overwrite each other's .sim/.mat
        safe = "%02d_%s" % (i, _safe_label(label))
        sim_name = "run_%s.sim" % safe
        mat_name = "run_%s.mat" % safe
        mat_path = os.path.join(tempdir, mat_name)
        with open(os.path.join(tempdir, sim_name), "w", encoding="utf-8") as fh:
            fh.write(text)
        # never report a leftover .mat from a previous run as this run's result
        if os.path.isfile(mat_path):
            os.remove(mat_path)
        # Running the executable needs no compiler -> plain subprocess on every OS.
        proc = subprocess.run([exe_abs, "-f", sim_name, "-r", mat_name],
                              cwd=tempdir, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        results.append({
            "label": label,
            "overrides": overrides,
            "result": mat_path if os.path.isfile(mat_path) else None,
            "returncode": proc.returncode,
            "missing_params": missing,
            "stderr_tail": (proc.stderr or "")[-400:],
        })
    return results


def _run_tree(cmd, cwd, timeout):
    """Like subprocess.run(capture_output=True, timeout=...), but on Windows a
    timeout kills the whole process tree -- killing just cmd.exe would orphan
    the kernel/compiler it spawned, which keeps running (and holding files)."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.kill()
        proc.wait()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_kernel(kernel, tempdir, mos_name, kernel_flags, mode, timeout, arch,
               vsdevcmd, no_run):
    """Run the kernel in tempdir. On Windows compile modes, go through VsDevCmd."""
    is_windows = platform.system() == "Windows"
    needs_compiler = mode in ("simulate", "diagnose")

    if is_windows and needs_compiler:
        if not vsdevcmd:
            raise RuntimeError(
                "A C++ compiler environment is required for '%s' on Windows but "
                "VsDevCmd.bat was not found. Install Visual Studio Build Tools, or "
                "set WSM_VSDEVCMD to its VsDevCmd.bat." % mode)
        flag_str = (" ".join(kernel_flags) + " ") if kernel_flags else ""
        # Keep the code generator's target arch in step with the arch we pass the
        # compiler via -arch below; a mismatch makes the link step fail.
        codegen_arch = "x86" if arch.lower() in ("x86", "win32") else "x86_64"
        # cmd.exe reads .bat files in the OEM code page, so write it in that codec
        # rather than UTF-8: a non-ASCII kernel/VsDevCmd install path then matches
        # what cmd reads (and an unrepresentable char fails loudly instead of being
        # silently garbled). The working dir is still set via cwd=, not a `cd` line.
        bat = os.path.join(tempdir, "run.bat")
        with open(bat, "w", encoding="oem") as fh:
            fh.write("@echo off\n")
            fh.write('call "%s" -arch=%s >nul 2>&1\n' % (vsdevcmd, arch))
            fh.write("if errorlevel 1 (\n")
            fh.write("    echo ERROR: compiler environment failed: VsDevCmd.bat "
                     "-arch=%s exited with errorlevel %%errorlevel%% 1>&2\n" % arch)
            fh.write("    exit /b 97\n")
            fh.write(")\n")
            fh.write('set "WSM_DEFAULT_COMPILER_ARCH=%s"\n' % codegen_arch)
            fh.write('"%s" %s%s\n' % (kernel, flag_str, mos_name))
        if no_run:
            return None
        proc = _run_tree(["cmd", "/c", bat], tempdir, timeout)
        if proc.returncode == 97:
            raise RuntimeError(
                "compiler environment failed: '%s' -arch=%s exited with an error. "
                "Check the Visual Studio Build Tools install, or point --vsdevcmd/"
                "$WSM_VSDEVCMD at a working VsDevCmd.bat." % (vsdevcmd, arch))
    else:
        if no_run:
            return None
        cmd = [kernel] + kernel_flags + [mos_name]
        proc = subprocess.run(cmd, cwd=tempdir, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    return proc


def run_with_param_studies(args, kernel, tempdir, msl_files, version):
    """Build the model once, then re-run the executable for each override/sweep
    parameter set without recompiling. Structural (non-tunable) parameters are
    detected from the .sim and reported, since they would need a rebuild."""
    # 1) compile once with buildModelTest (build, don't simulate)
    mos_name = "build.mos"
    mos_path = os.path.join(tempdir, mos_name)
    for extra in args.extra_loads:
        if not os.path.isfile(extra):
            print("ERROR: --load file not found: %s" % extra, file=sys.stderr)
            return 2
    with open(mos_path, "w", encoding="utf-8") as fh:
        fh.write(build_mos("simulate", args.model, args.name, msl_files,
                           "build", args.extra_loads))
    vsdevcmd = find_vsdevcmd(args.vsdevcmd) if platform.system() == "Windows" else None
    run_start = time.time() - _MTIME_SLACK
    try:
        proc = run_kernel(kernel, tempdir, mos_name, args.kernel_arg, "simulate",
                          args.timeout, args.arch, vsdevcmd, args.no_run)
    except subprocess.TimeoutExpired:
        print("ERROR: build timed out after %ds" % args.timeout, file=sys.stderr)
        return 3
    except RuntimeError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    if proc is None:  # --no-run: script(s) generated, nothing executed
        print("Generated %s (not run; --no-run); skipped the override/sweep runs."
              % mos_path)
        return 0

    # Only trust artifacts THIS run (re)built: a reused tempdir may still hold a
    # previous model's executable/.sim, and running those after a failed build
    # would fabricate results.
    exe = _find_built_exe(tempdir, newer_than=run_start)
    sim = _newest(tempdir, ".sim", newer_than=run_start)
    if not exe or not sim:
        if proc.stdout: sys.stdout.write(proc.stdout)
        if proc.stderr: sys.stderr.write(proc.stderr)
        what = "an executable" if not exe else "a .sim init file"
        stale = _find_built_exe(tempdir) if not exe else _newest(tempdir, ".sim")
        if stale:
            print("ERROR: this build did not produce %s in %s (see errors above); "
                  "ignoring stale %s left by a previous run."
                  % (what, tempdir, os.path.basename(stale)), file=sys.stderr)
        else:
            print("ERROR: build did not produce %s in %s (see errors above)."
                  % (what, tempdir), file=sys.stderr)
        return 2

    # 2) parse the override + sweep specs into a list of runs
    try:
        fixed = parse_assignments(args.override)
    except ValueError as e:
        print("ERROR: bad --override: %s" % e, file=sys.stderr)
        return 2
    runs = []
    if args.sweep:
        if "=" not in args.sweep:
            print("ERROR: --sweep must be name=v1,v2,...", file=sys.stderr)
            return 2
        sname, svals = args.sweep.split("=", 1)
        sname = sname.strip()
        for val in [v.strip() for v in svals.split(",") if v.strip()]:
            ov = dict(fixed); ov[sname] = val
            runs.append(("%s_%s" % (sname, val), ov))
        if not runs:
            print("ERROR: --sweep %r produced no values (expected name=v1,v2,...)"
                  % args.sweep, file=sys.stderr)
            return 2
    else:
        runs.append(("override", fixed))

    # 3) check tunability against the .sim (structural params need a rebuild)
    with open(sim, "r", encoding="utf-8", errors="replace") as fh:
        sim_text = fh.read()
    all_names = sorted({k for _, ov in runs for k in ov})
    overridable, needs_rebuild, missing = classify_params(sim_text, all_names)
    if needs_rebuild or missing:
        print("WARNING: the runtime will IGNORE a .sim override for these parameters; "
              "they need a rebuild (set them in the model, or build a wrapper "
              "`model X = %s(param=value)`):" % args.name, file=sys.stderr)
        for n in needs_rebuild:
            print("  - %s (initType != exact: not exactly initializable)" % n, file=sys.stderr)
        for n in missing:
            print("  - %s (absent from .sim: structural / constant-folded / typo)" % n, file=sys.stderr)

    # 4) run each parameter set on the one executable
    try:
        results = run_param_studies(exe, sim, tempdir, runs, args.timeout)
    except subprocess.TimeoutExpired:
        print("ERROR: a parameter run timed out after %ds" % args.timeout, file=sys.stderr)
        return 3

    summary = {
        "tempdir": tempdir, "executable": exe, "base_sim": sim,
        "kernel": kernel, "version": version,
        "msl_version": msl_files["version"] if msl_files else None,
        "overridable": overridable, "needs_rebuild": needs_rebuild, "missing": missing,
        "runs": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n--- wsm_run parameter study ---")
        print("built once: %s" % os.path.basename(exe))
        for r in results:
            status = "ok" if (r["result"] and r["returncode"] == 0) else "FAILED"
            print("  [%s] %-24s -> %s" % (status, r["label"],
                  r["result"] or "(no .mat)"))
            if r["missing_params"]:
                print("        (no-effect params this run: %s)" % ", ".join(r["missing_params"]))
        print("Reuse these .mat files for plotting/analysis.")
        if args.report:
            rvars = [v.strip() for v in args.report.split(",") if v.strip()]
            for r in results:
                if r["result"]:
                    print("\n# %s" % r["label"])
                    run_mat_summary(r["result"], rvars)
    # non-zero if any run failed
    return 0 if all(r["result"] and r["returncode"] == 0 for r in results) else 1


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Cross-platform WSMKernelX launcher.")
    ap.add_argument("--mode", required=True,
                    choices=["validate", "simulate", "diagnose", "info", "libraries"])
    ap.add_argument("--model",
                    help="Path to the .mo file, or (for a directory-form library) the "
                         "library folder or any class file inside it — the whole package "
                         "is loaded and you pass the full dotted name via --name.")
    ap.add_argument("--name", help="Model/package name to test")
    ap.add_argument("--tempdir", help="Working directory (default <model-dir>/_wsm_<mode>_temp)")
    ap.add_argument("--msl", choices=["auto", "yes", "no"], default="auto")
    ap.add_argument("--msl-version", help="Force MSL version, e.g. 4.1.0")
    ap.add_argument("--wsm-home", help="Install root override")
    ap.add_argument("--vsdevcmd", help="Windows: path to VsDevCmd.bat")
    ap.add_argument("--arch", default=os.environ.get("WSM_ARCH", "amd64"),
                    help="Windows VS arch (default amd64; or set $WSM_ARCH)")
    ap.add_argument("--call", choices=["instantiate", "build", "sim"],
                    help="Override the test entry point (staged diagnostics): "
                         "instantiate=instantiateModelTest, build=buildModelTest, sim=simTest")
    ap.add_argument("--load", action="append", default=[], dest="extra_loads",
                    help="Extra .mo file to loadFile before the model, repeatable "
                         "(e.g. a Hydraulic library's package.mo)")
    ap.add_argument("--load-library", action="append", default=[], dest="load_libraries",
                    metavar="NAME[==VER]",
                    help="Locate an installed non-MSL library by name and loadFile it "
                         "before the model, repeatable (e.g. --load-library Hydraulic, or "
                         "--load-library \"Hydraulic==2.1\"). Searches bundled, user-installed, "
                         "and Model-Center custom paths; override with $WSM_LIBRARY_<NAME>. "
                         "Run '--mode libraries' to see what is installed. MSL uses --msl.")
    ap.add_argument("--library",
                    help="libraries mode: resolve just this one library and print its "
                         "package path (ready for --load).")
    ap.add_argument("--library-version",
                    help="libraries mode: with --library, force this exact version.")
    ap.add_argument("--kernel-arg", action="append", default=[],
                    help="Advanced/raw kernel flag, repeatable. Most diagnostics are "
                         "handled for you; prefer --debug over hand-passing flags here.")
    ap.add_argument("--debug", action="store_true",
                    help="diagnose mode: additionally emit the compiler's per-stage dumps "
                         "and execution statistics so an opaque/silent crash can be located. "
                         "Best combined with --call build. Output can be large — redirect to a file.")
    ap.add_argument("--override",
                    help="simulate mode: re-run the compiled model with parameter "
                         "overrides WITHOUT recompiling, e.g. \"kfb=0.04,I0=45e-6\". "
                         "Only works for tunable parameters (the .sim is consulted).")
    ap.add_argument("--sweep",
                    help="simulate mode: sweep one parameter over values, one .mat "
                         "per value, reusing a single build, e.g. \"I0=12e-6,32e-6,90e-6\". "
                         "Combine with --override to hold other parameters fixed.")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress the kernel's stdout/stderr; print only a one-line outcome.")
    ap.add_argument("--report",
                    help="After simulate, print a compact summary (min/max/mean/pp/final) of "
                         "these comma-separated variables from the result .mat.")
    ap.add_argument("--no-sim", action="store_true",
                    help="diagnose mode: build only (buildModelTest + keep artifacts), skip the "
                         "simulation. Much faster when you only need the structural report.")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--no-run", action="store_true",
                    help="Generate the .mos (and .bat on Windows) without running")
    ap.add_argument("--json", action="store_true",
                    help="Emit a machine-readable JSON summary to stdout")
    args = ap.parse_args()

    # --- discover install ---
    try:
        root, kernel, version = find_install(args.wsm_home)
    except RuntimeError as e:
        # libraries mode can still report user-installed / custom-path libraries
        # (they live under the home dir, independent of the install); only the
        # bundled ones under <root>/L are unavailable without an install.
        if args.mode == "libraries":
            print("NOTE: %s\nListing user-installed and custom-path libraries only."
                  % e, file=sys.stderr)
            root, kernel, version = None, None, None
        else:
            print("ERROR: %s" % e, file=sys.stderr)
            return 2

    if args.mode == "info":
        msl = None
        try:
            msl = find_msl(root, args.msl_version)
        except RuntimeError as e:
            print("MSL: %s" % e, file=sys.stderr)
        info = {
            "platform": platform.system(),
            "install_root": root,
            "kernel": kernel,
            "version": version,
            "msl_version": msl["version"] if msl else None,
        }
        if platform.system() == "Windows":
            info["vsdevcmd"] = find_vsdevcmd(args.vsdevcmd)
        libs = discover_libraries(root)
        info["installed_libraries"] = ["%s %s" % (l["name"], l["version"]) if l["version"]
                                       else l["name"] for l in libs]
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("Platform      : %s" % info["platform"])
            print("Install root  : %s" % info["install_root"])
            print("Kernel        : %s" % info["kernel"])
            print("Version       : %s" % info["version"])
            print("MSL version   : %s" % info["msl_version"])
            if "vsdevcmd" in info:
                print("VsDevCmd.bat  : %s" % info["vsdevcmd"])
            libnames = info["installed_libraries"]
            print("Libraries     : %s" % (", ".join(libnames) if libnames
                                          else "(none besides MSL; see --mode libraries)"))
        return 0

    if args.mode == "libraries":
        # Resolve one named library -> print just its package path (for --load).
        if args.library:
            pkg = resolve_library(root, args.library, args.library_version)
            if pkg:
                print(pkg)
                return 0
            searched = "\n".join("  " + p for p in _library_search_locations(root))
            print(
                "ERROR: could not locate an installed '%s'%s library.\n"
                "Searched these locations (none matched):\n%s\n\n"
                "If it is installed elsewhere, set $WSM_LIBRARY_%s to its package.moe "
                "(or its folder)." % (
                    args.library,
                    (" " + args.library_version) if args.library_version else "",
                    searched,
                    re.sub(r"[^A-Za-z0-9]", "_", args.library).upper()),
                file=sys.stderr)
            return 2
        # Otherwise list everything discovered.
        libs = discover_libraries(root)
        if args.json:
            print(json.dumps(libs, indent=2))
        elif not libs:
            print("No non-MSL libraries found. Searched:")
            for p in _library_search_locations(root):
                print("  " + p)
            print("(MSL is loaded automatically via --msl.)")
        else:
            width = max(len(l["name"]) for l in libs)
            print("%-*s  %-8s  %-9s  %s" % (width, "LIBRARY", "VERSION", "SOURCE", "PACKAGE"))
            for l in libs:
                print("%-*s  %-8s  %-9s  %s" % (
                    width, l["name"], l["version"] or "-", l["source"], l["package"]))
            print("\nLoad one into a build with:  --load-library <LIBRARY>"
                  "  (MSL is automatic via --msl)")
        return 0

    # --- validate required args ---
    if not args.model or not args.name:
        print("ERROR: --model and --name are required for mode '%s'" % args.mode,
              file=sys.stderr)
        return 2
    if not _is_model_name(args.name):
        print("ERROR: --name %r is not a valid Modelica class name (dotted identifiers "
              "only); it is interpolated into the generated .mos script." % args.name,
              file=sys.stderr)
        return 2
    target = resolve_model_target(args.model)
    if target is None:
        if os.path.isdir(args.model):
            print("ERROR: model directory has no package.mo (not a directory-form "
                  "library): %s" % args.model, file=sys.stderr)
        else:
            print("ERROR: model file not found: %s" % args.model, file=sys.stderr)
        return 2
    model_load, scan_paths, temp_base, model_kind = target
    if model_kind == "package" and os.path.abspath(model_load) != os.path.abspath(args.model):
        print("NOTE: '%s' is part of a directory-form library; loading the whole "
              "package via %s. Use the full dotted --name (e.g. Package.Model)."
              % (args.model, model_load), file=sys.stderr)
    # Every downstream consumer (build_mos here, in run_with_param_studies, and in
    # the +g recovery re-run) loads args.model, so point it at the resolved target.
    args.model = model_load

    # --- resolve --load-library into concrete package paths (loaded before the model) ---
    if args.load_libraries:
        resolved = []
        for spec in args.load_libraries:
            name, _, ver = spec.partition("==")
            name, ver = name.strip(), ver.strip() or None
            pkg = resolve_library(root, name, ver)
            if not pkg:
                searched = "\n".join("  " + p for p in _library_search_locations(root))
                print(
                    "ERROR: --load-library: could not locate an installed '%s'%s library.\n"
                    "Searched these locations (none matched):\n%s\n\n"
                    "Run '--mode libraries' to see what is installed, pass an explicit path "
                    "with --load, or set $WSM_LIBRARY_%s." % (
                        name, (" " + ver) if ver else "", searched,
                        re.sub(r"[^A-Za-z0-9]", "_", name).upper()),
                    file=sys.stderr)
                return 2
            resolved.append(pkg)
        # libraries first, then any explicit --load files, then the model (via build_mos)
        args.extra_loads = resolved + args.extra_loads

    # --- MSL decision ---
    want_msl = (args.msl == "yes" or
                (args.msl == "auto" and any(model_uses_msl(p) for p in scan_paths)))
    msl_files = None
    if want_msl:
        try:
            msl_files = find_msl(root, args.msl_version)
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 2
        if msl_files is None:
            print("ERROR: the model appears to use the Modelica Standard Library, but no MSL was "
                  "found under %s. Install MSL, pass --msl-version, or re-run with --msl no."
                  % os.path.join(root, "L"), file=sys.stderr)
            return 2
        warn_msl_dialect(scan_paths, msl_files.get("version"))

    # --- temp dir ---
    model_dir = os.path.abspath(temp_base)
    tempdir = os.path.abspath(args.tempdir) if args.tempdir \
        else os.path.join(model_dir, "_wsm_%s_temp" % args.mode)
    os.makedirs(tempdir, exist_ok=True)

    # --- parameter override / sweep: build once, re-run the exe per value -----
    if (args.override or args.sweep):
        if args.mode != "simulate":
            print("ERROR: --override/--sweep are only valid with --mode simulate",
                  file=sys.stderr)
            return 2
        return run_with_param_studies(args, kernel, tempdir, msl_files, version)

    # --- write .mos ---
    mos_name = "%s.mos" % args.mode
    mos_path = os.path.join(tempdir, mos_name)
    for extra in args.extra_loads:
        if not os.path.isfile(extra):
            print("ERROR: --load file not found: %s" % extra, file=sys.stderr)
            return 2
    # diagnose --no-sim: build (keep +g artifacts) but don't simulate.
    effective_call = args.call
    if args.no_sim and args.mode == "diagnose" and not args.call:
        effective_call = "build"
    with open(mos_path, "w", encoding="utf-8") as fh:
        fh.write(build_mos(args.mode, model_load, args.name, msl_files,
                           effective_call, args.extra_loads))

    # --- kernel flags (diagnose only; callers never hand-write these) ---
    # +g keeps the build artifacts under predictable names
    # (ModelName_blockdebug.json, _header.h, .sim, _res.log) that report_blocks.py
    # consumes. BUT +g also turns OFF the kernel's exception catching -- so a *normal*
    # model error (lookup, type, assertion, unbalanced) escapes as an uncaught abort
    # and is reported as nothing. That is exactly the failure this launcher must avoid.
    # So restrict +g to the calls that genuinely need its kept artifacts:
    #   * default / --call sim : the full run that produces the structural report -> +g.
    #     (If it fails, the opaque abort is recovered by rerun_without_g, which re-runs
    #      the same call WITHOUT +g so the kernel catches and reports the real error.)
    #   * --call build         : block-debug for stage localization, but keep exception
    #     catching ON -> use +blt (keeps the block-debug artifacts without disabling catch).
    #   * --call instantiate   : flatten only, no artifacts needed -> no flag, so flatten
    #     errors are caught and reported instead of aborting opaquely.
    kernel_flags = []
    if args.mode == "diagnose":
        if args.call == "build":
            # Explicit build stage = localizing a crash: keep exception catching ON.
            kernel_flags.append("+blt")
        elif effective_call in (None, "sim", "build"):
            # Full run, or --no-sim build-for-report: needs +g's predictable artifact
            # names for report_blocks.py. A healthy model never triggers the
            # catch-disabling downside; a failing one is recovered (see below).
            kernel_flags.append("+g")
        # args.call == "instantiate": no flag, so flatten errors are reported.
        if args.debug:
            kernel_flags += ["+d=daelow,initblt", "+execstat=2"]
    kernel_flags += args.kernel_arg

    vsdevcmd = find_vsdevcmd(args.vsdevcmd) if platform.system() == "Windows" else None

    # A reused tempdir may hold a stale <mode>.out.json from a previous run, which
    # would mask a failure of THIS run. Drop it up front and only accept artifacts
    # written after run_start below (the rest of the tempdir is left alone so the
    # documented warm-toolchain reuse still works).
    out_json = os.path.join(tempdir, "%s.out.json" % args.mode)
    run_start = time.time() - _MTIME_SLACK
    if not args.no_run and os.path.isfile(out_json):
        try:
            os.remove(out_json)
        except OSError:
            pass  # _fresh() below still keeps a stale file from being trusted

    try:
        proc = run_kernel(kernel, tempdir, mos_name, kernel_flags, args.mode,
                          args.timeout, args.arch, vsdevcmd, args.no_run)
    except subprocess.TimeoutExpired:
        print("ERROR: kernel timed out after %ds" % args.timeout, file=sys.stderr)
        return 3
    except RuntimeError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2

    if args.no_run:
        print("Generated %s (not run; --no-run)." % mos_path)
        return 0

    summary = {
        "tempdir": tempdir,
        "mos": mos_path,
        "out_json": out_json if _fresh(out_json, run_start) else None,
        "kernel": kernel,
        "version": version,
        "msl_version": msl_files["version"] if msl_files else None,
        "returncode": proc.returncode,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    elif args.quiet:
        print(quiet_outcome(out_json, proc, tempdir, run_start))
    else:
        # forward the kernel's own stdout/stderr for the model
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        print("\n--- wsm_run summary ---")
        print("temp dir : %s" % tempdir)
        print("out.json : %s" % (summary["out_json"] or "(not produced)"))
        print("kernel   : %s (v%s, MSL %s)" % (kernel, version, summary["msl_version"]))

    # On a failed run, dig the real diagnostic out of the kernel output and print it
    # at the tail (where `tail -N run.log` will catch it), so an opaque
    # uncaught-exception abort is not mistaken for an unknowable crash.
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    run_failed = (proc.returncode != 0 or summary["out_json"] is None
                  or FATAL_EXCEPTION_TOKEN in combined
                  or _SIM_ERROR_RE.search(combined) is not None)
    if run_failed and not args.no_run:
        sys.stdout.flush()
        # +g is the only flag that disables exception catching, so the re-run-without-+g
        # recovery can only add something when +g was actually used. (It is added only
        # for diagnose; a user could also pass it via --kernel-arg.)
        recover = None
        if "+g" in kernel_flags:
            recover = lambda: rerun_without_g(
                kernel, args, msl_files, tempdir, kernel_flags, effective_call,
                args.arch, vsdevcmd)
        surface_kernel_error(combined, tempdir, recover=recover)

    # optional compact result summary (only for a successful run, and only from a
    # .mat this run actually wrote -- never a leftover from a previous run)
    if args.report and args.mode in ("simulate", "diagnose"):
        sys.stdout.flush()  # keep the status/summary line above the report table
        if run_failed:
            print("(--report skipped: this run failed; not summarizing a stale or "
                  "partial .mat)", file=sys.stderr)
        else:
            mat = _newest(tempdir, ".mat", newer_than=run_start)
            if not mat:
                stale = _newest(tempdir, ".mat")
                if stale:
                    print("(--report: no .mat from this run; ignoring stale %s)"
                          % os.path.basename(stale), file=sys.stderr)
            run_mat_summary(mat,
                            [v.strip() for v in args.report.split(",") if v.strip()])

    if run_failed and proc.returncode == 0:
        return 1  # kernel exited 0 but the run demonstrably failed
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
