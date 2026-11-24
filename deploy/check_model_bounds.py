#!/usr/bin/env python3
"""Fail the build when a shipped model cannot bake.

Minecraft 26.1 rejects any cuboid element whose coordinates leave [-16, 32]:
CuboidModelElement.getPosition throws "to specifier exceeds the allowed
boundaries", the model never reaches the model manager, and the item quietly
renders as the missing purple-black square instead of a stack trace.

Whole assemblies are published through block_item_model, which normalizes its
geometry into one block, but nothing stops a later edit from pointing an item
definition at an oversized model again. Every shipped model and every model an
item definition ends up drawing is checked here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models"
ITEMS = ASSETS / "items"

# The hard element bounds the vanilla cuboid deserializer enforces.
MODEL_LOW = -16.0
MODEL_HIGH = 32.0
# Only from/to go through the bounds-checked parser; getRotation reads its origin
# with a plain vector parse (javap on CuboidModelElement$Deserializer), so pivots
# legitimately sit outside the block, e.g. pastoral_home:block/arch elements[16].
POINT_KEYS = ("from", "to")


def model_id(path: Path) -> str:
    return "pastoral_home:" + path.relative_to(MODELS).with_suffix("").as_posix()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def model_index() -> dict[str, dict]:
    index = {}
    for path in sorted(MODELS.rglob("*.json")):
        index[model_id(path)] = load(path)
    return index


def oversized_points(model: dict) -> list[tuple[str, list[float]]]:
    """Every point of a model that the vanilla deserializer would reject."""
    problems = []
    for position, element in enumerate(model.get("elements") or []):
        for key in POINT_KEYS:
            point = element.get(key)
            if not isinstance(point, list) or len(point) != 3:
                continue
            values = [float(value) for value in point]
            if any(value < MODEL_LOW or value > MODEL_HIGH for value in values):
                problems.append((f"elements[{position}].{key}", values))
    return problems


def resolved_elements(index: dict[str, dict], identifier: str, depth: int = 8) -> list[dict]:
    """Collect the elements a model draws, following its parent chain."""
    seen = set()
    elements: list[dict] = []
    current: str | None = identifier
    while current and depth > 0 and current not in seen:
        seen.add(current)
        model = index.get(current)
        if model is None:
            break
        elements.extend(model.get("elements") or [])
        parent = model.get("parent")
        current = parent if isinstance(parent, str) else None
        depth -= 1
    return elements


def referenced_models(value, found: list[str]) -> list[str]:
    """Every model id an item definition asks the client to draw."""
    if isinstance(value, dict):
        kind = value.get("type")
        if kind == "minecraft:model" and isinstance(value.get("model"), str):
            found.append(value["model"])
        for nested in value.values():
            referenced_models(nested, found)
    elif isinstance(value, list):
        for nested in value:
            referenced_models(nested, found)
    return found


def scan() -> list[str]:
    index = model_index()
    problems = []
    for identifier, model in index.items():
        for where, values in oversized_points(model):
            problems.append(f"{identifier}: {where} = {values}")
    for path in sorted(ITEMS.rglob("*.json")):
        for identifier in referenced_models(load(path), []):
            if identifier not in index:
                continue
            for where, values in oversized_points({"elements": resolved_elements(index, identifier)}):
                problems.append(f"{path.relative_to(ASSETS).as_posix()} draws {identifier}: {where} = {values}")
    return problems


def main() -> int:
    problems = scan()
    if problems:
        print(f"{len(problems)} model point(s) leave the [{MODEL_LOW:g}, {MODEL_HIGH:g}] bounds;")
        print("the client refuses the whole model and draws the missing purple-black square:")
        for problem in problems:
            print("  " + problem)
        return 1
    print(f"Checked {len(model_index())} models: every element point stays within "
          f"[{MODEL_LOW:g}, {MODEL_HIGH:g}].")
    return 0


if __name__ == "__main__":
    sys.exit(main())
