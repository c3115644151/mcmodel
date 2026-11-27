#!/usr/bin/env python3
"""Build the seamless table multipart models from the artist's modified bbmodel export.

Source: tools/deploy/model_sources/furniture/seamless_table_modified.bbmodel, imported to a single
block-model JSON with one shared 64x64 atlas (15 elements):

    0..3   four corner legs (NE, SE, NW, SW) -- unchanged from the collision boxes
    4,5    north crossed braces (rot z -45/+45)
    6,7    south crossed braces
    8,9    west crossed braces  (rot x +/-45)
    10,11  east crossed braces
    12     left tabletop strip  (x 0..4)   -> west edge
    13     right tabletop strip (x 12..16) -> east edge
    14     full tabletop        (x 0..16)  -> always visible base

Blockstate multipart mapping (each apply key matches a table_*.json):
    base            : full tabletop, always drawn
    leg_{ne,se,nw,sw}: only when that corner edge pair is exposed
    edge_west       : left tabletop strip + west braces   (when west=false)
    edge_east       : right tabletop strip + east braces  (when east=false)
    edge_north      : north braces                        (when north=false)
    edge_south      : south braces                        (when south=false)

The left/right strips are lifted by a hair so they deterministically own the top surface over the
full slab instead of z-fighting, exactly as the old flat edge decals did.
"""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "src/main/resources/assets/pastoral_home/models/block"

LEGS = {"ne": 0, "se": 1, "nw": 2, "sw": 3}
FULL_TOP = 14
EDGE_PARTS = {
    "west":  {"strips": [12], "braces": [8, 9]},
    "east":  {"strips": [13], "braces": [10, 11]},
    "north": {"strips": [],   "braces": [4, 5]},
    "south": {"strips": [],   "braces": [6, 7]},
}
LIFT = 0.005
TEX = "pastoral_home:block/table_tex0"


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def retint(element: dict) -> dict:
    out = copy.deepcopy(element)
    for face in out.get("faces", {}).values():
        face["texture"] = "#bb_texture_0"
    return out


def lifted(element: dict, dy: float) -> dict:
    out = copy.deepcopy(element)
    out["from"][1] = round(out["from"][1] + dy, 6)
    out["to"][1] = round(out["to"][1] + dy, 6)
    return out


def shell(source: dict, elements: list, particle: str) -> dict:
    model = copy.deepcopy(source)
    model["textures"] = {"bb_texture_0": TEX, "particle": particle}
    model["elements"] = elements
    model.pop("groups", None)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Imported full table model JSON (15 elements)")
    parser.add_argument("output_dir", type=Path, help="Destination for table_*.json models")
    args = parser.parse_args()

    source = json.loads(args.model.read_text(encoding="utf-8"))
    elements = source.get("elements")
    if not isinstance(elements, list) or len(elements) != 15:
        raise SystemExit(f"expected 15 table elements, got {len(elements) if elements else 0}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Always-visible full tabletop.
    base = shell(source, [retint(elements[FULL_TOP])], "pastoral_home:block/table_base_particle")
    write(args.output_dir / "table_base.json", base)

    for name, idx in LEGS.items():
        write(args.output_dir / f"table_leg_{name}.json",
              shell(source, [retint(elements[idx])], f"pastoral_home:block/table_leg_{name}_particle"))

    for edge, parts in EDGE_PARTS.items():
        group = [lifted(retint(elements[i]), LIFT) for i in parts["strips"]]
        group += [retint(elements[i]) for i in parts["braces"]]
        write(args.output_dir / f"table_edge_{edge}.json",
              shell(source, group, f"pastoral_home:block/table_edge_{edge}_particle"))

    # Inventory / legacy full model: everything drawn, strips lifted to avoid z-fighting.
    item_elements = [retint(elements[FULL_TOP])]
    item_elements += [lifted(retint(elements[i]), LIFT) for i in [12, 13]]
    item_elements += [retint(elements[i]) for i in [0, 1, 2, 3]]
    item_elements += [retint(elements[i]) for e in EDGE_PARTS.values() for i in e["braces"]]
    write(args.output_dir / "table_item.json",
          shell(source, item_elements, "pastoral_home:block/table_item_particle"))
    write(args.output_dir / "table.json",
          shell(source, item_elements, "pastoral_home:block/table_particle"))

    print("Built tabletop, 4 legs, 4 edge groups (strip + crossed braces), item and legacy models.")


if __name__ == "__main__":
    main()
