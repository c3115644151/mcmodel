#!/usr/bin/env python3
"""Print a compact, UTF-8 safe structure report for one or more Blockbench .bbmodel files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def walk(nodes, groups, elements, depth=0):
    for node in nodes or []:
        if isinstance(node, str):
            element = elements.get(node)
            if element:
                yield depth, "cube", element
            continue
        if not isinstance(node, dict):
            continue
        uuid = node.get("uuid")
        group = groups.get(uuid, node)
        name = group.get("name", node.get("name", "(unnamed)"))
        yield depth, "group", group
        yield from walk(node.get("children", []), groups, elements, depth + 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.files:
        data = json.loads(path.read_text(encoding="utf-8"))
        elements = {item.get("uuid"): item for item in data.get("elements", [])}
        groups = {item.get("uuid"): item for item in data.get("groups", []) or []}
        print(f"\n## {path.name}")
        print(f"format={data.get('meta', {}).get('model_format')} resolution={data.get('resolution')} "
              f"elements={len(elements)} textures={len(data.get('textures', []))}")
        print(f"project bounds (unrotated): {bounds(data.get('elements', []))}")
        for depth, kind, item in walk(data.get("outliner", []), groups, elements):
            pad = "  " * depth
            if kind == "group":
                print(f"{pad}[{item.get('name', '(unnamed)')}] origin={item.get('origin')} "
                      f"rotation={item.get('rotation')} visible={item.get('visibility', True)}")
            else:
                print(f"{pad}- {item.get('name', 'cube')} from={item.get('from')} to={item.get('to')} "
                      f"rotation={item.get('rotation')} faces={','.join(item.get('faces', {}).keys())}")
        # Older java_block exports can use a flat UUID outliner; include any cubes
        # that were not reached through a group node.
        listed = {item.get("uuid") for depth, kind, item in walk(data.get("outliner", []), groups, elements)
                  if kind == "cube"}
        for uuid, element in elements.items():
            if uuid not in listed:
                print(f"- {element.get('name', 'cube')} from={element.get('from')} to={element.get('to')} "
                      f"rotation={element.get('rotation')} faces={','.join(element.get('faces', {}).keys())}")


def bounds(elements):
    if not elements:
        return None
    low = [min(element["from"][axis] for element in elements) for axis in range(3)]
    high = [max(element["to"][axis] for element in elements) for axis in range(3)]
    return {"min": low, "max": high}


if __name__ == "__main__":
    main()
