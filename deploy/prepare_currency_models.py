#!/usr/bin/env python3
"""Prepare native 2D coin icons and progressive variants of the authored 3D coin-pile templates."""
from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from pathlib import Path
import shutil

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/currency"
WORK = ROOT / "build/requested_models/currency"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
JAVA_OUT = ROOT / "src/main/java/com/pastoralhome/block/CoinPileLayoutTemplates.java"
MESH_JAVA_OUT = ROOT / "src/main/java/com/pastoralhome/client/CoinPileMeshData.java"
KINDS = ("gold", "silver", "copper")
POUCHES = {"gold": "bag_gold", "silver": "bag_silver", "copper": "bag_copper"}
COIN_SOURCES = {"gold": "stack_gold_b", "silver": "stack_silver_b", "copper": "stack_copper_a"}
LAYOUTS = (
    "stack_gold_a", "stack_gold_b", "stack_silver_a", "stack_silver_b",
    "stack_copper_a", "stack_copper_b", "mixed_gold_silver", "mixed_silver_copper",
)
SHAPE_SOURCES = {
    "a": {"gold": "stack_gold_a", "silver": "stack_silver_a", "copper": "stack_copper_b"},
    "b": {"gold": "stack_gold_b", "silver": "stack_silver_b", "copper": "stack_copper_a"},
}
STYLE_SHAPES = {
    "stack_gold_a": "a", "stack_gold_b": "b",
    "stack_silver_a": "a", "stack_silver_b": "b",
    "stack_copper_a": "b", "stack_copper_b": "a",
    "mixed_gold_silver": "a", "mixed_silver_copper": "b",
}
COMPOSITIONS = {
    "gold": {"gold": 1.0},
    "silver": {"silver": 1.0},
    "copper": {"copper": 1.0},
    "gold_silver": {"gold": 0.5, "silver": 0.5},
    "gold_copper": {"gold": 0.5, "copper": 0.5},
    "silver_copper": {"silver": 0.5, "copper": 0.5},
    "all_three": {"gold": 1 / 3, "silver": 1 / 3, "copper": 1 / 3},
}
COMPOSITION_NAMES = tuple(COMPOSITIONS)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_model(name: str, texture_id: str, texture_path: Path | None, separate_textures: bool = False):
    source = SOURCE / f"{name}.bbmodel"
    raw_path = WORK / f"{name}.json"
    output_texture = texture_path or (WORK / f"{name}.png")
    command = [
        sys.executable, str(IMPORTER), str(source), "--model-out", str(raw_path),
        "--texture-out", str(output_texture), "--texture-name", texture_id,
    ]
    if separate_textures:
        command.extend(["--texture-dir", str(WORK / f"{name}_textures"), "--texture-prefix", texture_id])
    subprocess.run(command, cwd=ROOT, check=True)
    return read(raw_path)


def translated_element(element: dict, dx: float, dy: float, dz: float) -> dict:
    item = copy.deepcopy(element)
    for point in ("from", "to"):
        item[point] = [round(float(item[point][0]) + dx, 6),
                       round(float(item[point][1]) + dy, 6),
                       round(float(item[point][2]) + dz, 6)]
    if "origin" in item:
        item["origin"] = [round(float(item["origin"][0]) + dx, 6),
                          round(float(item["origin"][1]) + dy, 6),
                          round(float(item["origin"][2]) + dz, 6)]
    if item.get("rotation", {}).get("origin"):
        item["rotation"]["origin"] = [round(float(item["rotation"]["origin"][0]) + dx, 6),
                                       round(float(item["rotation"]["origin"][1]) + dy, 6),
                                       round(float(item["rotation"]["origin"][2]) + dz, 6)]
    return item


def coin_mesh_element(raw: dict, name: str) -> dict:
    candidates = []
    for index, element in enumerate(raw.get("elements", [])):
        size = [abs(float(element["to"][axis]) - float(element["from"][axis])) for axis in range(3)]
        x, y, z = size
        if y <= 1.05 and 2.5 <= x <= 4.5 and 2.5 <= z <= 4.5 and abs(x - z) <= 0.25:
            score = (0 if not element.get("rotation") else 1, abs(x - 3.0) + abs(z - 3.0), index)
            candidates.append((score, index, element))
    if not candidates:
        raise ValueError(f"No isolated flat coin cube found in {name}")
    _, source_index, element = min(candidates)
    center_x = (float(element["from"][0]) + float(element["to"][0])) * 0.5
    center_z = (float(element["from"][2]) + float(element["to"][2])) * 0.5
    if element.get("rotation"):
        raise ValueError(f"Selected single coin in {name} must be an axis-aligned source cube")
    item_element = translated_element(element, 8.0 - center_x, 0.0, 8.0 - center_z)
    return item_element, source_index


def write_coin_mesh_java(mesh_data: dict[str, tuple[dict, tuple[int, int]]]):
    rows = []
    for kind in KINDS:
        element, texture_size = mesh_data[kind]
        faces = element.get("faces", {})
        face_rows = []
        for face in ("north", "east", "south", "west", "up", "down"):
            uv = faces.get(face, {}).get("uv")
            if uv is None or len(uv) != 4:
                raise ValueError(f"Single-coin mesh {kind} is missing {face} UVs")
            face_rows.append("{" + ", ".join(f"{float(value) / texture_size[axis % 2]:.6f}F"
                                                   for axis, value in enumerate(uv)) + "}")
        from_values = ", ".join(f"{float(value):.6f}F" for value in element["from"])
        to_values = ", ".join(f"{float(value):.6f}F" for value in element["to"])
        rows.append("        new CoinMesh(new float[]{" + from_values + "}, new float[]{" + to_values
                     + "}, new float[][]{" + ", ".join(face_rows) + "})")
    content = '''package com.pastoralhome.client;

/** Single-coin cuboids and per-face UVs extracted directly from the authored BBModels. */
public final class CoinPileMeshData {
    public record CoinMesh(float[] from, float[] to, float[][] faceUvs) {}

    // Face order: north, east, south, west, up, down. UV rectangles are normalized.
    public static final CoinMesh[] COINS = {
''' + ",\n".join(rows) + '''
    };

    private CoinPileMeshData() {}
}
'''
    MESH_JAVA_OUT.parent.mkdir(parents=True, exist_ok=True)
    MESH_JAVA_OUT.write_text(content, encoding="utf-8")


def column_candidates(model: dict):
    piles, loose = [], []
    for index, element in enumerate(model.get("elements", [])):
        dimensions = [abs(float(element["to"][axis]) - float(element["from"][axis])) for axis in range(3)]
        x, y, z = dimensions
        center = [(float(element["from"][axis]) + float(element["to"][axis])) * 0.5 for axis in range(3)]
        point = [(center[0] - 8.0) / 16.0, (center[2] - 8.0) / 16.0]
        if y >= 4.0 and 2.5 <= x <= 5.0 and 2.5 <= z <= 5.0:
            piles.append((index, point, max(7, min(10, round(y)))))
        elif min(dimensions) <= 1.1 and 2.5 <= max(dimensions) <= 4.5:
            loose.append((index, point, 7))
    authored = piles + loose
    if len(authored) < 8:
        raise ValueError(f"Expected at least eight pile/coin parts in source with {len(model.get('elements', []))} cubes")
    # Quantize artist part centers into a collision-safe 3x3 layout. Static art
    # deliberately overlaps some faces; dynamic coin columns must have room to grow.
    grid = [[x, z] for x in (-0.28125, 0.0, 0.28125) for z in (-0.28125, 0.0, 0.28125)]
    available = list(grid)
    positions, capacities = [], []
    for _, point, capacity in authored[:9]:
        nearest = min(available, key=lambda candidate: math.dist(point, candidate))
        positions.append(nearest)
        capacities.append(int(capacity))
        available.remove(nearest)
    for point in available:
        if len(positions) >= 9:
            break
        positions.append(point)
        capacities.append(7)
    if len({tuple(point) for point in positions}) != 9 or sum(capacities) < 64:
        raise ValueError("Currency layout quantization produced duplicate columns")
    return positions, capacities


def java_templates(templates):
    rows, capacity_rows = [], []
    for template, capacities in templates:
        points = ", ".join("{" + f"{x:.5f}f, {z:.5f}f" + "}" for x, z in template)
        rows.append("        {" + points + "}")
        capacity_rows.append("        {" + ", ".join(str(value) for value in capacities) + "}")
    source = """package com.pastoralhome.block;

/** Generated from the eight authored currency-pile meshes; coordinates are block-center offsets. */
public final class CoinPileLayoutTemplates {
    public static final float[][][] POSITIONS = {
""" + ",\n".join(rows) + "\n    };\n\n    public static final int[][] CAPACITIES = {\n" + ",\n".join(capacity_rows) + "\n    };\n\n    private CoinPileLayoutTemplates() {}\n}\n"
    JAVA_OUT.parent.mkdir(parents=True, exist_ok=True)
    JAVA_OUT.write_text(source, encoding="utf-8")


def write_blockstate():
    entries = []
    for persisted_style, layout in STYLE_SHAPES.items():
        for composition in COMPOSITIONS:
            for stage in range(17):
                entries.append({
                    "when": {"packed": "false", "style": persisted_style,
                             "composition": composition, "stage": str(stage)},
                    "apply": {"model": f"pastoral_home:block/coin_pile/{layout}_{composition}_stage_{stage}"},
                })
    for facing, y_rotation in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for kind in KINDS:
            apply = {"model": f"pastoral_home:block/coin_pouch_{kind}"}
            if y_rotation:
                apply["y"] = y_rotation
            entries.append({"when": {"packed": "true", "pouch": kind, "facing": facing}, "apply": apply})
    return {"multipart": entries}


def progressive_elements(elements: list[dict], stage: int, total_stages: int = 16) -> list[dict]:
    if stage <= 0:
        return []
    ordered = sorted(enumerate(elements), key=lambda indexed: (
        max(0.0, float(indexed[1]["to"][1]) - float(indexed[1]["from"][1])),
        sum(abs(float(indexed[1]["to"][axis]) - float(indexed[1]["from"][axis])) for axis in range(3)),
    ))
    heights = [abs(float(element["to"][1]) - float(element["from"][1])) for _, element in ordered]
    target_height = sum(heights) * stage / total_stages
    remaining = target_height
    result: list[dict] = []
    for (source_index, source), height in zip(ordered, heights):
        if remaining <= 1e-5:
            break
        used = min(height, remaining)
        if used <= 1e-5:
            continue
        element = copy.deepcopy(source)
        element["_source_index"] = source_index
        if used < height - 1e-5:
            if element.get("rotation"):
                continue
            y0, y1 = float(element["from"][1]), float(element["to"][1])
            element["to"][1] = round(y0 + used if y1 >= y0 else y0 - used, 6)
            fraction = used / height
            for face_name in ("north", "east", "south", "west"):
                face = element.get("faces", {}).get(face_name)
                if not face or len(face.get("uv", [])) != 4:
                    continue
                u0, v0, u1, v1 = map(float, face["uv"])
                if v1 >= v0:
                    v0 = v1 - (v1 - v0) * fraction
                else:
                    v1 = v0 - (v0 - v1) * fraction
                face["uv"] = [round(u0, 6), round(v0, 6), round(u1, 6), round(v1, 6)]
        result.append(element)
        remaining -= used
    return result


def geometry_signature(model: dict):
    return [
        (element["from"], element["to"], element.get("rotation"), {
            name: {key: face[key] for key in ("uv", "rotation") if key in face}
            for name, face in element.get("faces", {}).items()
        })
        for element in model["elements"]
    ]


def copy_model_textures(name: str, model: dict, texture_dir: Path):
    for texture_ref in model.get("textures", {}).values():
        if not texture_ref.startswith("pastoral_home:block/"):
            continue
        texture_name = texture_ref.split(":", 1)[1].split("/", 1)[1]
        target = texture_dir / f"{texture_name}.png"
        if target.exists():
            continue
        candidates = (WORK / f"{name}.png", WORK / f"{name}_textures" / f"{texture_name}.png")
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise FileNotFoundError(f"Missing authored texture {texture_name} for {name}")
        shutil.copy2(source, target)


def element_palette(model: dict, weights: dict[str, float]) -> list[str]:
    heights = [max(1.0, abs(float(element["to"][1]) - float(element["from"][1])))
               for element in model["elements"]]
    total = sum(heights)
    assigned = {kind: 0.0 for kind in KINDS}
    result = ["gold"] * len(heights)
    order = sorted(range(len(heights)), key=lambda i: (
        heights[i], sum(abs(float(model["elements"][i]["to"][axis]) - float(model["elements"][i]["from"][axis])) for axis in range(3)), i))
    for index in order:
        kind = max(weights, key=lambda candidate: weights[candidate] * total - assigned[candidate])
        result[index] = kind
        assigned[kind] += heights[index]
    return result


def update_language_and_loot():
    lang_path = ROOT / "src/generated/resources/assets/pastoral_home/lang"
    for locale, values in {
        "en_us": {"coin_gold": "Gold Coin", "coin_silver": "Silver Coin", "coin_copper": "Copper Coin", "coin_pile": "Coin Pile"},
        "zh_cn": {"coin_gold": "金币", "coin_silver": "银币", "coin_copper": "铜币", "coin_pile": "钱堆"},
    }.items():
        path = lang_path / f"{locale}.json"
        document = read(path)
        for key, value in values.items():
            document[f"item.pastoral_home.{key}" if key.startswith("coin_") and key != "coin_pile"
                     else f"block.pastoral_home.{key}"] = value
        document["container.pastoral_home.coin_pile"] = values["coin_pile"]
        save(path, document)

    save(ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/coin_pile.json", {
        "type": "minecraft:block", "pools": [],
        "random_sequence": "pastoral_home:blocks/coin_pile",
    })


def main():
    model_dir = ASSETS / "models/block"
    texture_dir = ASSETS / "textures/block"
    layouts = []
    # Public denomination icons are authored 2D sprites. World heaps use the
    # artists' complete 3D BBModel layouts as discrete growth stages.
    for kind, source_name in COIN_SOURCES.items():
        source_texture = SOURCE / f"coin_{kind}_2d.png"
        with Image.open(source_texture) as image:
            if image.size != (16, 16) or image.mode not in ("RGBA", "RGB"):
                raise ValueError(f"{source_texture.name} must be a 16x16 RGB/RGBA PNG, got {image.size} {image.mode}")
        shutil.copy2(source_texture, texture_dir / f"coin_{kind}.png")
        (ASSETS / "textures/item").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_texture, ASSETS / f"textures/item/coin_{kind}.png")
        save(ASSETS / f"models/item/coin_{kind}.json", {
            "parent": "minecraft:item/generated",
            "textures": {"layer0": f"pastoral_home:item/coin_{kind}"},
        })
        save(ASSETS / f"items/coin_{kind}.json", {
            "model": {"type": "minecraft:model", "model": f"pastoral_home:item/coin_{kind}"}
        })
        # Remove model-derived icon remnants from earlier iterations; the
        # public icon is now the authored 2D PNG through minecraft:item/generated.
        stale_block_icon = model_dir / f"coin_{kind}_icon.json"
        if stale_block_icon.exists():
            stale_block_icon.unlink()
        stale_proxy = ASSETS / f"models/item_icons/coin_{kind}/variant_0.json"
        if stale_proxy.exists():
            stale_proxy.unlink()
            try:
                stale_proxy.parent.rmdir()
            except OSError:
                pass

    for kind, source_name in POUCHES.items():
        raw = import_model(source_name, f"coin_pouch_{kind}", texture_dir / f"coin_pouch_{kind}.png")
        raw.setdefault("textures", {})["particle"] = f"pastoral_home:block/coin_pouch_{kind}"
        save(model_dir / f"coin_pouch_{kind}.json", raw)

    raw_layouts = {
        name: import_model(name, f"coin_{name}", None, separate_textures=True)
        for name in LAYOUTS
    }
    for name in {source for shape in SHAPE_SOURCES.values() for source in shape.values()}:
        copy_model_textures(name, raw_layouts[name], texture_dir)

    # A/B variants share geometry and UVs across denominations. Reuse one stable
    # shape and vary only its per-stack material palette as the coin contents mix.
    for style, sources in SHAPE_SOURCES.items():
        base = raw_layouts[sources["gold"]]
        signature = geometry_signature(base)
        for kind, source_name in sources.items():
            if geometry_signature(raw_layouts[source_name]) != signature:
                raise ValueError(f"{style} layout geometry/UVs diverged for denomination {kind}")

        texture_map = {f"coin_{kind}": raw_layouts[source_name]["textures"]["bb_texture_0"]
                       for kind, source_name in sources.items()}
        palette = {name: element_palette(base, weights) for name, weights in COMPOSITIONS.items()}
        stage_dir = model_dir / "coin_pile"
        stage_dir.mkdir(parents=True, exist_ok=True)
        for composition, weights in COMPOSITIONS.items():
            for stage in range(17):
                elements = progressive_elements(base["elements"], stage)
                for element in elements:
                    source_index = element.pop("_source_index")
                    denomination = palette[composition][source_index]
                    for face in element.get("faces", {}).values():
                        face["texture"] = f"#coin_{denomination}"
                model = {
                    "parent": "minecraft:block/block",
                    "textures": {**texture_map, "particle": texture_map["coin_" + max(weights, key=weights.get)]},
                    "elements": elements,
                }
                save(stage_dir / f"{style}_{composition}_stage_{stage}.json", model)

    layouts = [{"layout": name, "cubes": len(raw_layouts[name]["elements"]), "stages": 17}
               for name in LAYOUTS]

    # Remove remnants from the discarded procedural coin-mesh renderer.
    (ROOT / "src/main/java/com/pastoralhome/block/CoinPileLayoutTemplates.java").unlink(missing_ok=True)
    (ROOT / "src/main/java/com/pastoralhome/client/CoinPileMeshData.java").unlink(missing_ok=True)
    (model_dir / "coin_pile_empty.json").unlink(missing_ok=True)
    for old_model in (model_dir / "coin_pile").glob("*_stage_*.json"):
        if old_model.stem.split("_stage_")[0] not in {
            f"{style}_{composition}" for style in SHAPE_SOURCES for composition in COMPOSITIONS
        }:
            old_model.unlink(missing_ok=True)
    for stale_texture in texture_dir.glob("coin_mixed_*_tex*.png"):
        stale_texture.unlink(missing_ok=True)
    for kind in KINDS:
        (ASSETS / f"textures/block/coin_{kind}_mesh.png").unlink(missing_ok=True)
        (ASSETS / f"items/coin_{kind}_render.json").unlink(missing_ok=True)
        (model_dir / f"coin_{kind}_render.json").unlink(missing_ok=True)
        (ASSETS / f"models/item/coin_{kind}_render.json").unlink(missing_ok=True)
    save(ASSETS / "blockstates/coin_pile.json", write_blockstate())
    save(WORK / "currency_asset_manifest.json", layouts)
    update_language_and_loot()
    print(f"Prepared three 2D coin icons, three pouches, and {2 * len(COMPOSITIONS) * 17} stable-geometry mixed-palette stages.")


if __name__ == "__main__":
    main()
