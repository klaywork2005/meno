"""Bundled asset locations."""

import sys
from pathlib import Path


def asset_path(*parts: str) -> Path:
    """Find an asset in a source checkout or packaged application."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root.joinpath("assets", *parts)
