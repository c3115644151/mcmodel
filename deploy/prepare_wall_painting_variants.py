#!/usr/bin/env python3
"""Import the three authored paintings as texture variants of the existing frame."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE_DIR = ROOT / "tools/deploy/model_sources/wall_painting_variants"
BUILD_DIR = ROOT / "build/requested_models/wall_paintings"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
VARIANTS = {
    1: ("overworld", "painting_overworld.bbmodel"),
    2: ("nether", "painting_nether.bbmodel"),
    3: ("end", "painting_end.bbmodel"),
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_source(name: str, source_name: str) -> dict:
    model_path = BUILD_DIR / f"{name}.json"
    texture_path = ASSETS / f"textures/block/wall_painting_{name}.png"
    source_path = SOURCE_DIR / source_name
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing authored painting source: {source_path}")
    subprocess.run([
        sys.executable, str(IMPORTER), str(source_path),
        "--model-out", str(model_path), "--texture-out", str(texture_path),
        "--texture-name", f"wall_painting_{name}",
    ], cwd=ROOT, check=True)
    return load(model_path)


def fit_existing_anchor(model: dict, texture_name: str) -> dict:
    """Align authored 32px paintings to the existing two-cell wall anchor.

    Source BB coordinates are centered at x=8, with the front plane at z=7..9.
    Existing runtime geometry uses x=0..32 and z=14..16. The y affine map
    preserves the hanging eyelet at the old lower edge and seats the 32px panel
    exactly at the existing 31px selection envelope.
    """
    result = copy.deepcopy(model)
    result["textures"]["bb_texture_0"] = f"pastoral_home:block/wall_painting_{texture_name}"
    result["textures"]["particle"] = "minecraft:block/oak_planks"
    for index, element in enumerate(result.get("elements", [])):
        if element.get("rotation"):
            raise ValueError(f"{texture_name}: expected unrotated frame cubes, got rotation at {index}")
        for point in ("from", "to"):
            element[point][0] = float(element[point][0]) + 8.0
            element[point][1] = -15.0 + float(element[point][1]) * (31.0 / 32.0)
            element[point][2] = float(element[point][2]) + 7.0
        if "origin" in element:
            element["origin"][0] = float(element["origin"][0]) + 8.0
            element["origin"][1] = -15.0 + float(element["origin"][1]) * (31.0 / 32.0)
            element["origin"][2] = float(element["origin"][2]) + 7.0
    if len(result.get("elements", [])) != 2:
        raise ValueError(f"{texture_name}: expected a frame and hanging eyelet, got {len(result.get('elements', []))} cubes")
    bounds = [
        min(float(e["from"][axis]) for e in result["elements"]) for axis in range(3)
    ] + [
        max(float(e["to"][axis]) for e in result["elements"]) for axis in range(3)
    ]
    expected = (0.0, -16.0, 14.0, 32.0, 16.0, 16.0)
    if any(abs(actual - target) > 0.04 for actual, target in zip(bounds, expected)):
        raise ValueError(f"{texture_name}: model no longer aligns with existing frame bounds {bounds}")
    return result


def backside(model: dict) -> dict:
    result = copy.deepcopy(model)
    for element in result.get("elements", []):
        faces = element.get("faces", {})
        if "north" in faces and "south" in faces:
            faces["north"], faces["south"] = faces["south"], faces["north"]
    return result


def state_file() -> dict:
    multipart = []
    names = {0: "", 1: "_overworld", 2: "_nether", 3: "_end"}
    for artwork in range(4):
        for flipped in (False, True):
            for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
                suffix = "_back" if flipped else ""
                model = f"pastoral_home:block/wall_painting{names[artwork]}{suffix}"
                value = {"model": model}
                if angle:
                    value["y"] = angle
                multipart.append({"when": {
                    "artwork": str(artwork), "facing": facing, "flipped": str(flipped).lower(),
                }, "apply": value})
    return {"multipart": multipart}


def representative_item_icon() -> None:
    """Show one clear front-facing sample; world placement still chooses randomly."""
    path = ASSETS / "items/wall_painting.json"
    definition = load(path)
    tree = definition.get("model", {})
    if tree.get("type") != "minecraft:select" or tree.get("property") != "minecraft:display_context":
        raise ValueError("Wall painting item must keep its GUI-only display-context selector")
    gui = next((case.get("model") for case in tree.get("cases", [])
                if case.get("when") in ("gui", ["gui"])), None)
    if not isinstance(gui, dict) or gui.get("type") != "minecraft:model":
        raise ValueError("Wall painting GUI selector is missing its model node")
    gui["model"] = "pastoral_home:block/wall_painting_overworld"
    save(path, definition)


def main() -> None:
    model_dir = ASSETS / "models/block"
    for artwork, (name, source_name) in VARIANTS.items():
        model = fit_existing_anchor(import_source(name, source_name), name)
        save(model_dir / f"wall_painting_{name}.json", model)
        save(model_dir / f"wall_painting_{name}_back.json", backside(model))
    save(ASSETS / "blockstates/wall_painting.json", state_file())
    representative_item_icon()
    print("Prepared 3 authored paintings + both sides, preserving the existing four-cell frame and random state mapping.")


if __name__ == "__main__":
    main()
