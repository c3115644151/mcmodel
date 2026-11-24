#!/usr/bin/env python3
"""Structural/UV regression checks for the grouped shallow-bridge assets."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_opaque_uv(image: Image.Image, uv: list[float], label: str) -> None:
    x0, y0, x1, y1 = uv
    px0, px1 = sorted((round(x0 * image.width / 16), round(x1 * image.width / 16)))
    py0, py1 = sorted((round(y0 * image.height / 16), round(y1 * image.height / 16)))
    if px0 == px1 or py0 == py1:
        raise AssertionError(f"{label}: degenerate UV rectangle {uv}")
    for y in range(py0, py1):
        for x in range(px0, px1):
            if image.getpixel((x, y))[3] == 0:
                raise AssertionError(f"{label}: fully transparent pixel at ({x},{y})")


def main() -> None:
    model_source = read_json(ASSETS / "model_sources/bridge_deck_mesh_source.json")
    parts = read_json(ASSETS / "model_sources/bridge_deck_parts.json")["lanes"]
    texture = Image.open(ASSETS / "textures/block/bridge_deck.png").convert("RGBA")
    if len(model_source["elements"]) != 15 or len(parts) != 3:
        raise AssertionError("Expected the 15-cube, 3-lane Blockbench export")

    for lane_data in parts:
        lane = lane_data["lane"]
        base = model_source["elements"][lane_data["base"]]
        z_width = base["to"][2] - base["from"][2]
        expected = (5, 6, 5)[lane]
        if z_width != expected:
            raise AssertionError(f"lane {lane}: expected width {expected}px, got {z_width}")
        for side, expected_x, cap in (
            ("west", (-5, 0), "west"),
            ("east", (16, 21), "east"),
        ):
            connector = model_source["elements"][lane_data["connectors"][side]]
            bounds = (connector["from"][0], connector["to"][0])
            if bounds != expected_x:
                raise AssertionError(f"lane {lane} {side}: connector must span 5px, got {bounds}")
            if cap not in connector["faces"]:
                raise AssertionError(f"lane {lane} {side}: outer cap face {cap!r} is missing")
            if len(connector["faces"]) != 6:
                raise AssertionError(f"lane {lane} {side}: connector cube must retain all six faces")
            for face_name, face in connector["faces"].items():
                assert_opaque_uv(texture, face["uv"], f"lane {lane} {side} {face_name}")

    icon = read_json(ASSETS / "models/item_icons/bridge_deck/variant_0.json")
    elements = icon["elements"]
    if len(elements) != 3:
        raise AssertionError(f"The item icon must show one slat plus two edges, got {len(elements)} cubes")
    bounds = sorted((e["from"][0], e["to"][0]) for e in elements)
    if bounds != [(0, 3), (3, 13), (13, 16)]:
        raise AssertionError(f"Center slat icon has overlapping or missing edge sections: {bounds}")
    if any(e["from"][1] < 0 or e["to"][1] > 3 for e in elements):
        raise AssertionError("The item icon base must be raised to the block floor and remain 3px thick")

    post = read_json(ASSETS / "models/block/bridge_post.json")
    collar = read_json(ASSETS / "models/block/bridge_post_collar.json")
    if len(post["elements"]) != 1 or len(collar["elements"]) != 1:
        raise AssertionError("The placed post must be bare; its rope collar is rendered separately")

    for locale in ("en_us", "zh_cn"):
        translations = read_json(ROOT / f"src/generated/resources/assets/pastoral_home/lang/{locale}.json")
        for key in ("block.pastoral_home.bridge_deck", "item.pastoral_home.bridge_deck"):
            if key not in translations:
                raise AssertionError(f"{locale}: missing display name {key}")
    print("Shallow bridge assets pass: lane geometry, connector caps/UVs, single-slat icon, bare post/collar split, and names.")


if __name__ == "__main__":
    main()
