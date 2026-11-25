#!/usr/bin/env python3
"""Check that custom model damage particles use their intended texture instead of oak planks."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "src/main/resources/assets/pastoral_home/models/block"
models = sorted(MODEL_ROOT.rglob("*.json"))
issues = []
for path in models:
    data = json.loads(path.read_text(encoding="utf-8"))
    textures = data.get("textures", {})
    custom = any(key != "particle" and isinstance(value, str)
                 and value.startswith("pastoral_home:block/") for key, value in textures.items())
    if custom and textures.get("particle") == "minecraft:block/oak_planks":
        issues.append(path.relative_to(MODEL_ROOT).as_posix())
    particle = textures.get("particle")
    if particle in {value for key, value in textures.items() if key != "particle"}:
        if isinstance(particle, str) and particle.startswith("pastoral_home:block/"):
            texture_path = ROOT / "src/main/resources/assets/pastoral_home/textures" / f"{particle.split(':', 1)[1]}.png"
            if texture_path.is_file() and Image.open(texture_path).size != (16, 16):
                issues.append(f"{path.relative_to(MODEL_ROOT).as_posix()}: particle still references a packed atlas")
assert not issues, "Custom models still emit oak-plank break particles: " + ", ".join(issues)
for name in ("hanging_rope_segment.json", "hanging_rope_end.json",
             "wardrobe_closed_l0_c0.json", "wardrobe_open_l0_c0.json"):
    data = json.loads((MODEL_ROOT / name).read_text(encoding="utf-8"))
    particle = data["textures"]["particle"]
    assert particle.endswith("_particle"), f"{name} should use a dedicated particle tile, got {particle}"
    image = ROOT / "src/main/resources/assets/pastoral_home/textures/block" / f"{particle.rsplit('/', 1)[-1]}.png"
    assert image.is_file() and Image.open(image).size == (16, 16), f"{name} particle tile must be a 16x16 image"

TEXTURES = ROOT / "src/main/resources/assets/pastoral_home/textures/block"


def frame_of(texture: Path) -> Image.Image:
    """One frame of an animated sheet: Minecraft stacks square frames, so the frame is the sheet's width."""
    image = Image.open(texture).convert("RGBA")
    meta = Path(str(texture) + ".mcmeta")
    if meta.is_file():
        height = json.loads(meta.read_text(encoding="utf-8")).get("animation", {}).get("height") or image.width
        return image.crop((0, 0, image.width, height))
    return image


def natural_window(tile: Image.Image, frame: Image.Image) -> bool:
    """Is the tile the frame's own texels at 1:1, rather than a resampled window?

    The tile may not be a scaled-up crop: resampling a four-texel paint block produces a staircase, which
    is what the party light rained when it broke. A flat tile is allowed; a patterned one has to exist
    somewhere in the frame with no resampling at all.
    """
    if len({pixel[:3] for pixel in tile.getdata()}) == 1:
        return True
    if frame.width < tile.width or frame.height < tile.height:
        return False
    want = tile.tobytes()
    for y in range(frame.height - tile.height + 1):
        for x in range(frame.width - tile.width + 1):
            if frame.crop((x, y, x + tile.width, y + tile.height)).tobytes() == want:
                return True
    return False


for name in ("party_lights_lit.json", "party_lights_unlit.json", "hanging_rope_segment.json"):
    data = json.loads((MODEL_ROOT / name).read_text(encoding="utf-8"))
    textures = data["textures"]
    tile_name = textures["particle"].rsplit("/", 1)[-1]
    tile = (TEXTURES / (tile_name + ".png"))
    assert tile.is_file() and Image.open(tile).size == (16, 16), f"{name} particle tile must be a 16x16 image"
    sources = [value for key, value in textures.items() if key != "particle"]
    assert sources, f"{name} has no source texture to shape debris from"
    assert natural_window(Image.open(tile).convert("RGBA"),
                          frame_of(TEXTURES / (sources[0].rsplit("/", 1)[-1] + ".png"))), (
        f"{name} particle tile is a resampled window, not paint at the sheet's own texel scale")

print(f"Block particles verified: {len(models)} models; atlas-backed models use dedicated 16x16 face tiles.")
