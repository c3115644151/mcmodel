#!/usr/bin/env python3
"""Import and split both wardrobe poses into a 2-column by 3-row structure."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_item_model import block_item_model  # noqa: E402
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE_DIR = ROOT / "tools/deploy/model_sources/wardrobe"
BUILD_DIR = ROOT / "build/requested_models/wardrobe"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
STATES = (("closed", "wardrobe_closed.bbmodel"), ("open", "wardrobe_open.bbmodel"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def translate_world(model: dict) -> dict:
    result = copy.deepcopy(model)
    for element in result.get("elements", []):
        for point in ("from", "to"):
            element[point][0] = float(element[point][0]) + 8.0
            element[point][1] = float(element[point][1]) + 16.0
        if "origin" in element:
            element["origin"][0] = float(element["origin"][0]) + 8.0
            element["origin"][1] = float(element["origin"][1]) + 16.0
        rotation = element.get("rotation")
        if rotation and rotation.get("origin"):
            rotation["origin"][0] = float(rotation["origin"][0]) + 8.0
            rotation["origin"][1] = float(rotation["origin"][1]) + 16.0
    return result


def split_model(model: dict):
    cells = {(layer, column): [] for layer in range(3) for column in range(2)}
    manifest = {(layer, column): [] for layer in range(3) for column in range(2)}
    for source_index, source in enumerate(model.get("elements", [])):
        x0, x1 = sorted((float(source["from"][0]), float(source["to"][0])))
        y0, y1 = sorted((float(source["from"][1]), float(source["to"][1])))
        column = max(0, min(1, int(((x0 + x1) * 0.5) // 16.0)))
        layer = max(0, min(2, int(((y0 + y1) * 0.5) // 16.0)))
        fragment = copy.deepcopy(source)
        for point in ("from", "to"):
            fragment[point][0] = round(float(fragment[point][0]) - 16.0 * column, 6)
            fragment[point][1] = round(float(fragment[point][1]) - 16.0 * layer, 6)
        if "origin" in fragment:
            fragment["origin"][0] = round(float(fragment["origin"][0]) - 16.0 * column, 6)
            fragment["origin"][1] = round(float(fragment["origin"][1]) - 16.0 * layer, 6)
        rotation = fragment.get("rotation")
        if rotation and rotation.get("origin"):
            rotation["origin"][0] = round(float(rotation["origin"][0]) - 16.0 * column, 6)
            rotation["origin"][1] = round(float(rotation["origin"][1]) - 16.0 * layer, 6)
        local_values = [float(value) for point in ("from", "to") for value in fragment[point]]
        if any(value < -16.0001 or value > 32.0001 for value in local_values):
            raise ValueError(f"Wardrobe element {source_index} cannot fit a cell-local model: {local_values}")
        fragment["_source_index"] = source_index
        cells[layer, column].append(fragment)
        manifest[layer, column].append(source_index)
    # Some source cubes span adjacent cells while being owned by the cell
    # containing their center. Empty owner cells still need an explicit model
    # file, but must not fail import or disappear from the six-cell state map.
    return cells, manifest


def blockstates() -> dict:
    parts = []
    for facing, rotation in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for opened in (False, True):
            pose = "open" if opened else "closed"
            for layer in range(3):
                for column in range(2):
                    apply = {"model": f"pastoral_home:block/wardrobe_{pose}_l{layer}_c{column}"}
                    if rotation:
                        apply["y"] = rotation
                    parts.append({"when": {
                        "facing": facing, "open": str(opened).lower(),
                        "layer": str(layer), "column": str(column),
                    }, "apply": apply})
    return {"multipart": parts}


def item_definition() -> dict:
    model = "pastoral_home:block/wardrobe_item"
    return {"model": {
        "type": "minecraft:select",
        "property": "minecraft:display_context",
        "cases": [{"when": "gui", "model": {"type": "minecraft:model", "model": model}}],
        "fallback": {"type": "minecraft:model", "model": model},
    }}


def update_generated_support_data() -> None:
    generated = ROOT / "src/generated/resources"
    for locale, display_name in (("en_us", "Wardrobe"), ("zh_cn", "衣橱")):
        path = generated / f"assets/pastoral_home/lang/{locale}.json"
        document = load(path)
        document["block.pastoral_home.wardrobe"] = display_name
        document["container.pastoral_home.wardrobe"] = display_name
        save(path, document)

    # The anchor-only loot table is generated by ModBlockLootProvider; a second copy here would be
    # one more place to forget when the anchor cell moves.

    axe_tag_path = generated / "data/minecraft/tags/block/mineable/axe.json"
    axe_tag = load(axe_tag_path) if axe_tag_path.is_file() else {"replace": False, "values": []}
    values = axe_tag.setdefault("values", [])
    if "pastoral_home:wardrobe" not in values:
        values.append("pastoral_home:wardrobe")
    save(axe_tag_path, axe_tag)


def main() -> None:
    model_dir = ASSETS / "models/block"
    split_manifest = {}
    for pose, source_name in STATES:
        source = SOURCE_DIR / source_name
        if not source.is_file():
            raise FileNotFoundError(f"Missing wardrobe source model: {source}")
        raw_path = BUILD_DIR / f"wardrobe_{pose}_raw.json"
        texture = ASSETS / f"textures/block/wardrobe_{pose}.png"
        subprocess.run([
            sys.executable, str(IMPORTER), str(source), "--model-out", str(raw_path),
            "--texture-out", str(texture), "--texture-name", f"wardrobe_{pose}",
        ], cwd=ROOT, check=True)
        raw = load(raw_path)
        if len(raw.get("elements", [])) != 12:
            raise ValueError(f"{pose} wardrobe expected 12 authored cubes")
        expected_particle = f"pastoral_home:block/wardrobe_{pose}_particle"
        if raw.get("textures", {}).get("particle") != expected_particle:
            raise ValueError(f"{pose} wardrobe import should use its dedicated face particle tile")
        placed = translate_world(raw)
        x_min = min(float(element[point][0]) for element in placed["elements"] for point in ("from", "to"))
        x_max = max(float(element[point][0]) for element in placed["elements"] for point in ("from", "to"))
        y_min = min(float(element[point][1]) for element in placed["elements"] for point in ("from", "to"))
        y_max = max(float(element[point][1]) for element in placed["elements"] for point in ("from", "to"))
        if abs(x_min) > 0.02 or abs(x_max - 32.0) > 0.02 or abs(y_min) > 0.02 or abs(y_max - 48.0) > 0.02:
            raise ValueError(f"Unexpected 2x3 wardrobe extents for {pose}: {(x_min, y_min, x_max, y_max)}")
        cells, manifest = split_model(placed)
        for (layer, column), elements in cells.items():
            model = copy.deepcopy(placed)
            model["elements"] = [{key: value for key, value in element.items() if key != "_source_index"}
                                 for element in elements]
            save(model_dir / f"wardrobe_{pose}_l{layer}_c{column}.json", model)
            split_manifest[f"{pose}:{layer}:{column}"] = manifest[layer, column]
        split_manifest[f"{pose}:raw"] = len(raw["elements"])
        if pose == "closed":
            # The closed pose is the neutral inventory/hand model. It is one
            # block, not the 48px assembly: an unnormalized cabinet fills the
            # whole screen in first person and every edge is clipped away.
            save(model_dir / "wardrobe_item.json", block_item_model(raw, label="wardrobe"))
        # Earlier builds emitted per-cell atlas crops. The shared source-face
        # tile above is now authoritative for every wardrobe piece.
        for stale in (ASSETS / "textures/block").glob(f"wardrobe_{pose}_l*_c*_particle.png"):
            stale.unlink(missing_ok=True)
        (ASSETS / "textures/block" / "wardrobe_item_particle.png").unlink(missing_ok=True)
    save(ASSETS / "blockstates/wardrobe.json", blockstates())
    save(ASSETS / "items/wardrobe.json", item_definition())
    save(BUILD_DIR / "wardrobe_split_manifest.json", split_manifest)
    update_generated_support_data()
    print("Prepared wardrobe closed/open poses as six cell-owned models each.")


if __name__ == "__main__":
    main()
