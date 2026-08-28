"""The HUD layout as a loadable, editable data model.

:class:`HudLayout` is loaded from JSON. The renderer draws from it and the
hit-test reads the same object, so displayed and pressable geometry cannot
diverge. Editing the HUD - by hand in ``%APPDATA%/Meno/hud.json`` or by
dragging a button in the application - is a mutation of this object followed by
a save.

Positions are stored as fractions of the frame, not pixels, so one layout is
correct at any capture resolution.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# Actions a button may carry. An unknown action is ignored rather than raising,
# so a HUD file written by a newer version still loads in an older one.
ACTIONS = ("clear", "set_color")

Rect = tuple[int, int, int, int]


# --------------------------------------------------------------------------- #
# Colour conversion
# --------------------------------------------------------------------------- #
# The JSON stores "#rrggbb". OpenCV uses BGR tuples and Qt uses RGB. Conversion
# happens at the edges; only one representation of a colour is stored.

def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert ``"#rrggbb"`` to an ``(r, g, b)`` tuple."""
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def hex_to_bgr(value: str) -> tuple[int, int, int]:
    """Convert ``"#rrggbb"`` to OpenCV's ``(b, g, r)`` order."""
    r, g, b = hex_to_rgb(value)
    return (b, g, r)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Convert an ``(r, g, b)`` tuple to ``"#rrggbb"``."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #

@dataclass
class HudButton:
    """One toolbar button, positioned as a fraction of the frame width."""

    id: str
    x1_pct: float
    x2_pct: float
    fill: str = "#000000"
    label: str | None = None
    action: str = "clear"
    arg: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> HudButton:
        """Build a button from its JSON representation."""
        return cls(
            id=data["id"],
            x1_pct=float(data["x1_pct"]),
            x2_pct=float(data["x2_pct"]),
            fill=data.get("fill", "#000000"),
            label=data.get("label"),
            action=data.get("action", "clear"),
            arg=data.get("arg"),
        )

    def to_dict(self) -> dict:
        """Return the button's JSON representation."""
        return {
            "id": self.id, "label": self.label,
            "x1_pct": round(self.x1_pct, 4), "x2_pct": round(self.x2_pct, 4),
            "fill": self.fill, "action": self.action, "arg": self.arg,
        }


DEFAULT_THEME: dict = {
    "label_color": "#ffffff",
    "font_px": 13,
    "corner_radius": 6,
    "border_color": "#ffffff",
    "border_width": 1,
    "active_border_color": "#ffffff",
    "active_border_width": 3,
    "opacity": 0.85,
}


@dataclass
class HudLayout:
    """The button strip: its height, contents, appearance and palette."""

    band_pct: float = 0.135
    palette: list[str] = field(default_factory=lambda: ["#0000ff", "#00ff00",
                                                        "#ff0000", "#ffff00"])
    buttons: list[HudButton] = field(default_factory=list)
    theme: dict = field(default_factory=lambda: dict(DEFAULT_THEME))

    # --- Persistence ------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> HudLayout:
        """Build a layout from its JSON representation."""
        theme = dict(DEFAULT_THEME)
        theme.update(data.get("theme", {}))
        return cls(
            band_pct=float(data.get("band_pct", 0.135)),
            palette=list(data.get("palette", cls().palette)),
            buttons=[HudButton.from_dict(b) for b in data.get("buttons", [])],
            theme=theme,
        )

    @classmethod
    def load(cls, path: Path | str) -> HudLayout:
        """Read a layout from a JSON file."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        """Return the layout's JSON representation."""
        return {
            "band_pct": round(self.band_pct, 4),
            "palette": list(self.palette),
            "theme": dict(self.theme),
            "buttons": [b.to_dict() for b in self.buttons],
        }

    def save(self, path: Path | str) -> None:
        """Write the layout to a JSON file."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    # --- Geometry ---------------------------------------------------------
    # All callers obtain pixels through these methods, so the fraction to pixel
    # conversion exists in one place.

    def band_height(self, frame_h: int) -> int:
        """Pixel height of the button strip for a frame of this height.

        A pen tip at or above this line is a button press; below it, a stroke.
        """
        return max(1, int(round(self.band_pct * frame_h)))

    def rects(self, frame_w: int, frame_h: int
              ) -> Iterator[tuple[HudButton, Rect]]:
        """Yield ``(button, (x1, y1, x2, y2))`` in frame pixels."""
        band = self.band_height(frame_h)
        for button in self.buttons:
            x1 = int(round(button.x1_pct * frame_w))
            x2 = int(round(button.x2_pct * frame_w))
            yield button, (x1, 1, x2, band)

    def hit(self, x: int, y: int, frame_w: int,
            frame_h: int) -> HudButton | None:
        """Return the button containing the point, or ``None``.

        Later buttons win an overlap, matching the paint order.
        """
        found = None
        for button, (x1, y1, x2, y2) in self.rects(frame_w, frame_h):
            if x1 <= x <= x2 and y1 <= y <= y2:
                found = button
        return found

    # --- Palette ----------------------------------------------------------

    def palette_bgr(self) -> list[tuple[int, int, int]]:
        """The palette in OpenCV's channel order."""
        return [hex_to_bgr(c) for c in self.palette]

    def color_slots(self) -> int:
        """The number of brush colours. Stroke buffers are sized to this."""
        return len(self.palette)
