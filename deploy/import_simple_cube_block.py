#!/usr/bin/env python3
"""Import a single full-cube Blockbench texture atlas as ordinary block assets.

The source must contain exactly one unrotated [0,0,0]..[16,16,16] cube. Its face
UVs are cropped into 16x16 face textures and emitted as a normal block/cube model,
blockstate, and 26.1 client item definition. Optional pillar mode adds vanilla
axis rotations without retaining Blockbench-only geometry metadata.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import resolve

FACES = ("north", "east", "south", "west", "up", "down")
SIDE_FACES = ("north", "east", "south", "west")
CAP_FACES = ("up", "down")


def import_simple_cube(source_path: Path, assets_root: Path, block_id: str,
                       pillar_axis: bool = False, namespace: str = "pastoral_home") -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    elements = source.get("elements", [])
    if len(elements) != 1:
        raise ValueError(f"expected exactly one cube, found {len(elements)}")
    element = elements[0]
    if element.get("from") != [0, 0, 0] or element.get("to") != [16, 16, 16]:
        raise ValueError("cube must span exactly [0,0,0] to [16,16,16]")
    if element.get("rotation"):
        raise ValueError("simple full-cube import does not support rotated elements")

    textures = source.get("textures", [])
    used_indices = set()
    for face in FACES:
        data = element.get("faces", {}).get(face)
        if not isinstance(data, dict) or "uv" not in data:
            raise ValueError(f"cube face {face!r} is missing a texture UV mapping")
        reference = data.get("texture")
        try:
            index = int(reference)
        except (TypeError, ValueError) as error:
            raise ValueError(f"face {face!r} texture ref must be a numeric source texture index") from error
        if index < 0 or index >= len(textures):
            raise ValueError(f"face {face!r} references missing texture index {index}")
        used_indices.add(index)
    if len(used_indices) != 1:
        raise ValueError(f"all six cube faces must use one source texture; found indices {sorted(used_indices)}")

    texture_index = next(iter(used_indices))
    embedded = textures[texture_index].get("source", "")
    if not embedded.startswith("data:image/") or "," not in embedded:
        raise ValueError(f"texture index {texture_index} is not embedded as a data URI")
    image = Image.open(__import__("io").BytesIO(base64.b64decode(embedded.split(",", 1)[1]))).convert("RGBA")

    crops: dict[str, Image.Image] = {}
    face_uvs: dict[str, list[float]] = {}
    face_hashes: dict[str, str] = {}
    for face in FACES:
        uv = element["faces"][face]["uv"]
        if len(uv) != 4:
            raise ValueError(f"face {face!r} UV must have four coordinates")
        u1, v1, u2, v2 = (float(value) for value in uv)
        left, right = sorted((u1, u2))
        top, bottom = sorted((v1, v2))
        if any(abs(value - round(value)) > 1e-6 for value in (left, top, right, bottom)):
            raise ValueError(f"face {face!r} has fractional UVs; refusing to resample a simple cube")
        if right - left != 16 or bottom - top != 16:
            raise ValueError(f"face {face!r} UV area must be 16x16, found {right-left:g}x{bottom-top:g}")
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise ValueError(f"face {face!r} UV {uv} lies outside {image.width}x{image.height} texture")
        crop = image.crop((int(left), int(top), int(right), int(bottom)))
        digest = hashlib.sha1(crop.tobytes()).hexdigest()[:10]
        crops.setdefault(digest, crop)
        face_hashes[face] = digest
        face_uvs[face] = [u1 - left, v1 - top, u2 - left, v2 - top]

    unique = set(face_hashes.values())
    slot_for_hash: dict[str, str] = {}
    if len(unique) == 1:
        slot_for_hash[next(iter(unique))] = "all"
    elif len(unique) == 2 and len({face_hashes[face] for face in SIDE_FACES}) == 1 \
            and len({face_hashes[face] for face in CAP_FACES}) == 1:
        slot_for_hash[face_hashes["north"]] = "side"
        slot_for_hash[face_hashes["up"]] = "end"
    else:
        for face in FACES:
            slot_for_hash.setdefault(face_hashes[face], face)

    texture_refs = {}
    for digest, slot in slot_for_hash.items():
        texture_name = f"{block_id}_{slot}"
        texture_path = assets_root / "textures/block" / f"{texture_name}.png"
        texture_path.parent.mkdir(parents=True, exist_ok=True)
        crops[digest].save(texture_path)
        texture_refs[slot] = f"{namespace}:block/{texture_name}"

    model_textures = {slot: value for slot, value in texture_refs.items()}
    model_textures["particle"] = texture_refs.get("side", texture_refs.get("all", next(iter(texture_refs.values()))))
    faces = {}
    for face in FACES:
        slot = slot_for_hash[face_hashes[face]]
        faces[face] = {"uv": face_uvs[face], "texture": f"#{slot}"}
    model = {
        "parent": "minecraft:block/block",
        "textures": model_textures,
        "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}],
    }
    model_path = assets_root / "models/block" / f"{block_id}.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    model_id = f"{namespace}:block/{block_id}"
    if pillar_axis:
        blockstate = {"variants": {
            "axis=x": {"model": model_id, "x": 90, "y": 90},
            "axis=y": {"model": model_id},
            "axis=z": {"model": model_id, "x": 90},
        }}
    else:
        blockstate = {"variants": {"": {"model": model_id}}}
    blockstate_path = assets_root / "blockstates" / f"{block_id}.json"
    blockstate_path.parent.mkdir(parents=True, exist_ok=True)
    blockstate_path.write_text(json.dumps(blockstate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    item_definition = {"model": {"type": "minecraft:model", "model": model_id}}
    item_path = assets_root / "items" / f"{block_id}.json"
    item_path.parent.mkdir(parents=True, exist_ok=True)
    item_path.write_text(json.dumps(item_definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "block": block_id,
        "texture_index": texture_index,
        "texture_size": [image.width, image.height],
        "face_texture_slots": {face: slot_for_hash[face_hashes[face]] for face in FACES},
        "texture_files": [path.name for path in sorted((assets_root / "textures/block").glob(f"{block_id}_*.png"))],
        "pillar_axis": pillar_axis,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("block_id")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pillar-axis", action="store_true", help="generate vanilla-style axis blockstates")
    parser.add_argument("--namespace", default=None)
    args = parser.parse_args()
    settings = resolve({"root": str(args.root.resolve())})
    namespace = args.namespace or settings.get("mod_id")
    if not namespace:
        parser.error("could not detect the target mod namespace")
    assets_root = args.root.resolve() / "src/main/resources/assets" / namespace
    result = import_simple_cube(args.source.resolve(), assets_root, args.block_id, args.pillar_axis, namespace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
