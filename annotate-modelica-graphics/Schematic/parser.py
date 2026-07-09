"""Re-export the shared ``scripts/modelica_parser.py`` so this skill's modules can keep using
``from .parser import ...`` while the parser lives in one place (shared with the other annotation
skills). Locates ``scripts/`` via ``$WSM_SKILLS_SCRIPTS`` or ``../scripts``.
"""

from __future__ import annotations

import os
import sys


def _scripts_dir() -> str:
    cands = [os.environ.get("WSM_SKILLS_SCRIPTS")]
    here = os.path.abspath(__file__)
    for base in (here, os.path.realpath(here)):
        cands.append(os.path.join(os.path.dirname(os.path.dirname(base)), "..", "scripts"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "modelica_parser.py")):
            return os.path.abspath(c)
    raise ImportError(
        "shared modelica_parser.py not found in scripts/. Set $WSM_SKILLS_SCRIPTS, or run the "
        "repo install.sh / install.ps1 so scripts/ is linked next to the skills.")


_d = _scripts_dir()
if _d not in sys.path:
    sys.path.insert(0, _d)

import modelica_parser as _mp  # noqa: E402

globals().update({k: v for k, v in vars(_mp).items() if not k.startswith("__")})

del _mp, _d
