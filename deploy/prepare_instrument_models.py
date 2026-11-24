#!/usr/bin/env python3
"""Rebuild the scroll and record player resources from committed sources.

The piano moved to prepare_piano_models.py: its keyboard is generated geometry
that has to be laid out in world space before the grid split, which is not a
patch this script can apply to an already cell-owned model. The scroll is a single
sheet that stays in one cell; its authored plane is one pixel thick so the
selection box has a body to aim at. The record player is a 1-wide by 2-high
cabinet whose three-axis horn comes from export_free_obj.py as a neoforge:obj
model.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE_DIR = ROOT / "tools/deploy/model_sources/instruments"
BUILD_DIR = ROOT / "build/instrument_models"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
sys.path.insert(0, str(ROOT / "tools/deploy"))
from item_icon_proxy import geometry_bounds  # noqa: E402
from split_model_cells import split_model  # noqa: E402

# Blockbench's inflate pushes the outermost piano shell to z = -0.2. Minecraft
# accepts that, but a cell-owned split would carve a second depth row for a
# 0.2px lip. Keep a hair of clearance inside the single authored depth cell so
# the shell still cannot z-fight with the cube it wraps.
DEPTH_EPSILON = 0.05
# A loose prop still needs a body to aim at: the authored paper plane is one
# pixel of air, so the crosshair slips through it to the floor below.
SCROLL_SHEET_THICKNESS = 1.0


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_model(name: str, source: Path | None = None) -> dict:
    source = source or (SOURCE_DIR / f"{name}.bbmodel")
    if not source.is_file():
        raise FileNotFoundError(f"Missing source model: {source}")
    raw_path = BUILD_DIR / f"{name}_raw.json"
    texture = ASSETS / f"textures/block/{name}.png"
    subprocess.run([
        sys.executable, str(IMPORTER), str(source),
        "--model-out", str(raw_path), "--texture-out", str(texture),
        "--texture-name", name,
    ], cwd=ROOT, check=True)
    return load(raw_path)


def shift(model: dict, dx: float, dy: float, dz: float) -> dict:
    result = copy.deepcopy(model)
    for element in result["elements"]:
        for point in ("from", "to"):
            element[point][0] = round(float(element[point][0]) + dx, 6)
            element[point][1] = round(float(element[point][1]) + dy, 6)
            element[point][2] = round(float(element[point][2]) + dz, 6)
        rotation = element.get("rotation")
        if rotation and rotation.get("origin"):
            rotation["origin"][0] = round(float(rotation["origin"][0]) + dx, 6)
            rotation["origin"][1] = round(float(rotation["origin"][1]) + dy, 6)
            rotation["origin"][2] = round(float(rotation["origin"][2]) + dz, 6)
    return result


def clamp_depth(model: dict, low: float, high: float) -> list[str]:
    """Pull cubes and their rotation origins inside one authored depth cell."""
    clamped = []
    for index, element in enumerate(model["elements"]):
        touched = False
        for point in ("from", "to"):
            value = float(element[point][2])
            bounded = min(max(value, low), high)
            if abs(bounded - value) > 1e-9:
                touched = True
                element[point][2] = round(bounded, 6)
        rotation = element.get("rotation")
        if rotation and rotation.get("origin"):
            value = float(rotation["origin"][2])
            bounded = min(max(value, low), high)
            if abs(bounded - value) > 1e-9:
                touched = True
                rotation["origin"][2] = round(bounded, 6)
        if touched:
            clamped.append(f"{index}:{element.get('name', '?')}")
    return clamped


def thicken_sheets(model: dict, thickness: float = SCROLL_SHEET_THICKNESS):
    """Give every zero-thickness sheet a real body of its own.

    Blockbench authors a paper plane with identical from/to on one axis. It
    renders, but nothing can be aimed at, so the block needs geometry with
    depth. The sheet is expanded symmetrically so its centre never moves; the
    side faces Blockbench left as single-texel strips then read as the paper
    edge instead of a stray line.
    """
    result = copy.deepcopy(model)
    thickened = []
    for index, element in enumerate(result.get("elements", [])):
        for axis in range(3):
            span = float(element["to"][axis]) - float(element["from"][axis])
            if abs(span) > 1e-6:
                continue
            centre = (float(element["from"][axis]) + float(element["to"][axis])) * 0.5
            element["from"][axis] = round(centre - thickness * 0.5, 6)
            element["to"][axis] = round(centre + thickness * 0.5, 6)
            thickened.append((index, "xyz"[axis]))
    return result, thickened


def extents(model: dict) -> tuple[float, float, float, float, float, float]:
    xs = [float(element[point][axis]) for element in model["elements"] for point in ("from", "to") for axis in (0,)]
    ys = [float(element[point][1]) for element in model["elements"] for point in ("from", "to")]
    zs = [float(element[point][2]) for element in model["elements"] for point in ("from", "to")]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def cell_bounds(elements: list[dict]) -> list[float]:
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for element in elements:
        for point in ("from", "to"):
            for axis in range(3):
                value = float(element[point][axis])
                lo[axis] = min(lo[axis], value)
                hi[axis] = max(hi[axis], value)
    if lo[0] > hi[0]:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return [round(value, 4) for value in lo + hi]



def scroll_blockstates() -> dict:
    variants = {}
    for facing, rotation in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        apply = {"model": "pastoral_home:block/scroll"}
        if rotation:
            apply["y"] = rotation
        variants[f"facing={facing}"] = apply
    return {"variants": variants}


def simple_item(model: str) -> dict:
    return {"model": {"type": "minecraft:model", "model": model}}


def main() -> None:
    model_dir = ASSETS / "models/block"
    manifest = {}

    scroll_raw, thickened = thicken_sheets(import_model("scroll"))
    sx0, sy0, sz0, sx1, sy1, sz1 = extents(scroll_raw)
    if abs(sx0) > 0.02 or abs(sx1 - 16.0) > 0.02 or abs(sz0) > 0.02 or abs(sz1 - 16.0) > 0.02:
        raise ValueError(f"Unexpected scroll extents: {(sx0, sy0, sz0, sx1, sy1, sz1)}")
    save(model_dir / "scroll.json", scroll_raw)
    save(ASSETS / "blockstates/scroll.json", scroll_blockstates())
    save(ASSETS / "items/scroll.json", simple_item("pastoral_home:block/scroll"))
    manifest["scroll"] = {"elements": len(scroll_raw["elements"]),
                          "bounds": cell_bounds(scroll_raw["elements"]),
                          "thickened": thickened}

    save(BUILD_DIR / "instrument_split_manifest.json", manifest)
    print("Prepared the scroll as one sheet; the record player comes from export_free_obj.py "
          "as a neoforge:obj model and the piano from prepare_piano_models.py.")
    for key, value in manifest.items():
        print(" ", key, value)


if __name__ == "__main__":
    main()
