#!/usr/bin/env python3
"""Fit the authored wardrobe UI art to Minecraft's fixed 176x222 container footprint."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/wardrobe/wardrobe_gui_source.png"
OUTPUT = ROOT / "src/main/resources/assets/pastoral_home/textures/gui/wardrobe_inventory.png"


def main() -> None:
    with Image.open(SOURCE) as image:
        source = image.convert("RGBA")
    width, height = source.size
    if height < 194 or width < 1:
        raise ValueError(f"Wardrobe GUI source is too small: {source.size}")

    # Preserve the title, storage, divider, and player-inventory zones while
    # fitting the standard chest-sized panel. Slot wells are drawn at fixed
    # Java menu coordinates on top of this art.
    segments = (
        ((0, 0, width, 38), 18),
        ((0, 38, width, 188), 110),
        ((0, 188, width, 194), 2),
        ((0, 194, width, height), 92),
    )
    output = Image.new("RGBA", (176, 222))
    y = 0
    for bounds, target_height in segments:
        strip = source.crop(bounds).resize((176, target_height), Image.Resampling.NEAREST)
        output.alpha_composite(strip, (0, y))
        y += target_height
    if y != 222:
        raise AssertionError(f"Wardrobe UI layout ended at y={y}, expected 222")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.save(OUTPUT)
    print(f"Prepared wardrobe UI texture at fixed container size: {OUTPUT}")


if __name__ == "__main__":
    main()
