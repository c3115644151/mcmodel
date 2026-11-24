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
print(f"Block particles verified: {len(models)} models; atlas-backed models use dedicated 16x16 face tiles.")
