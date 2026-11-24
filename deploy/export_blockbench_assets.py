#!/usr/bin/env python3
"""Export the active BlockBench Java-block project with every referenced texture.

Example:
  python tools/deploy/export_blockbench_assets.py model.json textures/block \
      --texture 9:chandelier_metal --texture 14:chandelier
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tmp"))
from mcp_client import call_tool, init_session


def text_content(reply):
    return next((item.get("text", "") for item in reply.get("content", []) if item.get("type") == "text"), "")


def parse_mapping(values):
    mapping = {}
    for value in values:
        texture_id, separator, asset_name = value.partition(":")
        if not separator or not texture_id or not asset_name:
            raise ValueError(f"Invalid texture mapping {value!r}; expected ID:asset_name")
        mapping[texture_id] = asset_name
    return mapping


def export_texture(session, texture_id, output):
    reply = call_tool("get_texture", {"texture": texture_id, "format": "png"}, session=session)
    image = next((item for item in reply.get("content", []) if item.get("type") == "image" and item.get("data")), None)
    if image is None:
        raise RuntimeError(f"BlockBench did not return PNG data for texture {texture_id}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(image["data"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_output", type=Path)
    parser.add_argument("texture_directory", type=Path)
    parser.add_argument("--texture", action="append", default=[], metavar="ID:NAME",
                        help="Texture ID:asset name; with --source-bbmodel, ID is its zero-based texture index")
    parser.add_argument("--source-bbmodel", type=Path,
                        help="Original .bbmodel; restores per-face texture indices when MCP IDs collide")
    parser.add_argument("--mod-id", default="pastoral_home")
    parser.add_argument("--particle", default=None,
                        help="Particle texture resource; defaults to the first mapped Blockbench texture")
    args = parser.parse_args()
    mapping = parse_mapping(args.texture)
    if not mapping:
        parser.error("at least one --texture ID:NAME mapping is required")
    session = init_session()
    if not session:
        raise SystemExit("BlockBench MCP is not available at http://localhost:3000/bb-mcp")

    if args.source_bbmodel:
        info = json.loads(text_content(call_tool("get_project_info", {}, session=session)))
        active_path = info.get("project", {}).get("save_path")
        if not active_path or os.path.normcase(os.path.abspath(active_path)) != os.path.normcase(os.path.abspath(args.source_bbmodel)):
            raise SystemExit(f"Active BlockBench project does not match --source-bbmodel: {active_path or '(unsaved project)'}")

    listed = json.loads(text_content(call_tool("list_textures", {}, session=session)))
    by_uuid = {str(texture.get("uuid")): texture for texture in listed if texture.get("uuid")}
    available = {str(texture.get("id")) for texture in listed} | set(by_uuid)

    # The MCP server can return the same short texture ID for multiple Blockbench
    # textures. In that case the compiled Java model also collapses face references
    # to that ID. Use the source .bbmodel's per-face texture index and the MCP UUIDs
    # to reconstruct distinct references before writing the game assets.
    source = None
    texture_fetch_ids = dict(mapping)
    source_indices = {}
    if args.source_bbmodel:
        source = json.loads(args.source_bbmodel.read_text(encoding="utf-8"))
        source_textures = source.get("textures", [])
        source_indices = {int(key): asset for key, asset in mapping.items()}
        source_model_refs = set()
        for element in source.get("elements", []):
            for face in element.get("faces", {}).values():
                ref = face.get("texture") if isinstance(face, dict) else None
                if isinstance(ref, int):
                    source_model_refs.add(ref)
                elif isinstance(ref, str) and ref.isdigit():
                    source_model_refs.add(int(ref))
                elif isinstance(ref, str) and ref:
                    match = next((i for i, tex in enumerate(source_textures)
                                  if ref in (str(tex.get("uuid")), str(tex.get("id")), tex.get("name"))), None)
                    if match is not None:
                        source_model_refs.add(match)
        missing_indices = sorted(source_model_refs - set(source_indices))
        if missing_indices:
            raise SystemExit(f"Source model uses unmapped texture indices: {', '.join(map(str, missing_indices))}")
        if len(source.get("elements", [])) == 0:
            raise SystemExit("Source .bbmodel contains no elements")
        for index in source_indices:
            if index < 0 or index >= len(source_textures):
                raise SystemExit(f"Texture index {index} is outside the source texture list")
            texture = source_textures[index]
            uuid = str(texture.get("uuid", ""))
            if not uuid or uuid not in by_uuid:
                raise SystemExit(f"Source texture {index} has no matching active MCP UUID")
            texture_fetch_ids[str(index)] = uuid
    else:
        unknown = sorted(set(mapping) - available)
        if unknown:
            raise SystemExit(f"Texture IDs/UUIDs not present in active BlockBench project: {', '.join(unknown)}")

    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    call_tool("export_model", {"codec_id": "java_block", "path": str(args.model_output.resolve())}, session=session)
    model = json.loads(args.model_output.read_text(encoding="utf-8"))
    if source is not None:
        if len(model.get("elements", [])) != len(source.get("elements", [])):
            raise SystemExit("MCP export element order/count differs from source .bbmodel; refusing unsafe texture remap")
        for index, (source_element, model_element) in enumerate(zip(source["elements"], model["elements"])):
            source_faces = source_element.get("faces", {})
            for face_name, model_face in model_element.get("faces", {}).items():
                source_face = source_faces.get(face_name, {})
                ref = source_face.get("texture") if isinstance(source_face, dict) else None
                if ref is None:
                    continue
                if isinstance(ref, str) and not ref.isdigit():
                    match = next((i for i, tex in enumerate(source.get("textures", []))
                                  if ref in (str(tex.get("uuid")), str(tex.get("id")), tex.get("name"))), None)
                    if match is None:
                        raise SystemExit(f"Cannot resolve source texture on element {index}, face {face_name}")
                    ref = match
                ref = int(ref)
                if ref not in source_indices:
                    raise SystemExit(f"Missing --texture mapping for source texture {ref}")
                model_face["texture"] = f"#bb_texture_{ref}"

        # Blockbench may compile faces with a null per-face texture using the
        # element's/default material. Those faces are absent from the source
        # index remap above, and MCP exports them as #<runtime texture id>.
        # Resolve those remaining references through texture UUIDs rather than
        # guessing from short IDs (which can change between project sessions).
        source_uuid_to_index = {
            str(source.get("textures", [])[index].get("uuid")): index
            for index in source_indices
        }
        runtime_id_to_index = {
            str(texture.get("id")): source_uuid_to_index[str(texture.get("uuid"))]
            for texture in listed
            if texture.get("uuid") and str(texture.get("uuid")) in source_uuid_to_index
        }
        for element in model.get("elements", []):
            for face in element.get("faces", {}).values():
                reference = face.get("texture", "")
                if isinstance(reference, str) and reference.startswith("#"):
                    runtime_id = reference[1:]
                    if runtime_id in runtime_id_to_index:
                        face["texture"] = f"#bb_texture_{runtime_id_to_index[runtime_id]}"
                    elif runtime_id == "missing" and len(source_indices) == 1:
                        # Some Blockbench cubes have no explicit per-face texture
                        # but inherit the project's only/default texture. The Java
                        # codec serializes those faces as #missing; keep them on
                        # that sole material instead of aborting or dropping faces.
                        only_index = next(iter(source_indices))
                        face["texture"] = f"#bb_texture_{only_index}"
    referenced = {face["texture"][1:] for element in model.get("elements", []) for face in element.get("faces", {}).values()
                  if face.get("texture", "").startswith("#")}
    mapped_model_keys = ({f"bb_texture_{index}" for index in source_indices}
                         if source is not None else set(mapping))
    missing = sorted(referenced - mapped_model_keys)
    if missing:
        raise SystemExit(f"Model references unmapped texture IDs: {', '.join(missing)}")

    model.pop("texture_size", None)
    model.pop("format_version", None)
    model.pop("credit", None)
    model["parent"] = "minecraft:block/block"
    if source is not None:
        model["textures"] = {f"bb_texture_{index}": f"{args.mod_id}:block/{asset}"
                              for index, asset in source_indices.items()}
        primary_texture = model["textures"][f"bb_texture_{min(source_indices)}"]
    else:
        model["textures"] = {texture_id: f"{args.mod_id}:block/{asset}" for texture_id, asset in mapping.items()}
        primary_texture = next(iter(model["textures"].values()))
    model["textures"]["particle"] = args.particle or primary_texture
    display = model.setdefault("display", {})
    display.setdefault("ground", {"scale": [0.25, 0.25, 0.25]})
    args.model_output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for texture_id, asset_name in mapping.items():
        output = args.texture_directory / f"{asset_name}.png"
        export_texture(session, texture_fetch_ids[texture_id], output)
        print(f"Exported texture {texture_id} -> {output}")
    print(f"Exported model -> {args.model_output} ({len(model.get('elements', []))} elements)")


if __name__ == "__main__":
    main()
