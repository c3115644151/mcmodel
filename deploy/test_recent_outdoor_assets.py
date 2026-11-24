#!/usr/bin/env python3
"""Asset-pipeline checks for the seven current outdoor model imports."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
ITEMS = ("greenery_2", "floor_lamp", "sunflower_planter", "one_cell_canopy", "globe", "telescope", "a_frame_ladder")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    for item in ITEMS:
        model = read(ASSETS / f"models/block/{item}.json")
        if not model.get("elements"):
            raise AssertionError(f"{item}: world model has no elements")
        for element in model["elements"]:
            for point_name in ("from", "to"):
                point = element[point_name]
                if any(value < -16 or value > 32 for value in point):
                    raise AssertionError(f"{item}: {point_name} exceeds Minecraft model bounds: {point}")
        for key, texture in model.get("textures", {}).items():
            if key == "particle" or not texture.startswith("pastoral_home:block/"):
                continue
            path = ASSETS / f"textures/block/{texture.split('/')[-1]}.png"
            if not path.is_file():
                raise AssertionError(f"{item}: unresolved {key} -> {path.name}")
        item_definition = read(ASSETS / f"items/{item}.json")
        if item_definition.get("model", {}).get("property") != "minecraft:display_context":
            raise AssertionError(f"{item}: normalized GUI model selector is missing")
        proxy = ASSETS / f"models/item_icons/{item}/variant_0.json"
        proxy_model = read(proxy)
        if not proxy_model.get("elements"):
            raise AssertionError(f"{item}: GUI proxy has no visible geometry")
        source_model = read(ROOT / f"tools/deploy/model_sources/recent_outdoor/{item}.json")
        source_gui = source_model.get("display", {}).get("gui")
        proxy_gui = proxy_model.get("display", {}).get("gui", {})
        # Vanilla's block camera is yaw 225: the calibration hotbar showed the furnace
        # mouth, the carved-pumpkin face and the observer front all facing the viewer at
        # 225, while 45 showed their backs. Every proxy inherits that camera unchanged.
        if proxy_gui.get("rotation") != [30.0, 225.0, 0.0]:
            raise AssertionError(f"{item}: GUI icon should use vanilla's block camera, yaw 225")
        state_file = read(ASSETS / f"blockstates/{item}.json")
        if item == "one_cell_canopy":
            multipart = state_file.get("multipart", [])
            models = {part["apply"]["model"].split(":")[-1] for part in multipart}
            if models != {"block/one_cell_canopy_core", "block/one_cell_canopy_side_left",
                          "block/one_cell_canopy_side_right"}:
                raise AssertionError(f"canopy side skins are not split into core and two removable edges: {models}")
            if len(multipart) != 12:
                raise AssertionError("canopy must render a core and two conditional side skins for each facing")
            left_rows = [part for part in multipart if part["apply"]["model"].endswith("one_cell_canopy_side_left")]
            right_rows = [part for part in multipart if part["apply"]["model"].endswith("one_cell_canopy_side_right")]
            if len(left_rows) != 4 or len(right_rows) != 4 \
                    or any(part.get("when", {}).get("connect_left") is not False for part in left_rows) \
                    or any(part.get("when", {}).get("connect_right") is not False for part in right_rows):
                raise AssertionError("shared thin skins must render only while their corresponding edge is disconnected")
        else:
            state = state_file["variants"]
            facings = {part.split("=", 1)[1] for key in state for part in key.split(",")
                       if part.startswith("facing=")}
            if facings != {"north", "east", "south", "west"}:
                raise AssertionError(f"{item}: facing state coverage is incomplete: {facings}")

    lamp_state = read(ASSETS / "blockstates/floor_lamp.json")["variants"]
    expected_lamp_states = {f"facing={facing},lit={lit},half={half}"
                            for facing in ("north", "east", "south", "west")
                            for lit in ("false", "true") for half in ("lower", "upper")}
    if set(lamp_state) != expected_lamp_states:
        raise AssertionError("Floor lamp needs both halves, all facings, and both light states")
    if len(read(ASSETS / "models/block/floor_lamp.json")["elements"]) != 9 \
            or len(read(ASSETS / "models/block/floor_lamp_on.json")["elements"]) != 9:
        raise AssertionError("Floor lamp's two overlapping lampshade material groups must be separate states")

    ladder_states = read(ASSETS / "blockstates/a_frame_ladder.json")["variants"]
    if len(ladder_states) != 8:
        raise AssertionError("A-frame ladder needs lower/upper models for all four facings")
    ladder_loot = read(ROOT / "src/generated/resources/data/pastoral_home/loot_table/blocks/a_frame_ladder.json")
    loot_conditions = [condition for pool in ladder_loot.get("pools", [])
                       for entry in pool.get("entries", []) for condition in entry.get("conditions", [])]
    if not any(condition.get("properties", {}).get("half") == "lower" for condition in loot_conditions):
        raise AssertionError("A-frame ladder loot must come from the lower half only")
    telescope_states = read(ASSETS / "blockstates/telescope.json")["variants"]
    if len(telescope_states) != 8 or {key.split("half=", 1)[1] for key in telescope_states} != {"lower", "upper"}:
        raise AssertionError("Telescope needs an upper/lower state for every facing")
    if len(read(ASSETS / "models/block/globe_stand.json")["elements"]) != 8 \
            or len(read(ASSETS / "models/block/globe_sphere.json")["elements"]) != 1:
        raise AssertionError("Globe BER requires a static stand model and one independently rotating sphere model")
    # The full-tree icon pass wraps every item definition in a display_context select,
    # so the BER item resolves through its non-GUI fallback rather than a bare model.
    for hidden_item, expected_model in (("globe_stand_render", "globe_stand"),
                                        ("globe_sphere_render", "globe_sphere")):
        item_model = read(ASSETS / f"items/{hidden_item}.json")["model"]
        if item_model.get("fallback", {}).get("model") != f"pastoral_home:block/{expected_model}":
            raise AssertionError(f"{hidden_item}: BER model item must resolve to {expected_model}")
    for part_name, expected_elements in (("one_cell_canopy_core", 2),
                                         ("one_cell_canopy_side_left", 1),
                                         ("one_cell_canopy_side_right", 1)):
        part_model = read(ASSETS / f"models/block/{part_name}.json")
        if len(part_model.get("elements", [])) != expected_elements:
            raise AssertionError(f"{part_name}: shared side skin split changed")
    for locale in ("en_us", "zh_cn"):
        lang = read(ROOT / f"src/generated/resources/assets/pastoral_home/lang/{locale}.json")
        for item in ITEMS:
            if f"block.pastoral_home.{item}" not in lang:
                raise AssertionError(f"{locale}: missing block name for {item}")
    print("Seven outdoor model assets pass: models, texture references, GUI proxies, lamp variants, ladder halves, and names.")


if __name__ == "__main__":
    main()
