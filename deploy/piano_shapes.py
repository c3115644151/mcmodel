#!/usr/bin/env python3
"""Re-derive the piano's collision boxes from the prepared per-cell models.

The piano is the only instrument whose VoxelShape is hand-written into the Java class
(`PianoBlock.SHAPES`), because three cells times two storeys would otherwise need twelve
separate overrides. Hand-written numbers drift the moment the exporter moves the model, so
this module is the single source for those numbers:

* `boxes()` voxelises `models/block/piano_l{layer}_c{column}.json` with the same settings the
  original table used (resolution 8 per cell, rotated parts included, exposure allowed).
* `java_source()` prints the snippet to paste into `PianoBlock`.
* `tools/deploy/test_instrument_models.py` re-derives the numbers and compares them with the
  values recorded in the Java class, so a shifted model cannot keep an stale hitbox.

Run `tools/python` (or the project venv) with no arguments to print the current table.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "src/main/resources/assets/pastoral_home/models/block"

PIANO_LAYERS = 2
PIANO_COLUMNS = 3
#: The exporter keeps every cell inside one block, so collision never needs cross-cell boxes.
CLIP = {0: (0.0, 16.0), 1: (0.0, 16.0), 2: (0.0, 16.0)}


def _deploy_collision():
    sys.path.insert(0, str(ROOT / "tools/collision"))
    from run import deploy_collision

    return deploy_collision


def cell_model(layer: int, column: int) -> Path:
    return MODELS / f"piano_l{layer}_c{column}.json"


def boxes(layer: int, column: int):
    """Return the voxelised boxes for one cell as 6-tuples in block pixels."""
    deploy_collision = _deploy_collision()
    result = deploy_collision(
        str(cell_model(layer, column)),
        res=8,
        allow_exposure=True,
        include_rotated=True,
        single_block=True,
        clip_bounds=CLIP,
    )
    return [tuple(round(value, 5) for value in box) for box in result["boxes"]]


def table():
    return {(layer, column): boxes(layer, column)
            for layer in range(PIANO_LAYERS) for column in range(PIANO_COLUMNS)}


def java_source() -> str:
    lines = []
    for (layer, column), cell in table().items():
        joined = ", ".join(
            "box(" + ", ".join(f"{value:g}" for value in box) + ")" for box in cell
        )
        lines.append(f"        SHAPES[{layer}][{column}] = Shapes.or({joined});")
    return "\n".join(lines)


if __name__ == "__main__":
    print(java_source())
