"""File locations and persisted settings.

Two directories are used and must not be confused:

*bundle*  read-only, ships with the application (default themes, icon). Under
          PyInstaller this is an extraction directory, not the source tree, so
          it is resolved through ``sys._MEIPASS``.
*user*    read-write, per machine (``%APPDATA%/Meno``). Everything the
          application saves goes here, never beside the executable, because
          the Program Files directory is not writable.

The first run copies the bundled theme into the user directory. Later versions
ship a new bundled default and leave the user's copy unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Meno"


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

def bundle_dir() -> Path:
    """Root of the read-only files shipped with the application.

    ``sys._MEIPASS`` exists only inside a PyInstaller bundle; the fallback to
    this file's parent is what makes the same code work from a source checkout.
    """
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def asset_path(*parts: str) -> Path:
    """Path to a bundled asset, e.g. ``asset_path("themes", "default.json")``."""
    return bundle_dir().joinpath("assets", *parts)


def user_dir() -> Path:
    """The per-user configuration directory, created if absent."""
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def hud_path() -> Path:
    """Path to the user's editable HUD layout."""
    return user_dir() / "hud.json"


def settings_path() -> Path:
    """Path to the user's application settings."""
    return user_dir() / "settings.json"


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

# HSV windows known to work, so a new user has a usable starting point. Hue is
# 0-180 in OpenCV (half the usual 0-360, so it fits in a byte); saturation and
# value are 0-255.
DEFAULT_PRESETS: dict[str, dict[str, list[int]]] = {
    "Blue object":   {"lower": [100, 83, 84],  "upper": [136, 255, 255]},
    "Green object":  {"lower": [36, 80, 70],   "upper": [86, 255, 255]},
    "Red object":    {"lower": [0, 120, 80],   "upper": [10, 255, 255]},
    "Yellow object": {"lower": [20, 100, 100], "upper": [35, 255, 255]},
}

DEFAULT_SETTINGS: dict = {
    "camera_index": 0,
    "preset": "Blue object",
    "presets": DEFAULT_PRESETS,
    "show_paint": True,
    "show_mask": False,
    # Auto-exposure lowers the frame rate in low light: 30fps becomes about
    # 12. Locked by default, which also keeps colours constant for the HSV
    # thresholds. See meno.camera.
    "lock_exposure": True,
    "exposure": -6,
}


def load_settings() -> dict:
    """Read settings, substituting defaults for anything missing.

    A corrupt file must not prevent startup, so a parse failure yields the
    defaults; the next save rewrites the file.
    """
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    try:
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings

    settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    # Presets are merged rather than replaced, so a newly bundled preset
    # appears for users who already have a settings file.
    merged = dict(DEFAULT_PRESETS)
    merged.update(stored.get("presets", {}))
    settings["presets"] = merged
    return settings


def save_settings(settings: dict) -> None:
    """Write settings to disk as indented JSON."""
    settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# First run
# --------------------------------------------------------------------------- #

def ensure_user_hud() -> Path:
    """Create the user's HUD file from the bundled default if absent.

    Returns its path.
    """
    target = hud_path()
    if not target.exists():
        shutil.copyfile(asset_path("themes", "default.json"), target)
    return target


def reset_user_hud() -> Path:
    """Overwrite the user's HUD with the bundled default. Returns its path."""
    target = hud_path()
    shutil.copyfile(asset_path("themes", "default.json"), target)
    return target
