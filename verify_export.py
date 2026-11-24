#!/usr/bin/env python3
"""Verify a Blockbench JSON model export and its PNG texture."""
import argparse
import json
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("texture", type=Path)
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    if not isinstance(model.get("elements"), list) or not model["elements"]:
        raise SystemExit("FAIL: JSON has no elements")
    if not model.get("textures"):
        raise SystemExit("FAIL: JSON has no textures")
    for element in model["elements"]:
        for face in element.get("faces", {}).values():
            uv = face.get("uv")
            if uv and any(value < 0 or value > 16 for value in uv):
                raise SystemExit(f"FAIL: UV outside 0..16: {uv}")
    with Image.open(args.texture) as image:
        if image.format != "PNG":
            raise SystemExit(f"FAIL: texture format is {image.format}, not PNG")
        print(f"PASS: {args.model} + {args.texture}")
        print(f"  elements: {len(model['elements'])}")
        print(f"  texture: {image.size[0]}x{image.size[1]} {image.mode}")


if __name__ == "__main__":
    main()
