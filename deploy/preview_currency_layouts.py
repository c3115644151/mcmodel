#!/usr/bin/env python3
"""Build an offline contact sheet for count-driven coin pile meshes."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
PREVIEW_ROOT = ROOT / "build/requested_models/currency_preview_root"
KINDS = ("gold", "silver", "copper")
LAYOUT = 5
SEED = 0x1368ABCD


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def mix(value: int) -> int:
    mask = (1 << 64) - 1
    value &= mask
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9
    value &= mask
    value = (value ^ (value >> 27)) * 0x94D049BB133111EB
    value &= mask
    return value ^ (value >> 31)


def plan(counts, positions, capacities):
    remaining = list(counts)
    placed = [0, 0, 0]
    placed_column = [0] * len(capacities)
    out = []
    total = sum(counts)
    for index in range(total):
        tie_start = mix(SEED + index) % 3
        kind = min((kind for kind in range(3) if remaining[kind] > 0),
                   key=lambda kind: ((placed[kind] + 1) / (placed[kind] + remaining[kind] + 1),
                                     (kind - tie_start) % 3))
        remaining[kind] -= 1
        placed[kind] += 1
        start = mix(SEED + index) % len(capacities)
        column = min((column for column in range(len(capacities)) if placed_column[column] < capacities[column]),
                     key=lambda column: ((placed_column[column] + 1) / capacities[column],
                                         (column - start) % len(capacities)))
        layer = placed_column[column]
        placed_column[column] += 1
        yaw = (mix(SEED + 0x9E3779B97F4A7C15 * (index + 1)) % 8) * 45
        out.append((kind, positions[column % len(positions)], layer / 16.0, yaw))
    return out


def translate(element, dx, dy, dz):
    result = copy.deepcopy(element)
    for point in ("from", "to"):
        result[point] = [result[point][0] + dx, result[point][1] + dy, result[point][2] + dz]
    rotation = result.get("rotation")
    if rotation and rotation.get("origin"):
        rotation["origin"] = [rotation["origin"][0] + dx,
                              rotation["origin"][1] + dy,
                              rotation["origin"][2] + dz]
    return result


def main():
    assets = PREVIEW_ROOT / "src/main/resources/assets/pastoral_home"
    (assets / "models/block").mkdir(parents=True, exist_ok=True)
    (assets / "items").mkdir(parents=True, exist_ok=True)
    (assets / "textures/block").mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        shutil.copy2(PROJECT_ASSETS / f"textures/block/coin_{kind}.png",
                     assets / f"textures/block/coin_{kind}.png")
    (PREVIEW_ROOT / "gradle.properties").write_text("mod_id=pastoral_home\n", encoding="utf-8")

    base_models = [read(PROJECT_ASSETS / f"models/block/coin_{kind}.json") for kind in KINDS]
    positions = read(ROOT / "build/requested_models/currency/currency_asset_manifest.json")
    layout_entry = next(entry for entry in positions if entry.get("layout") == "mixed_gold_silver")
    layout_positions = layout_entry["positions"]
    layout_capacities = layout_entry["capacities"]
    samples = {
        "coin_preview_gold_1": [1, 0, 0],
        "coin_preview_gold_8": [8, 0, 0],
        "coin_preview_gold_32": [32, 0, 0],
        "coin_preview_gold_64": [64, 0, 0],
        "coin_preview_gold_silver": [32, 32, 0],
        "coin_preview_gold_copper": [32, 0, 32],
        "coin_preview_silver_copper": [0, 32, 32],
        "coin_preview_three_way": [20, 22, 22],
    }
    for item_id, counts in samples.items():
        model_id = item_id.replace("coin_preview_", "currency_preview_")
        elements = []
        for kind_index, position, y, yaw in plan(counts, layout_positions, layout_capacities):
            model = base_models[kind_index]
            part = translate(model["elements"][0], position[0] * 16, y * 16, position[1] * 16)
            for face in part.get("faces", {}).values():
                if face.get("texture") == "#bb_texture_0":
                    face["texture"] = f"#coin_{KINDS[kind_index]}"
            if part.get("rotation"):
                part["rotation"]["angle"] += yaw
            elements.append(part)
        model = {
            "parent": "minecraft:block/block",
            "textures": {f"coin_{kind}": f"pastoral_home:block/coin_{kind}" for kind in KINDS},
            "elements": elements,
        }
        (assets / f"models/block/{model_id}.json").write_text(
            json.dumps(model, indent=2) + "\n", encoding="utf-8")
        definition = {"model": {"type": "minecraft:select", "property": "minecraft:display_context",
                                "cases": [{"when": "gui", "model": {"type": "minecraft:model",
                                                                            "model": f"pastoral_home:block/{model_id}"}}],
                                "fallback": {"type": "minecraft:model", "model": f"pastoral_home:block/{model_id}"}}}
        (assets / f"items/{item_id}.json").write_text(
            json.dumps(definition, indent=2) + "\n", encoding="utf-8")
    preview = ROOT / "tools/deploy/preview_item_icons.py"
    subprocess.run([sys.executable, str(preview), "--root", str(PREVIEW_ROOT),
                    "--items", ",".join(samples), "--vanilla-reference",
                    "--output", "build/requested_models/currency/count_growth_preview.png",
                    "--report", "build/requested_models/currency/count_growth_preview.json"],
                   cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
