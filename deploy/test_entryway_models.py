#!/usr/bin/env python3
"""Regression-check imported geometry/UVs, edge variants, icon fit."""
from __future__ import annotations

import json
import copy
import math
from pathlib import Path
from PIL import Image, ImageStat
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/entryway"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
GENERATED = ROOT / "src/generated/resources"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from split_model_cells import split_model
from item_icon_proxy import collect_model_ids, geometry_bounds


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def close(a, b):
    return abs(float(a) - float(b)) < 1e-6


def check_source_import(name: str, offsets=(0, 0, 0), skip=(), model_path=None):
    source = read(SOURCE / f"{name}.bbmodel")
    model = read(model_path or ASSETS / f"models/block/{name}.json")
    width = float(source.get("resolution", {}).get("width", 16))
    height = float(source.get("resolution", {}).get("height", width))
    expected = [i for i in range(len(source["elements"])) if i not in set(skip)]
    assert len(model["elements"]) == len(expected), (name, len(model["elements"]), len(expected))
    for out_index, src_index in enumerate(expected):
        src, out = source["elements"][src_index], model["elements"][out_index]
        inflate = float(src.get("inflate", 0.0) or 0.0)
        for point in ("from", "to"):
            for axis in range(3):
                direction = 1.0 if float(src["to"][axis]) >= float(src["from"][axis]) else -1.0
                expected_value = float(src[point][axis]) + offsets[axis]
                if point == "from": expected_value -= direction * inflate
                else: expected_value += direction * inflate
                assert close(out[point][axis], expected_value), (name, src_index, point, axis)
        src_rot, out_rot = src.get("rotation"), out.get("rotation")
        assert bool(src_rot) == bool(out_rot), (name, src_index, "rotation")
        if src_rot:
            for axis in range(3):
                assert close(out_rot["origin"][axis], float(src["origin"][axis]) + offsets[axis]), (name, src_index, "origin", axis)
        expected_faces = {face: data for face, data in src.get("faces", {}).items()
                          if data.get("texture") is not None and data.get("uv") is not None}
        assert set(out["faces"]) == set(expected_faces), (name, src_index, "faces")
        for face, data in expected_faces.items():
            uv = data["uv"]
            expected_uv = [float(uv[0]) * 16 / width, float(uv[1]) * 16 / height,
                           float(uv[2]) * 16 / width, float(uv[3]) * 16 / height]
            assert all(close(a, b) for a, b in zip(out["faces"][face]["uv"], expected_uv)), (name, src_index, face, "uv")
            tex_index = data.get("texture", 0)
            tex_key = f"bb_texture_{tex_index.lstrip('#')}" if isinstance(tex_index, str) and tex_index.startswith("#") else f"bb_texture_{int(tex_index)}"
            assert out["faces"][face]["texture"] == f"#{tex_key}", (name, src_index, face, "texture")


def main():
    check_source_import("coat_rack")
    imported_coat = read(ROOT / "build/entryway_models/coat_rack.json")
    assert imported_coat["elements"][33]["from"] != imported_coat["elements"][34]["from"]
    assert imported_coat["elements"][33]["to"] != imported_coat["elements"][34]["to"]
    check_source_import("parasol", model_path=ROOT / "build/entryway_models/parasol.json")
    parasol_world = read(ROOT / "build/entryway_models/parasol_world_model.json")
    parasol_imported = read(ROOT / "build/entryway_models/parasol.json")
    assert len(parasol_world["elements"]) == len(parasol_imported["elements"])
    for original, placed in zip(parasol_imported["elements"], parasol_world["elements"]):
        for point in ("from", "to"):
            assert close(placed[point][0], original[point][0])
            assert close(placed[point][1], original[point][1] + 2.1844)
            assert close(placed[point][2], original[point][2])
    parasol_fence_world = read(ROOT / "build/entryway_models/parasol_fence_world_model.json")
    for ground, mounted in zip(parasol_world["elements"], parasol_fence_world["elements"]):
        for point in ("from", "to"):
            assert close(mounted[point][0], ground[point][0])
            assert close(mounted[point][1], ground[point][1] - 2.0)
            assert close(mounted[point][2], ground[point][2])
    parasol_block_source = (ROOT / "src/main/java/com/pastoralhome/block/ParasolBlock.java").read_text(encoding="utf-8")
    assert "FENCE_MOUNTED, hasFenceSupport" in parasol_block_source
    assert "renderCorrectionPixels" in parasol_block_source
    check_source_import("rug", model_path=ROOT / "build/entryway_models/rug.json")
    for model_name in ("coat_rack", "parasol", "rug"):
        imported = read(ASSETS / f"models/block/{model_name}.json")
        expected_particle = f"pastoral_home:block/{model_name}_particle"
        assert imported["textures"]["particle"] == expected_particle, model_name
    board_source = read(SOURCE / "bulletin_board.bbmodel")
    board_authored = read(ROOT / "build/entryway_models/bulletin_board_authored_full.json")
    for index in (16, 21):
        assert board_authored["elements"][index]["from"] != board_source["elements"][index]["from"]
        assert board_authored["elements"][index]["to"] != board_source["elements"][index]["to"]
    board_imported = read(ROOT / "build/entryway_models/bulletin_board.json")
    board_skip = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 22, 23, 24}
    expected_board = [e for i, e in enumerate(board_source["elements"]) if i not in board_skip]
    assert len(board_imported["elements"]) == len(board_source["elements"])
    board_imported["elements"] = [e for i, e in enumerate(board_imported["elements"]) if i not in board_skip]
    board_imported["elements"][0]["faces"]["north"]["uv"] = copy.deepcopy(
        board_imported["elements"][0]["faces"]["south"]["uv"])
    for element in board_imported["elements"]:
        for point in ("from", "to"):
            element[point][1] += 16
        if element.get("rotation"):
            element["rotation"]["origin"][1] += 16
    split_cells, split_warnings = split_model(board_imported)
    expected_cells = {}
    for (dx, layer, dz), fragments in split_cells.items():
        render_dz = 0 if layer == 2 and dz != 0 else dz
        if render_dz != dz:
            for fragment in fragments:
                for point in ("from", "to"):
                    fragment[point][2] += dz * 16.0
                if fragment.get("rotation"):
                    fragment["rotation"]["origin"][2] += dz * 16.0
        expected_cells.setdefault((dx, layer, render_dz), []).extend(fragments)
    assert len(expected_board) == 12
    model_bounds = geometry_bounds(board_imported)
    assert close((model_bounds[0] + model_bounds[3]) * 0.5, 8.0)
    assert close((model_bounds[2] + model_bounds[5]) * 0.5, 8.0), \
        f"world model is displaced from its placement center: z bounds {model_bounds[2]}, {model_bounds[5]}"
    assert math.floor(model_bounds[2] / 16) == -1 and math.floor((model_bounds[5] - 1e-6) / 16) == 1
    seen = []
    for layer in range(3):
        for column in range(3):
            for row in range(3):
                model = read(ASSETS / f"models/block/bulletin_board_l{layer}_c{column}_r{row}.json")
                expected = expected_cells.get((column - 1, layer, row - 1), [])
                assert model["elements"] == expected, (layer, column, row, len(model["elements"]), len(expected))
                for out in model["elements"]:
                    for point in ("from", "to"):
                        assert all(-16 <= float(v) <= 32 for v in out[point]), (layer, column, row, out)
                    seen.append(out)
    assert len(seen) > len(expected_board), "cross-cell board panels were not split into grid-owned fragments"
    assert board_imported["elements"][0]["faces"]["north"]["uv"] == \
        board_imported["elements"][0]["faces"]["south"]["uv"], \
        "blank board front still samples the baked-in colored pin marks"
    collision_report = read(ROOT / "build/entryway_models/bulletin_board_collision_report.json")
    assert collision_report["grid"] == {"x": [0.0, 16.0], "y": [16.0, 32.0], "z": [0.0, 16.0]}
    for boxes in collision_report["cell_boxes"].values():
        assert all(-1e-6 <= value <= 16.000001 for box in boxes for value in box), boxes
    assert max(collision_report["shape_box_counts"].values()) <= 6
    # Envelope colliders around a two-pixel board cannot be tight: the whole cell body
    # gives back roughly 2.6 times the panel it wraps, and the ceiling was 35 % only while
    # the measurement counted the board's bounding boxes instead of its voxels. The 2026-11-25
    # rebuild of tools/collision made both sides voxel-based (a slanted part now counts as the
    # slice it really is), so the ceiling moved with the metric, not with the board.
    assert collision_report["air_percent_over_rendered_cells"] <= 220.0, \
        collision_report["air_percent_over_rendered_cells"]
    assert "source-element envelopes merged per cell" in collision_report["collision_policy"]
    assert "canopy eaves excluded" in collision_report["collision_policy"]
    assert collision_report["canopy_collision_excluded_source_elements"] == [16, 21]
    board_split = read(ROOT / "build/entryway_models/bulletin_board_model_split_report.json")
    assert not {8, 9}.intersection(set(board_split["source_elements_in_world_model"])), \
        "the colored sticky-note templates must not be baked into the blank board"
    assert board_split["paper_template_source_elements"] == [8, 9]
    for key, boxes in collision_report["cell_boxes"].items():
        layer, _column, _row = map(int, key.split(","))
        if layer == 2:
            # The eaves remain visible/selectable but no longer form a broad
            # top-row body collider that blocks adjacent placement.
            assert all(box[4] <= 13.000001 or (box[2] >= 6.49 and box[5] <= 9.51)
                       for box in boxes), (key, boxes)
    split_report = read(ROOT / "build/entryway_models/bulletin_board_model_split_report.json")
    crossings = split_report["rotated_element_cell_crossings"]
    assert crossings and all(warning["max_overhang_px"] <= 1.1 for warning in crossings), crossings
    assert (ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardCollisionShapes.java").is_file()
    for name in ("coat_rack", "parasol", "rug", "bulletin_board"):
        for path in (ASSETS / f"blockstates/{name}.json", ASSETS / f"items/{name}.json",
                     ASSETS / f"models/block/{name}.json", ASSETS / f"textures/block/{name}.png",
                     GENERATED / f"data/pastoral_home/loot_table/blocks/{name}.json"):
            assert path.is_file(), f"missing {path}"
    assert (ASSETS / "items/bulletin_page.json").is_file()
    assert (ASSETS / "models/item/bulletin_page.json").is_file()
    assert (ASSETS / "font/notebook.json").is_file()
    assert (ASSETS / "font/lxgw_wenkai_lite_regular.ttf").is_file()
    assert (ASSETS / "font/ofl.txt").is_file()
    notebook_font = read(ASSETS / "font/notebook.json")
    assert notebook_font["providers"][0]["type"] == "ttf"
    assert notebook_font["providers"][0]["file"] == "pastoral_home:lxgw_wenkai_lite_regular.ttf"
    title_font = read(ASSETS / "font/notebook_title.json")
    assert title_font["providers"][0]["type"] == "ttf"
    assert title_font["providers"][0]["size"] == 12.0
    assert (ASSETS / "textures/gui/paper_notebook.png").is_file()
    paper_background = Image.open(ASSETS / "textures/gui/paper_notebook.png").convert("RGB")
    assert paper_background.size == (256, 224)
    paper_rgba = Image.open(ASSETS / "textures/gui/paper_notebook.png").convert("RGBA")
    assert paper_rgba.getchannel("A").getextrema() == (255, 255), \
        "the editor sheet must be opaque; alpha in the writing area exposes the game world"
    writing_area_stats = ImageStat.Stat(paper_background.crop((36, 94, 220, 167)))
    assert max(writing_area_stats.stddev) < 12.0, writing_area_stats.stddev
    screen_source = (ROOT / "src/main/java/com/pastoralhome/client/PaperNoticeScreen.java").read_text(encoding="utf-8")
    assert "payload.mode() == OpenBulletinNoticePayload.Mode.NEW_ON_BOARD.ordinal()" in screen_source
    assert "gui.pastoral_home.notice.pin" in screen_source and "gui.pastoral_home.notice.save" in screen_source
    assert ".setY(this.top + 86)" in screen_source and ".build(this.font, 196, 89," in screen_source
    assert "this.left + 30, this.top + 51, 194, 17" in screen_source
    assert "this.titleBox.setTextShadow(false)" in screen_source
    assert "this.titleBox.setTextColor(INK)" in screen_source
    assert "drawEditableBody(graphics)" in screen_source and "drawEditableTitle(graphics)" not in screen_source
    assert "withFont(TITLE_FONT).withColor(0xFF59402F)" in screen_source
    assert "withFont(TITLE_FONT).withBold(true)" not in screen_source
    assert "graphics.pose().scale((float) nativeAdvance / styledAdvance, 1.0F)" in screen_source
    assert "withFont(NOTEBOOK_FONT).withColor(INK)" in screen_source
    assert "graphics.text(this.font, visual, x, y, 0xFFFFFFFF, false)" in screen_source
    paper_builder = (ROOT / "tools/deploy/build_bulletin_paper_assets.py").read_text(encoding="utf-8")
    assert "rounded_rectangle" not in paper_builder and "d.line((29, 63" not in paper_builder
    board_entity_source = (ROOT / "src/main/java/com/pastoralhome/blockentity/BulletinBoardBlockEntity.java").read_text(encoding="utf-8")
    assert "List<BulletinPlacedNotice>" in board_entity_source and "nine-slot" not in board_entity_source
    particle_path = ASSETS / "textures/block/bulletin_board_particle.png"
    assert particle_path.is_file() and Image.open(particle_path).size == (16, 16)
    board_cell = read(ASSETS / "models/block/bulletin_board_l1_c1_r1.json")
    assert board_cell["textures"]["particle"] == "pastoral_home:block/bulletin_board_particle"
    page_variants = read(ROOT / "build/entryway_models/bulletin_page_variants.json")["variants"]
    assert [entry["source_element"] for entry in page_variants] == [2, 3, 4, 5, 6, 7, 10, 22, 23, 24, 8, 9]
    shadow_report = read(ROOT / "build/entryway_models/bulletin_page_shadow_source_report.json")
    assert shadow_report["paired_page_source_element"] == 4
    assert shadow_report["shadow_source_element"] == 24
    assert shadow_report["generated_shadow_models"] == 24
    source_atlas = read(SOURCE / "bulletin_board.bbmodel")
    assert page_variants[0]["render_source_elements"] == [2, 22]
    assert page_variants[1]["render_source_elements"] == [3, 23]
    assert page_variants[7]["render_source_elements"] == [2, 22]
    assert page_variants[8]["render_source_elements"] == [3, 23]
    assert page_variants[9]["render_source_elements"] == [4]
    assert page_variants[10]["source_element"] == 8 and page_variants[11]["source_element"] == 9
    for entry in page_variants:
        source_indices = entry["render_source_elements"]
        for side, face in ((0, "north"), (1, "south")):
            suffix = "front" if side == 0 else "back"
            model_id = f"bulletin_page_variant_{entry['variant']}_{suffix}"
            page_model = read(ASSETS / f"models/item/{model_id}.json")
            page_definition = read(ASSETS / f"items/{model_id}.json")
            assert page_model["textures"]["bb_texture_0"] == "pastoral_home:block/bulletin_board"
            assert len(page_model["elements"]) == len(source_indices)
            for rendered_element, source_index in zip(page_model["elements"], source_indices):
                source_uv = source_atlas["elements"][source_index]["faces"]["north"]["uv"]
                expected_uv = [value * 16.0 / 128.0 for value in source_uv]
                assert set(rendered_element["faces"]) == {face}
                assert rendered_element["faces"][face]["texture"] == "#bb_texture_0"
                assert all(close(actual, expected) for actual, expected in
                           zip(rendered_element["faces"][face]["uv"], expected_uv))
            local_bounds = geometry_bounds(page_model)
            assert all(close((local_bounds[axis] + local_bounds[axis + 3]) * 0.5, 8.0)
                       for axis in range(3)), (model_id, local_bounds)
            assert page_definition["model"]["fallback"]["model"] == f"pastoral_home:item/{model_id}"
            assert page_definition["model"]["cases"][0]["model"]["model"] == \
                f"pastoral_home:item_icons/{model_id}/variant_0"
            shadow_model_id = f"bulletin_shadow_variant_{entry['variant']}_{suffix}"
            shadow_model = read(ASSETS / f"models/item/{shadow_model_id}.json")
            shadow_definition = read(ASSETS / f"items/{shadow_model_id}.json")
            expected_shadow_count = len(source_indices)
            assert len(shadow_model["elements"]) == expected_shadow_count
            assert all(set(element["faces"]) == {face} for element in shadow_model["elements"])
            assert shadow_model["textures"] == page_model["textures"]
            assert all(close(element["from"][2], 8.0) and close(element["to"][2], 8.0)
                       and (element.get("rotation") is None
                            or element["rotation"].get("axis") == "z")
                       for element in shadow_model["elements"]), shadow_model_id
            assert shadow_definition["model"]["cases"][0]["model"]["model"] == \
                f"pastoral_home:item_icons/{shadow_model_id}/variant_0"
            assert shadow_definition["model"]["fallback"]["model"] == f"pastoral_home:item/{shadow_model_id}"
            if expected_shadow_count:
                source_shadow_uv = source_atlas["elements"][shadow_report["shadow_source_element"]]["faces"]["north"]["uv"]
                expected_shadow_uv = [value * 16.0 / 128.0 for value in source_shadow_uv]
                actual_shadow_uv = shadow_model["elements"][0]["faces"][face]["uv"]
                assert all(close(actual, expected) for actual, expected in zip(actual_shadow_uv, expected_shadow_uv))
            shadow_model_id = f"bulletin_shadow_variant_{entry['variant']}_{suffix}"
            shadow_model = read(ASSETS / f"models/item/{shadow_model_id}.json")
            assert len(shadow_model["elements"]) == expected_shadow_count
            if expected_shadow_count:
                assert set(shadow_model["elements"][0]["faces"]) == {face}
            assert shadow_model["textures"] == page_model["textures"]
    default_page_model = read(ASSETS / "models/item/bulletin_page.json")
    source_strip_model = read(ASSETS / "models/item/bulletin_page_variant_10_front.json")
    assert default_page_model["elements"] == source_strip_model["elements"], \
        "the inventory icon should use the complete BB-authored paper model, not a generic base sheet"
    assert (ROOT / "build/entryway_models/bulletin_board_posted_pages_preview.png").is_file()
    renderer_source = (ROOT / "src/main/java/com/pastoralhome/client/BulletinBoardBlockEntityRenderer.java").read_text(encoding="utf-8")
    assert "placed.centerX() / 16.0, placed.centerY() / 16.0" in renderer_source
    page_transform = renderer_source.split(
        "poseStack.translate(placed.centerX() / 16.0, placed.centerY() / 16.0, paperDepth / 16.0);", 1
    )[1].split("pageState.submit", 1)[0]
    assert "poseStack.translate" not in page_transform
    assert "ItemDisplayContext.NONE applies the block-item centering transform" in renderer_source
    assert "BulletinBoardLayout.paperDepth(notice.paperStyle(), placed.side())" in renderer_source
    assert "BulletinPageTemplates.rotationAngle(notice.paperStyle())" in renderer_source
    layout_source = (ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardLayout.java").read_text(encoding="utf-8")
    template_source = (ROOT / "src/main/java/com/pastoralhome/block/BulletinPageTemplates.java").read_text(encoding="utf-8")
    assert "BulletinPageTemplates.width(paperStyle)" in layout_source
    assert "DEPTHS" in template_source and "ROTATION_AXES" in template_source
    assert "itemModel(int variant, int side)" in template_source
    assert "shadowItemModel(int variant, int side)" in template_source
    assert "choose(String title, String body, int variationSalt)" in template_source
    assert "shadowState.submit" in renderer_source and "shadowItemModel(placed.data().paperStyle()" in renderer_source
    assert "placed.side() == 1" in renderer_source and "FRONT_SURFACE_Z - 0.015" in renderer_source
    assert "BACK_SURFACE_Z + 0.015" in renderer_source
    board_interaction = (ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardBlock.java").read_text(encoding="utf-8")
    assert board_interaction.index("board.getNoticeAt(point.x(), point.y(), targetSide)") < board_interaction.index("openNewBoardNotice")
    assert "openBoardNotice(serverPlayer, anchor, existing" in board_interaction
    assert (SOURCE / "paper_notebook_base.png").is_file()
    assert (ROOT / "build/entryway_models/paper_notice_screen_preview.png").is_file()
    assert (ROOT / "build/entryway_models/bulletin_board_posted_pages_preview.png").is_file()
    bulletin_state = read(ASSETS / "blockstates/bulletin_board.json")
    assert len(bulletin_state["variants"]) == 108
    for layer in range(3):
        for column in range(3):
            for row in range(3):
                for facing, degrees in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
                    variant = bulletin_state["variants"][f"facing={facing},layer={layer},column={column},row={row}"]
                    assert variant["model"] == f"pastoral_home:block/bulletin_board_l{layer}_c{column}_r{row}"
                    assert variant.get("y", 0) == degrees
    coat_state = read(ASSETS / "blockstates/coat_rack.json")
    assert len(coat_state["variants"]) == 8
    for facing, degrees in (("north", 180), ("east", 270), ("south", 0), ("west", 90)):
        for layer in range(2):
            variant = coat_state["variants"][f"facing={facing},layer={layer},column=0,row=0"]
            assert variant["model"] == "pastoral_home:block/coat_rack"
            assert variant.get("y", 0) == degrees
    coat_source = (ROOT / "src/main/java/com/pastoralhome/block/CoatRackBlock.java").read_text(encoding="utf-8")
    assert "extends DecorativeStructureBlock" in coat_source
    assert "super(properties, 0, 1, 0, 0, 0, 0, 0, 0, 0)" in coat_source
    assert "CoatRackCollisionShapes.selectionFor(state)" in coat_source
    assert "CoatRackCollisionShapes.collisionFor(state)" in coat_source
    coat_shapes = read(ROOT / "build/entryway_models/coat_rack_cell_shapes.json")
    assert set(coat_shapes["selection_boxes"]) == {"0,1,1", "1,1,1"}
    assert coat_shapes["collision_max_boxes_per_cell"] <= 5
    assert coat_shapes["collision_boxes"]["1,1,1"] == [[7, 0, 7, 9, 11, 9], [6, 11, 6, 10, 15, 10]]
    loot_source = (ROOT / "src/main/java/com/pastoralhome/data/ModBlockLootProvider.java").read_text(encoding="utf-8")
    assert "dropSelfAnchorOnly(output, ModBlocks.COAT_RACK.get())" in loot_source
    # The anchor indices are read off the block instead of being hand-copied here, so the loot
    # condition cannot drift away from the declaration that decides where the structure places.
    for accessor in ("anchorLayerIndex()", "anchorColumnIndex()", "anchorRowIndex()"):
        assert accessor in loot_source
    assert "dropSelfAnchorOnly(BlockOutput output, Block block, int layer" not in loot_source
    parasol_source = (ROOT / "src/main/java/com/pastoralhome/block/ParasolBlock.java").read_text(encoding="utf-8")
    assert "super(properties, 0, 1, -1, 1, -1, 1, 0, 1, 1)" in parasol_source
    assert "ParasolCollisionShapes.selectionFor(state)" in parasol_source
    assert "ParasolCollisionShapes.collisionFor(state)" in parasol_source
    parasol_shapes = read(ROOT / "build/entryway_models/parasol_cell_shapes.json")
    assert set(parasol_shapes["selection_boxes"]) == {
        f"{layer},{column},{row}" for layer in range(2) for column in range(3) for row in range(3)}
    assert parasol_shapes["selection_max_boxes_per_cell"] <= 4
    for column in range(3):
        for row in range(3):
            upper_boxes = parasol_shapes["selection_boxes"][f"1,{column},{row}"]
            assert upper_boxes == [[0.0, 0.0, 0.0, 16.0, 16.0, 16.0]]
            assert parasol_shapes["collision_boxes"][f"1,{column},{row}"] == []
    assert set(key for key, boxes in parasol_shapes["collision_boxes"].items() if boxes) == {"0,1,1"}
    assert parasol_shapes["collision_policy"].endswith("entire second layer passes through")
    assert (ROOT / "build/entryway_models/coat_rack_collision_preview.png").is_file()
    assert (ROOT / "build/entryway_models/parasol_collision_preview.png").is_file()
    assert (ROOT / "build/entryway_models/parasol_fence_collision_preview.png").is_file()
    parasol_block_source = (ROOT / "src/main/java/com/pastoralhome/block/ParasolBlock.java").read_text(encoding="utf-8")
    assert "setValue(FENCE_MOUNTED, hasFenceSupport" in parasol_block_source
    parasol_state = read(ASSETS / "blockstates/parasol.json")
    assert len(parasol_state["variants"]) == 8
    for face, degrees in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        for mounted in ("false", "true"):
            variant = parasol_state["variants"][f"facing={face},fence_mounted={mounted}"]
            expected_model = "parasol_fence" if mounted == "true" else "parasol"
            assert variant["model"] == f"pastoral_home:block/{expected_model}"
            assert variant.get("y", 0) == degrees
    icon = read(ASSETS / "models/block/bulletin_board.json")
    assert all(-16 <= coordinate <= 32 for e in icon["elements"] for p in ("from", "to") for coordinate in e[p])
    for item_id in ("coat_rack", "parasol", "rug", "bulletin_board"):
        item_definition = read(ASSETS / f"items/{item_id}.json")["model"]
        gui_tree = next(case["model"] for case in item_definition["cases"] if case["when"] == "gui")
        fallback_tree = item_definition["fallback"]
        gui_ids = collect_model_ids(gui_tree)
        fallback_ids = collect_model_ids(fallback_tree)
        assert gui_ids and all(model_id.startswith(f"pastoral_home:item_icons/{item_id}/") for model_id in gui_ids)
        assert fallback_ids and all(not model_id.startswith("pastoral_home:item_icons/") for model_id in fallback_ids)
    bulletin_loot = read(GENERATED / "data/pastoral_home/loot_table/blocks/bulletin_board.json")
    assert bulletin_loot["pools"][0]["conditions"][0]["properties"] == {
        "column": "1", "layer": "0", "row": "1"}
    rug_state = read(ASSETS / "blockstates/rug.json")
    assert len(rug_state["variants"]) == 16
    assert all((ASSETS / f"models/block/{value['model'].split('/')[-1]}.json").is_file()
               for value in rug_state["variants"].values())
    for variant in range(16):
        assert (ASSETS / f"models/block/rug_{variant:02x}.json").is_file()
        rug_model = read(ASSETS / f"models/block/rug_{variant:02x}.json")
        base = rug_model["elements"][0]
        assert close(base["from"][0], 0.0 if variant & 8 else 2.0)
        assert close(base["to"][0], 16.0 if variant & 2 else 14.0)
        assert close(base["from"][2], 0.0 if variant & 1 else 2.0)
        assert close(base["to"][2], 16.0 if variant & 4 else 14.0)
        top_coverage = [[0 for _ in range(16)] for _ in range(16)]
        for element in rug_model["elements"]:
            if "up" not in element.get("faces", {}) or not close(element["to"][1], 1.1):
                continue
            x0, x1 = max(0.0, float(element["from"][0])), min(16.0, float(element["to"][0]))
            z0, z1 = max(0.0, float(element["from"][2])), min(16.0, float(element["to"][2]))
            for x in range(16):
                for z in range(16):
                    if x + 0.5 >= x0 and x + 0.5 < x1 and z + 0.5 >= z0 and z + 0.5 < z1:
                        top_coverage[x][z] += 1
        assert all(value == 1 for column in top_coverage for value in column), (variant, top_coverage)
        rug_surface_item = read(ASSETS / f"items/rug_surface_{variant:02x}.json")["model"]
        assert rug_surface_item["fallback"]["model"] == f"pastoral_home:block/rug_{variant:02x}"
        assert rug_surface_item["cases"][0]["model"]["model"] == \
            f"pastoral_home:item_icons/rug_surface_{variant:02x}/variant_0"
    rug_templates = (ROOT / "src/main/java/com/pastoralhome/block/RugSurfaceTemplates.java").read_text(encoding="utf-8")
    assert "surfaceOriginY()" in rug_templates and "surfaceHeight()" in rug_templates
    assert "rotateMaskToLocal" in rug_templates and "rotationForFacing" in rug_templates
    rug_geometry_report = read(ROOT / "build/entryway_models/rug_surface_geometry_report.json")
    assert rug_geometry_report["top_surface_regions"] == {
        "base": [2.0, 2.0, 14.0, 14.0],
        "west_trim": [0.0, 0.0, 2.0, 16.0],
        "east_trim": [14.0, 0.0, 16.0, 16.0],
        "north_border": [2.0, 0.0, 14.0, 2.0],
        "south_border": [2.0, 14.0, 14.0, 16.0],
    }
    rug_models = [read(ASSETS / f"models/block/rug_{mask:02x}.json") for mask in range(16)]
    assert all("up" in rug_models[0]["elements"][index]["faces"] for index in (0, 1, 4, 7, 8))
    assert rug_models[0]["elements"][0]["from"][0] == 2.0
    assert rug_models[0]["elements"][0]["to"][0] == 14.0
    assert rug_models[0]["elements"][7]["from"][0] == 2.0
    assert rug_models[0]["elements"][7]["to"][0] == 14.0
    rug_entity = (ROOT / "src/main/java/com/pastoralhome/entity/RugSurfaceEntity.java").read_text(encoding="utf-8")
    assert "refreshAround" in rug_entity and "supportPos()" in rug_entity
    assert "1.0 + 0.5 - RugSurfaceTemplates.surfaceOriginY()" in rug_entity
    assert "ROTATION_QUADRANTS" in rug_entity and 'output.putInt("rotation"' in rug_entity
    assert "supportPos.getY() + 1.7" in rug_entity
    rug_renderer = (ROOT / "src/main/java/com/pastoralhome/client/renderer/RugSurfaceRenderer.java").read_text(encoding="utf-8")
    assert "poseStack.translate(-0.5F, 0.0F, -0.5F)" not in rug_renderer
    assert "rotateMaskToLocal" in rug_renderer and "rotationQuadrants * 90.0F" in rug_renderer
    rug_item = (ROOT / "src/main/java/com/pastoralhome/item/RugSurfaceItem.java").read_text(encoding="utf-8")
    assert "hasFullLevelTopSurface" in rug_item and "addFreshEntity" in rug_item
    zh_lang = read(GENERATED / "assets/pastoral_home/lang/zh_cn.json")
    en_lang = read(GENERATED / "assets/pastoral_home/lang/en_us.json")
    assert zh_lang["item.pastoral_home.rug"] == "地毯"
    assert en_lang["item.pastoral_home.rug"] == "Rug"
    assert zh_lang["gui.pastoral_home.notice.save"] == "保存"
    assert zh_lang["gui.pastoral_home.notice.pin"] == "张贴"
    for item_name, chinese, english in (("coat_rack", "衣帽架", "Coat Rack"),
                                        ("parasol", "遮阳伞", "Parasol"),
                                        ("bulletin_board", "公告栏", "Bulletin Board")):
        assert zh_lang[f"block.pastoral_home.{item_name}"] == chinese
        assert en_lang[f"block.pastoral_home.{item_name}"] == english
    coat_loot = read(GENERATED / "data/pastoral_home/loot_table/blocks/coat_rack.json")
    assert coat_loot["pools"][0]["conditions"][0]["properties"] == {
        "layer": "0", "column": "0", "row": "0"}
    parasol_loot = read(GENERATED / "data/pastoral_home/loot_table/blocks/parasol.json")
    # ParasolBlock anchors on row 1 (the middle of its -1..1 footprint), so the loot condition has
    # to name that row or the umbrella never matches its own state and drops nothing.
    assert parasol_loot["pools"][0]["conditions"][0]["properties"] == {
        "column": "1", "layer": "0", "row": "1"}
    board_renderer = (ROOT / "src/main/java/com/pastoralhome/client/BulletinBoardBlockEntityRenderer.java").read_text(encoding="utf-8")
    board_layout = (ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardLayout.java").read_text(encoding="utf-8")
    assert "rendererYaw(facing)" in board_renderer
    assert "for (BulletinPlacedNotice placed : board.getNotices())" in board_renderer
    assert "state.pages.add(new PageRender(placed, pageState, shadowState))" in board_renderer
    assert "shadowState.submit" in board_renderer
    assert "return -modelYaw(facing)" in board_layout
    board_interaction = (ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardBlock.java").read_text(encoding="utf-8")
    assert board_interaction.index("board.getNoticeAt(point.x(), point.y(), targetSide)") < board_interaction.index("openNewBoardNotice")
    assert "openBoardNotice(serverPlayer, anchor, existing" in board_interaction
    save_payload = (ROOT / "src/main/java/com/pastoralhome/network/SaveBulletinNoticePayload.java").read_text(encoding="utf-8")
    assert "styleFor(title, body, player.level().getRandom().nextInt()," in save_payload
    assert "board.getNotices().stream().map(entry -> entry.data().paperStyle()).toList()" in save_payload
    assert "entry.id() != payload.noticeId()" in save_payload
    assert "withText(title, body,\n                    player.level().getRandom().nextInt(), existingStyles)" in save_payload
    icons = read(ROOT / "build/entryway_models/item_icons.json")
    assert {entry["item"] for entry in icons} == {"coat_rack", "parasol", "rug", "bulletin_board"}
    assert (ROOT / "build/entryway_models/bulletin_page_item_preview.png").is_file()
    page_item_model = read(ASSETS / "models/item/bulletin_page.json")
    page_authored_model = read(ASSETS / "models/item/bulletin_page_variant_10_front.json")
    assert page_item_model["elements"] == page_authored_model["elements"]
    assert page_item_model["textures"] == page_authored_model["textures"]
    assert "entities.rug_surface" not in json.dumps(zh_lang)
    assert zh_lang["entity.pastoral_home.rug_surface"] == "地毯"
    coat_particle = Image.open(ASSETS / "textures/block/coat_rack_particle.png").convert("RGBA")
    assert coat_particle.getbbox() is not None
    coat_model = read(ASSETS / "models/block/coat_rack.json")
    assert coat_model["textures"]["particle"] == "pastoral_home:block/coat_rack_particle"
    assert all(entry["bounds_within_16px_cell"] for entry in icons), icons
    # The proxies centre their geometry on the cell, but the measurement runs on the
    # rendered silhouette: a sparse icon (the parasol's wide canopy over a thin pole and a
    # hanging skirt) cannot be centred more precisely than a pixel by moving an
    # axis-aligned box. One pixel is below the slot's visual resolution, so that is the gate.
    for entry in icons:
        offset = entry["projected_gui_center_offset"]
        assert abs(offset[0]) <= 1.0 and abs(offset[1]) <= 1.0, (entry["item"], entry)

    app_source = (ROOT / "src/main/java/com/pastoralhome/PastoralHome.java").read_text(encoding="utf-8")
    board_entity = (ROOT / "src/main/java/com/pastoralhome/blockentity/BulletinBoardBlockEntity.java").read_text(encoding="utf-8")
    assert "registerBlockEntityRenderer(ModBlockEntities.BULLETIN_BOARD.get()" in app_source
    assert 'output.store(NOTICES_TAG, NOTICE_LIST_CODEC, notices)' in board_entity
    print("Entryway asset regression checks passed: geometry/UVs, 16 rug states, icon bounds, resources. Jar contents are test_jar_contents.py's job.")


if __name__ == "__main__":
    main()
