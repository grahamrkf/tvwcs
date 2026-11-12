"""TVWCS - TV Window Channel Switcher: a remote-friendly GTK 4 launcher for sway."""

import os
from pathlib import Path


def _read_version():
    """The VERSION file: next to the package once installed (/usr/lib/tvwcs/VERSION), at the repository root in a checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "VERSION", here.parent.parent / "VERSION"):
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return os.environ.get("TVWCS_VERSION", "0.0.0.dev0")  # installed as a wheel without the repo tree


__version__ = _read_version()

# Where TVWCS runs from: PACKAGE_DIR is this folder (/usr/lib/tvwcs/tvwcs once installed, package/tvwcs in the
# repository) and LIB_DIR the folder above it, which is what PYTHONPATH needs for `python3 -m tvwcs....`.
PACKAGE_DIR = Path(__file__).resolve().parent
LIB_DIR = PACKAGE_DIR.parent
