#!/usr/bin/env python3
"""Build the seamless table body and non-coplanar, top-only edge decals.

The four source edge cubes overlap the full tabletop cube and each other at
corners. Keep the tabletop as the only volume, then render each optional edge
as a very thin top-face layer. East/west layers are raised by a tiny extra
amount so they deterministically own the four corners instead of z-fighting.
"""
import argparse
import copy
import json
from pathlib import Path


EDGE_ELEMENTS = {
    "east": 5,
    "west": 6,
    "south": 7,
    "north": 8,
}


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Full exported seamless table model JSON")
    parser.add_argument("output_dir", type=Path, help="Destination for table_base/table_edge_*.json")
    args = parser.parse_args()

    source = json.loads(args.model.read_text(encoding="utf-8"))
    elements = source.get("elements")
    if not isinstance(elements, list) or len(elements) < 9:
        raise SystemExit("expected the table body (elements 0..4) and edge cubes (5..8)")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base = copy.deepcopy(source)
    base["elements"] = [copy.deepcopy(elements[0])]
    base.pop("groups", None)
    write(args.output_dir / "table_base.json", base)

    leg_names = {
        1: "table_leg_ne",
        2: "table_leg_se",
        3: "table_leg_nw",
        4: "table_leg_sw",
    }
    for index, name in leg_names.items():
        leg = copy.deepcopy(source)
        leg["elements"] = [copy.deepcopy(elements[index])]
        leg.pop("groups", None)
        write(args.output_dir / f"{name}.json", leg)

    item = copy.deepcopy(source)
    item["elements"] = copy.deepcopy(elements[:5])
    for direction, index in EDGE_ELEMENTS.items():
        original = copy.deepcopy(elements[index])
        if "up" not in original.get("faces", {}):
            raise SystemExit(f"edge element {index} ({direction}) has no top face")
        x0, _, z0 = original["from"]
        x1, _, z1 = original["to"]
        top_y = 16.01 if direction in ("north", "south") else 16.02
        decal = {
            "from": [x0, 16.0, z0],
            "to": [x1, top_y, z1],
            "faces": {"up": copy.deepcopy(original["faces"]["up"])},
        }
        model = copy.deepcopy(source)
        model["elements"] = [decal]
        model.pop("groups", None)
        write(args.output_dir / f"table_edge_{direction}.json", model)
        item["elements"].append(copy.deepcopy(decal))

    item.pop("groups", None)
    write(args.output_dir / "table_item.json", item)

    print("Built tabletop, 4 independent corner legs, 4 top-only edge layers, and a non-flickering item model.")


if __name__ == "__main__":
    main()
