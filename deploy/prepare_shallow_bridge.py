#!/usr/bin/env python3
"""Stage the artist's grouped bridge deck source for runtime assembly."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root
    source_path = root / "tools/deploy/model_sources/bridge_deck_full_source.json"
    parts_path = root / "tools/deploy/model_sources/bridge_deck_parts.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    parts = json.loads(parts_path.read_text(encoding="utf-8"))
    if len(source.get("elements", [])) != 15 or len(parts.get("lanes", [])) != 3:
        raise SystemExit("Expected the 15-cube, three-lane artist model")

    models = root / "src/main/resources/assets/pastoral_home/models/block"
    item_icons = root / "src/main/resources/assets/pastoral_home/models/item_icons/bridge_deck"
    model_sources = root / "src/main/resources/assets/pastoral_home/model_sources"
    states = root / "src/main/resources/assets/pastoral_home/blockstates"
    model_sources.mkdir(parents=True, exist_ok=True)
    (model_sources / "bridge_deck_mesh_source.json").write_text(
        json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (model_sources / "bridge_deck_parts.json").write_text(
        json.dumps(parts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # The item icon is the center slat only, with its two end-grain edge cubes.
    # These replace overlapping base ends; support connectors are not item art.
    inventory = copy.deepcopy(source)
    assembled = []
    lane = next(entry for entry in parts["lanes"] if entry["lane"] == 1)
    base = copy.deepcopy(source["elements"][lane["base"]])
    base["from"][0], base["to"][0] = 3, 13
    base["faces"].pop("west", None)
    base["faces"].pop("east", None)
    assembled.append(base)
    west_edge = copy.deepcopy(source["elements"][lane["edges"]["west"]])
    west_edge["faces"].pop("east", None)
    assembled.append(west_edge)
    east_edge = copy.deepcopy(source["elements"][lane["edges"]["east"]])
    east_edge["faces"].pop("west", None)
    assembled.append(east_edge)
    for element in assembled:
        element["from"][1] += 3.0
        element["to"][1] += 3.0
    inventory["elements"] = copy.deepcopy(assembled)
    display = {
        "gui": {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [0.625, 0.625, 0.625]},
        "ground": {"rotation": [0, 0, 0], "translation": [0, 3, 0], "scale": [0.25, 0.25, 0.25]},
        "fixed": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [0.5, 0.5, 0.5]},
        "thirdperson_righthand": {"rotation": [75, 45, 0], "translation": [0, 2.5, 0], "scale": [0.375, 0.375, 0.375]},
        "thirdperson_lefthand": {"rotation": [75, 225, 0], "translation": [0, 2.5, 0], "scale": [0.375, 0.375, 0.375]},
        "firstperson_righthand": {"rotation": [0, 45, 0], "translation": [0, 2, 0], "scale": [0.4, 0.4, 0.4]},
        "firstperson_lefthand": {"rotation": [0, 225, 0], "translation": [0, 2, 0], "scale": [0.4, 0.4, 0.4]},
    }
    inventory["display"] = display
    (models / "bridge_deck_inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    item_icons.mkdir(parents=True, exist_ok=True)
    icon = copy.deepcopy(inventory)
    icon["display"] = display
    (item_icons / "variant_0.json").write_text(
        json.dumps(icon, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    states.mkdir(parents=True, exist_ok=True)
    (states / "bridge_deck.json").write_text(
        json.dumps({"multipart": [{"apply": {"model": "pastoral_home:block/bridge_deck_inventory"}}]},
                   indent=2) + "\n", encoding="utf-8")

    # The post is bare by default. Its collar is a separate mesh used only by
    # the temporary anchor preview and by committed rope entities.
    post_source_path = root / "tools/deploy/model_sources/bridge_post_full_source.json"
    if post_source_path.exists():
        post_source = json.loads(post_source_path.read_text(encoding="utf-8"))
        bare_post = copy.deepcopy(post_source)
        bare_post["elements"] = [copy.deepcopy(post_source["elements"][0])]
        collar = copy.deepcopy(post_source)
        collar["elements"] = [copy.deepcopy(post_source["elements"][1])]
        collar.pop("display", None)
        (models / "bridge_post.json").write_text(
            json.dumps(bare_post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (models / "bridge_post_collar.json").write_text(
            json.dumps(collar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        post_icon_path = root / "src/main/resources/assets/pastoral_home/models/item_icons/bridge_post/variant_0.json"
        post_icon = json.loads(post_icon_path.read_text(encoding="utf-8"))
        post_icon["elements"] = [copy.deepcopy(post_source["elements"][0])]
        (post_icon_path.parent).mkdir(parents=True, exist_ok=True)
        post_icon_path.write_text(json.dumps(post_icon, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    stale_models = [
        "bridge_deck_base.json", "bridge_deck_lane_0.json", "bridge_deck_lane_1.json", "bridge_deck_lane_2.json",
        "bridge_deck_left_connector.json", "bridge_deck_right_connector.json",
        "bridge_deck_left_lane_0.json", "bridge_deck_left_lane_1.json", "bridge_deck_left_lane_2.json",
        "bridge_deck_right_lane_0.json", "bridge_deck_right_lane_1.json", "bridge_deck_right_lane_2.json",
    ]
    for name in stale_models:
        path = models / name
        if path.exists():
            path.unlink()
    stale_state = states / "bridge_deck_model.json"
    if stale_state.exists():
        stale_state.unlink()
    print("Staged the center lane icon with edges; post collars are reserved for rope previews/connections.")


if __name__ == "__main__":
    main()
