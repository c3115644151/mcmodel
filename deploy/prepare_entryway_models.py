#!/usr/bin/env python3
"""Rebuild the four entryway model resources from the committed BBModel sources."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/entryway"
STAGE = ROOT / "build/entryway_models"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collision"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import deploy_collision
from generate import merge_exact_union_boxes
from split_model_cells import split_model
from item_icon_proxy import geometry_bounds

# Keep stable style IDs for notices already saved in worlds. Styles 7 and 8
# now both render the authored two-cube folded strip as one complete sheet;
# style 9 remains the legacy alias for the paper whose offset plane is its shadow.
PAPER_SOURCE_INDICES = (2, 3, 4, 5, 6, 7, 10, 22, 23, 24, 8, 9)
FOLDED_STRIP_SOURCE_GROUPS = {2: (2, 22), 22: (2, 22), 3: (3, 23), 23: (3, 23)}
FOLDED_STRIP_SOURCE_INDICES = set(FOLDED_STRIP_SOURCE_GROUPS)
COLOR_NOTE_SOURCE_INDICES = {8, 9}
BOARD_CANOPY_COLLISION_SOURCE_INDICES = {16, 21}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data, newline=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline=newline)


def import_model(name: str) -> dict:
    model_path = STAGE / f"{name}.json"
    texture_path = STAGE / f"{name}.png"
    texture_dir = STAGE / f"{name}_textures"
    cmd = [sys.executable, str(ROOT / "tools/deploy/import_java_block_bbmodel.py"),
           str(SOURCE / f"{name}.bbmodel"), "--model-out", str(model_path),
           "--texture-out", str(texture_path), "--mod-id", "pastoral_home",
           "--texture-name", name, "--texture-dir", str(texture_dir), "--texture-prefix", name]
    subprocess.run(cmd, check=True)
    model = read(model_path)
    texture_out = ASSETS / "textures/block"
    texture_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(texture_path, texture_out / f"{name}.png")
    for texture in texture_dir.glob("*.png"):
        shutil.copy2(texture, texture_out / texture.name)
    # Particle texture follows the imported material rather than the oak-plank fallback.
    model["textures"]["particle"] = f"pastoral_home:block/{name}"
    return model


def transform(model: dict, *, y: float = 0, z: float = 0):
    result = copy.deepcopy(model)
    for e in result.get("elements", []):
        for point in ("from", "to"):
            e[point][1] += y
            e[point][2] += z
        if e.get("rotation"):
            e["rotation"]["origin"][1] += y
            e["rotation"]["origin"][2] += z
    return result


def rotations(model_id: str, angles: dict[str, int]):
    return {"variants": {f"facing={face}": ({"model": f"pastoral_home:block/{model_id}", **({"y": y} if y else {})})
                          for face, y in angles.items()}}


def layered_rotations(model_id: str, angles: dict[str, int], layers: int):
    return {"variants": {
        f"facing={face},layer={layer},column=0,row=0":
            {"model": f"pastoral_home:block/{model_id}", **({"y": y} if y else {})}
        for face, y in angles.items() for layer in range(layers)
    }}


def set_item_display(model: dict, gui: float, hand: float):
    model["display"] = {
        "gui": {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [gui, gui, gui]},
        "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [gui, gui, gui]},
        "fixed": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [gui, gui, gui]},
        "thirdperson_righthand": {"rotation": [75, 45, 0], "translation": [0, 2, 0], "scale": [hand, hand, hand]},
        "thirdperson_lefthand": {"rotation": [75, 45, 0], "translation": [0, 2, 0], "scale": [hand, hand, hand]},
        "firstperson_righthand": {"rotation": [0, 225, 0], "translation": [0, 3, 0], "scale": [hand, hand, hand]},
        "firstperson_lefthand": {"rotation": [0, 45, 0], "translation": [0, 3, 0], "scale": [hand, hand, hand]},
    }


def assign_particle_from_model_face(model: dict, source_name: str, element_index: int,
                                    face_name: str, particle_name: str):
    """Use one authored, representative face for block-break particles."""
    source_model = read(SOURCE / f"{source_name}.bbmodel")
    source_element = source_model["elements"][element_index]
    face = source_element.get("faces", {}).get(face_name)
    if not face or face.get("texture") is None:
        raise ValueError(f"{source_name} element {element_index} has no {face_name} particle face")
    texture_index = int(face.get("texture", 0))
    source_texture = source_model["textures"][texture_index]
    atlas = Image.open(ASSETS / "textures/block" / f"{source_name}.png").convert("RGBA")
    uv = face["uv"]
    bounds = (min(uv[0], uv[2]), min(uv[1], uv[3]), max(uv[0], uv[2]), max(uv[1], uv[3]))
    scale_x = atlas.width / float(source_texture.get("uv_width", atlas.width))
    scale_y = atlas.height / float(source_texture.get("uv_height", atlas.height))
    crop = atlas.crop((round(bounds[0] * scale_x), round(bounds[1] * scale_y),
                       round(bounds[2] * scale_x), round(bounds[3] * scale_y)))
    if crop.width <= 0 or crop.height <= 0 or crop.getchannel("A").getbbox() is None:
        raise ValueError(f"{source_name} particle UV {bounds} is empty")
    target = ASSETS / "textures/block" / f"{particle_name}.png"
    crop.save(target)
    model["textures"]["particle"] = f"pastoral_home:block/{particle_name}"
    write(STAGE / f"{particle_name}_particle_report.json", {
        "source_element": element_index, "source_face": face_name, "uv": bounds,
        "atlas_size": [atlas.width, atlas.height], "particle_size": [crop.width, crop.height],
        "output": str(target.relative_to(ROOT)),
    })


def crop_element_uv_to_bounds(element: dict, new_from: list[float], new_to: list[float]):
    """Crop each face UV with its geometry when a cube is split to remove overlap."""
    old_from = list(map(float, element["from"]))
    old_to = list(map(float, element["to"]))
    axes_by_face = {
        "north": (0, 1), "south": (0, 1),
        "east": (2, 1), "west": (2, 1),
        "up": (0, 2), "down": (0, 2),
    }
    for face_name, face in element.get("faces", {}).items():
        if face.get("uv") is None or face_name not in axes_by_face:
            continue
        u_axis, v_axis = axes_by_face[face_name]
        uv = list(map(float, face["uv"]))
        for axis, low_index, high_index in ((u_axis, 0, 2), (v_axis, 1, 3)):
            span = old_to[axis] - old_from[axis]
            if abs(span) < 1e-9:
                continue
            low_t = (float(new_from[axis]) - old_from[axis]) / span
            high_t = (float(new_to[axis]) - old_from[axis]) / span
            uv[low_index] = float(face["uv"][low_index]) + (float(face["uv"][high_index]) - float(face["uv"][low_index])) * low_t
            uv[high_index] = float(face["uv"][low_index]) + (float(face["uv"][high_index]) - float(face["uv"][low_index])) * high_t
        face["uv"] = uv
    element["from"], element["to"] = list(map(float, new_from)), list(map(float, new_to))


def fit_rug_top_strips_to_single_surface(model: dict) -> dict:
    """Keep the full trim around the tile while giving each top face its own area."""
    base = model["elements"][0]
    base_from, base_to = list(base["from"]), list(base["to"])
    base_from[0], base_from[2], base_to[0], base_to[2] = 2.0, 2.0, 14.0, 14.0
    crop_element_uv_to_bounds(base, base_from, base_to)
    # West/east trims own the corners. North/south strips stop at their inner
    # edges so all five top faces meet without coplanar overlap.
    for index in (7, 8):
        element = model["elements"][index]
        new_from, new_to = list(element["from"]), list(element["to"])
        new_from[0], new_to[0] = 2.0, 14.0
        crop_element_uv_to_bounds(element, new_from, new_to)
    report = {
        "top_surface_regions": {
            "base": [2.0, 2.0, 14.0, 14.0],
            "west_trim": [0.0, 0.0, 2.0, 16.0],
            "east_trim": [14.0, 0.0, 16.0, 16.0],
            "north_border": [2.0, 0.0, 14.0, 2.0],
            "south_border": [2.0, 14.0, 14.0, 16.0],
        },
        "preserved_edge_elements": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "policy": "partition the authored top surface into non-overlapping base, trim and border faces",
    }
    write(STAGE / "rug_surface_geometry_report.json", report)
    return report


def java_number(value: float) -> str:
    return f"{float(value):.6f}D".replace("-0.000000D", "0.000000D")


def write_board_collision_helper(model: dict, render_cells: dict):
    """Generate one local collision union from the same fragments used to render each cell."""
    expected_grid = {"x": [0.0, 16.0], "y": [16.0, 32.0], "z": [0.0, 16.0]}
    selection_cases = []
    collision_cases = []
    counts = {}
    report_cells = {}
    cell_metrics = {}
    for layer in range(3):
        for column in range(3):
            for row in range(3):
                key = f"{layer},{column},{row}"
                fragments = render_cells.get((column - 1, layer, row - 1), [])
                def build_boxes(model_fragments, suffix):
                    if not model_fragments:
                        return [], None
                    collision_source = STAGE / f"bulletin_board_{suffix}_l{layer}_c{column}_r{row}.json"
                    cell_model = copy.deepcopy(model)
                    cell_model["elements"] = model_fragments
                    write(collision_source, cell_model)
                    indices = list(range(len(model_fragments)))
                    groups_by_source = {}
                    for index, fragment in enumerate(model_fragments):
                        groups_by_source.setdefault(fragment.get("_bb_source_index",
                                                                  fragment.get("_source_element_index", index)), []).append(index)
                    result = deploy_collision(str(collision_source), res=8, allow_exposure=True,
                                              include_rotated=True, single_block=True,
                                              collision_groups=list(groups_by_source.values()),
                                              include_indices=indices,
                                              clip_bounds={0: (0.0, 16.0), 1: (0.0, 16.0), 2: (0.0, 16.0)})
                    return result["boxes"], result["metrics"]
                if fragments:
                    selection_boxes, _selection_metrics = build_boxes(fragments, "selection")
                    # The broad canopy sheets are visual eaves. Let them remain
                    # targetable/rendered, but keep their overhang from making
                    # the entire third row a blocking body collider. The ridge
                    # and posts still provide physical support there.
                    collision_fragments = [fragment for fragment in fragments
                                           if not (layer == 2 and fragment.get("_bb_source_index")
                                                   in BOARD_CANOPY_COLLISION_SOURCE_INDICES)]
                    collision_boxes, metrics = build_boxes(collision_fragments, "collision")
                    cell_metrics[key] = metrics or {"air_percent": 0.0, "miss_percent": 0.0,
                        "precision_percent": 100.0, "render_voxels": 0, "collision_voxels": 0,
                        "air_voxels": 0, "miss_voxels": 0, "resolution": 8}
                else:
                    selection_boxes = []
                    collision_boxes = []
                    cell_metrics[key] = {"air_percent": 0.0, "miss_percent": 0.0,
                                         "precision_percent": 100.0, "render_voxels": 0,
                                         "collision_voxels": 0, "air_voxels": 0, "miss_voxels": 0,
                                         "resolution": 8}
                counts[key] = len(collision_boxes)
                report_cells[key] = collision_boxes
                if not selection_boxes:
                    selection_expression = "Shapes.empty()"
                else:
                    terms = [f"Block.box({', '.join(java_number(v) for v in box)})" for box in selection_boxes]
                    selection_expression = "combine(" + ", ".join(terms) + ")"
                if not collision_boxes:
                    expression = "Shapes.empty()"
                else:
                    terms = [f"Block.box({', '.join(java_number(v) for v in box)})" for box in collision_boxes]
                    expression = "combine(" + ", ".join(terms) + ")"
                state_id = layer * 9 + column * 3 + row
                selection_cases.append(f"            case {state_id} -> {selection_expression};")
                collision_cases.append(f"            case {state_id} -> {expression};")

    java = """package com.pastoralhome.block;

import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Generated from the filtered BulletinBoard BBModel with cell-wise collision splitting. */
public final class BulletinBoardCollisionShapes {
    private BulletinBoardCollisionShapes() {}

    public static VoxelShape selectionForState(BlockState state) {
        int id = state.getValue(DecorativeStructureBlock.LAYER) * 9
                + state.getValue(DecorativeStructureBlock.COLUMN) * 3
                + state.getValue(DecorativeStructureBlock.ROW);
        return switch (id) {
""" + "\n".join(selection_cases) + """
            default -> Shapes.empty();
        };
    }

    public static VoxelShape collisionForState(BlockState state) {
        int id = state.getValue(DecorativeStructureBlock.LAYER) * 9
                + state.getValue(DecorativeStructureBlock.COLUMN) * 3
                + state.getValue(DecorativeStructureBlock.ROW);
        return switch (id) {
""" + "\n".join(collision_cases) + """
            default -> Shapes.empty();
        };
    }

    private static VoxelShape combine(VoxelShape... shapes) {
        VoxelShape result = Shapes.empty();
        for (VoxelShape shape : shapes) result = Shapes.or(result, shape);
        return result;
    }
}
"""
    java_path = ROOT / "src/main/java/com/pastoralhome/block/BulletinBoardCollisionShapes.java"
    java_path.write_text(java, encoding="utf-8")
    total_rendered = sum(metrics["render_voxels"] for metrics in cell_metrics.values())
    total_air = sum(metrics["air_voxels"] for metrics in cell_metrics.values())
    report = {
        "grid": expected_grid,
        "source_element_count": len(model.get("elements", [])),
        "cell_mesh_fragment_count": sum(len(elements) for elements in render_cells.values()),
        "collision_policy": "source-element envelopes merged per cell; canopy eaves excluded from third-layer body collision while remaining selectable",
        "canopy_collision_excluded_source_elements": sorted(BOARD_CANOPY_COLLISION_SOURCE_INDICES),
        "air_percent_over_rendered_cells": 100.0 * total_air / total_rendered if total_rendered else 0.0,
        "cell_metrics": cell_metrics,
        "shape_box_counts": counts,
        "cell_boxes": report_cells,
    }
    write(STAGE / "bulletin_board_collision_report.json", report)
    for boxes in report_cells.values():
        for box in boxes:
            if any(value < -1e-6 or value > 16.000001 for value in box):
                raise ValueError(f"bulletin board collision box escaped its own cell: {box}")
    return report


def write_parasol_shape_helper(model: dict, physical_indices: tuple[int, ...] = (1, 12)):
    """Generate full-cell upper hit targets and support-specific lower shapes."""
    selection_groups = ((0, 3, 4, 5), (1, 12), (9, 13), (10, 11), (2,), (6,), (7,), (8,))

    def build_cells(source_model):
        element_bounds = [geometry_bounds({"elements": [element]}) for element in source_model.get("elements", [])]
        def envelope(indices):
            members = [element_bounds[index] for index in indices
                       if index < len(element_bounds) and element_bounds[index] is not None]
            if not members:
                return None
            return tuple(min(bounds[axis] for bounds in members) for axis in range(3)) + tuple(
                max(bounds[axis + 3] for bounds in members) for axis in range(3))
        def clipped_box(bounds, origin, allow_thin):
            values = []
            for axis in range(3):
                cell_min, cell_max = origin[axis], origin[axis] + 16.0
                low = max(float(bounds[axis]), cell_min)
                high = min(float(bounds[axis + 3]), cell_max)
                if high < low - 1e-6:
                    return None
                if high - low < 1e-4:
                    if not allow_thin:
                        return None
                    center = (low + high) * 0.5
                    low = max(cell_min, center - 0.025)
                    high = min(cell_max, center + 0.025)
                values.extend((low - cell_min, high - cell_min))
            return [values[0], values[2], values[4], values[1], values[3], values[5]]
        selection_cells: dict[str, list[list[float]]] = {}
        collision_cells: dict[str, list[list[float]]] = {}
        physical_bounds = envelope(physical_indices)
        for layer in range(2):
            for column in range(3):
                for row in range(3):
                    key = f"{layer},{column},{row}"
                    origin = ((column - 1) * 16.0, layer * 16.0, (row - 1) * 16.0)
                    selected: list[list[float]] = []
                    if layer == 1:
                        # The upper 3×3 layer is a generous hit target, not a
                        # thin sheet outline. Physics collision remains empty.
                        selected.append([0.0, 0.0, 0.0, 16.0, 16.0, 16.0])
                    else:
                        for group in selection_groups:
                            bounds = envelope(group)
                            if bounds is not None:
                                box = clipped_box(bounds, origin, allow_thin=True)
                                if box is not None:
                                    selected.append(box)
                    physical_box = clipped_box(physical_bounds, origin, allow_thin=False) \
                        if physical_bounds and layer == 0 else None
                    physical = [physical_box] if physical_box is not None else []
                    selection_cells[key] = merge_exact_union_boxes(selected)
                    collision_cells[key] = merge_exact_union_boxes(physical)
                    for box in selection_cells[key] + collision_cells[key]:
                        if any(value < -1e-5 or value > 16.00001 for value in box):
                            raise ValueError(f"parasol box escaped cell {key}: {box}")
        return selection_cells, collision_cells

    def cases_for(cells: dict[str, list[list[float]]]) -> str:
        cases = []
        for layer in range(2):
            for column in range(3):
                for row in range(3):
                    key = f"{layer},{column},{row}"
                    index = layer * 9 + column * 3 + row
                    boxes = cells[key]
                    expression = ("combine(" + ", ".join(
                        f"Block.box({', '.join(java_number(value) for value in box)})" for box in boxes
                    ) + ")") if boxes else "Shapes.empty()"
                    cases.append(f"            case {index} -> {expression};")
        return "\n".join(cases)

    base_selection, base_collision = build_cells(model)
    java = '''package com.pastoralhome.block;

import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Generated per-cell from the unchanged authored parasol geometry. */
public final class ParasolCollisionShapes {
    private ParasolCollisionShapes() {}
    private static int id(BlockState state) {
        return state.getValue(DecorativeStructureBlock.LAYER) * 9
                + state.getValue(DecorativeStructureBlock.COLUMN) * 3
                + state.getValue(DecorativeStructureBlock.ROW);
    }
    public static VoxelShape selectionFor(BlockState state) {
        return switch (id(state)) {
''' + cases_for(base_selection) + '''
            default -> Shapes.empty();
        };
    }
    public static VoxelShape collisionFor(BlockState state) {
        return switch (id(state)) {
''' + cases_for(base_collision) + '''
            default -> Shapes.empty();
        };
    }
    private static VoxelShape combine(VoxelShape... shapes) {
        VoxelShape result = Shapes.empty();
        for (VoxelShape shape : shapes) result = Shapes.or(result, shape);
        return result;
    }
}
'''
    (ROOT / "src/main/java/com/pastoralhome/block/ParasolCollisionShapes.java").write_text(java, encoding="utf-8")
    report = {
        "selection_boxes": base_selection,
        "collision_boxes": base_collision,
        "selection_max_boxes_per_cell": max(map(len, base_selection.values())),
        "collision_max_boxes_per_cell": max(map(len, base_collision.values())),
        "selection_policy": "full local-cell targets across the entire second layer; selected from support-mounted geometry",
        "collision_policy": "central mast/hub only in lower layer; entire second layer passes through",
    }
    write(STAGE / "parasol_cell_shapes.json", report)


def write_coat_rack_shape_helper():
    """Keep the two-cell rack's selectable silhouette separate from body collision."""
    selection = {
        0: [[7, 5, 7, 9, 16, 9], [7, 0, 4, 9, 7, 6], [7, 0, 10, 9, 7, 12],
            [4, 0, 7, 6, 7, 9], [10, 0, 7, 12, 7, 9]],
        1: [[7, 0, 7, 9, 15, 9], [3, 2, 7, 13, 5, 9], [7, 3, 2, 9, 11, 14]],
    }
    collision = {
        0: selection[0],
        # Keep the post/cap solid. Hooks and hanging garments are targetable
        # through selectionFor, but they should not form a wide entity collider.
        1: [[7, 0, 7, 9, 11, 9], [6, 11, 6, 10, 15, 10]],
    }

    def cases(shapes):
        rows = []
        for layer in range(2):
            terms = ", ".join(f"Block.box({', '.join(java_number(value) for value in box)})"
                               for box in shapes[layer])
            rows.append(f"            case {layer} -> combine({terms});")
        return "\n".join(rows)

    java = '''package com.pastoralhome.block;

import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Per-cell coat-rack hit outline and body-only entity collision. */
public final class CoatRackCollisionShapes {
    private CoatRackCollisionShapes() {}
    public static VoxelShape selectionFor(BlockState state) {
        return switch (state.getValue(DecorativeStructureBlock.LAYER)) {
''' + cases(selection) + '''
            default -> Shapes.empty();
        };
    }
    public static VoxelShape collisionFor(BlockState state) {
        return switch (state.getValue(DecorativeStructureBlock.LAYER)) {
''' + cases(collision) + '''
            default -> Shapes.empty();
        };
    }
    private static VoxelShape combine(VoxelShape... shapes) {
        VoxelShape result = Shapes.empty();
        for (VoxelShape shape : shapes) result = Shapes.or(result, shape);
        return result;
    }
}
'''
    (ROOT / "src/main/java/com/pastoralhome/block/CoatRackCollisionShapes.java").write_text(java, encoding="utf-8")
    def centered(shapes):
        return {f"{layer},1,1": boxes for layer, boxes in shapes.items()}
    write(STAGE / "coat_rack_cell_shapes.json", {
        "selection_boxes": centered(selection),
        "collision_boxes": centered(collision),
        "selection_max_boxes_per_cell": max(map(len, selection.values())),
        "collision_max_boxes_per_cell": max(map(len, collision.values())),
        "selection_policy": "post, feet and hook arms; upper cell remains independently targetable",
        "collision_policy": "post, feet and top cap only; hooks/clothes do not create an air-heavy body collider",
    })


def write_item(name: str, model_id: str):
    write(ASSETS / "items" / f"{name}.json", {"model": {
        "type": "minecraft:select", "property": "minecraft:display_context",
        "cases": [{"when": "gui", "model": {"type": "minecraft:model", "model": f"pastoral_home:block/{model_id}"}}],
        "fallback": {"type": "minecraft:model", "model": f"pastoral_home:block/{model_id}"}}})


def write_bulletin_page_variants(source_model: dict, display: dict):
    """Recenter source papers and preserve the authored backing-shadow treatment."""
    for directory, pattern in ((ASSETS / "models/item", "bulletin_page_variant_*.json"),
                               (ASSETS / "items", "bulletin_page_variant_*.json"),
                               (ASSETS / "textures/block", "bulletin_page_variant_*_front.png"),
                               (ASSETS / "textures/block", "bulletin_page_variant_*_north.png"),
                               (ASSETS / "textures/block", "bulletin_page_variant_*_south.png")):
        for stale in directory.glob(pattern):
            stale.unlink()
    for directory, pattern in ((ASSETS / "models/item", "bulletin_shadow_variant_*.json"),
                               (ASSETS / "items", "bulletin_shadow_variant_*.json")):
        for stale in directory.glob(pattern):
            stale.unlink()

    specs = []
    shadow_pair = None
    for page_index in PAPER_SOURCE_INDICES:
        page = source_model["elements"][page_index]
        page_dims = [abs(float(page["to"][axis]) - float(page["from"][axis])) for axis in range(3)]
        page_center = [(float(page["from"][axis]) + float(page["to"][axis])) * 0.5 for axis in range(3)]
        page_rotation = page.get("rotation") or {}
        for shadow_index, candidate in enumerate(source_model["elements"]):
            candidate_rotation = candidate.get("rotation") or {}
            if (shadow_index == page_index
                    or candidate_rotation.get("axis") != page_rotation.get("axis")
                    or abs(float(candidate_rotation.get("angle", 0.0))
                           - float(page_rotation.get("angle", 0.0))) > 1.0e-5):
                continue
            shadow_dims = [abs(float(candidate["to"][axis]) - float(candidate["from"][axis])) for axis in range(3)]
            shadow_center = [(float(candidate["from"][axis]) + float(candidate["to"][axis])) * 0.5
                             for axis in range(3)]
            delta = [shadow_center[axis] - page_center[axis] for axis in range(3)]
            if (all(abs(shadow_dims[axis] - page_dims[axis]) <= 0.05 for axis in range(3))
                    and abs(delta[0]) <= 1.0 and abs(delta[1]) <= 1.5
                    and 0.1 <= delta[2] <= 0.35
                    and candidate.get("faces", {}).get("north", {}).get("texture") is not None):
                shadow_pair = (page_index, shadow_index, delta)
                break
        if shadow_pair:
            break
    if shadow_pair is None:
        raise ValueError("could not identify the artist-authored bulletin paper shadow plane")
    paired_page_index, shadow_source_index, shadow_delta = shadow_pair
    shadow_face = copy.deepcopy(source_model["elements"][shadow_source_index]["faces"]["north"])
    write(STAGE / "bulletin_page_shadow_source_report.json", {
        "paired_page_source_element": paired_page_index,
        "shadow_source_element": shadow_source_index,
        "source_offset_pixels": shadow_delta,
        "policy": "project the artist-authored shadow UV onto a flat board-facing plane for every dynamic paper",
    })
    for variant, source_index in enumerate(PAPER_SOURCE_INDICES):
        # Source element 24 is the offset backing-shadow for source paper 4,
        # not a distinct paper silhouette. Keep legacy variant 9 as a safe
        # alias of that authored paper instead of displaying the shadow alone.
        if source_index in FOLDED_STRIP_SOURCE_GROUPS:
            # Two authored cubes form each folded long strip (2+22 and 3+23).
            # Keep old IDs, but every ID renders its complete pair.
            render_source_indices = list(FOLDED_STRIP_SOURCE_GROUPS[source_index])
        else:
            render_source_indices = [paired_page_index if source_index == shadow_source_index else source_index]
        elements = [copy.deepcopy(source_model["elements"][index]) for index in render_source_indices]
        render_source_index = render_source_indices[0]
        bounds = geometry_bounds({"elements": elements})
        if bounds is None:
            raise ValueError(f"bulletin paper element {source_index} has no render bounds")
        center = [(bounds[axis] + bounds[axis + 3]) * 0.5 for axis in range(3)]
        offset = [8.0 - value for value in center]
        for element in elements:
            for point in ("from", "to"):
                element[point] = [float(value) + offset[axis] for axis, value in enumerate(element[point])]
            if element.get("rotation"):
                element["rotation"]["origin"] = [float(value) + offset[axis]
                                                   for axis, value in enumerate(element["rotation"]["origin"])]
        # The source back is blank. Build separate front/back item models so a
        # sheet can be pinned to either board face without flipping its saved side.
        for side, face_name in ((0, "north"), (1, "south")):
            model_id = f"bulletin_page_variant_{variant}_{'front' if side == 0 else 'back'}"
            side_elements = []
            for element in elements:
                front_face = element.get("faces", {}).get("north")
                if front_face is None:
                    raise ValueError(f"bulletin paper element {source_index} has no authored front face")
                side_element = copy.deepcopy(element)
                side_element["faces"] = {face_name: copy.deepcopy(front_face)}
                side_elements.append(side_element)
            page_model = {
                "parent": "minecraft:block/block",
                "textures": copy.deepcopy(source_model["textures"]),
                "elements": side_elements,
                "display": copy.deepcopy(display),
            }
            write(ASSETS / f"models/item/{model_id}.json", page_model)
            write(ASSETS / f"items/{model_id}.json", {"model": {
                "type": "minecraft:select", "property": "minecraft:display_context",
                "cases": [{"when": "gui", "model": {
                    "type": "minecraft:model", "model": f"pastoral_home:item/{model_id}"}}],
                "fallback": {"type": "minecraft:model", "model": f"pastoral_home:item/{model_id}"}}})
            # Reuse the source BB's offset-plane shadow trick for every paper
            # silhouette. Folded pages receive one matching shadow per joined
            # cube, preserving the authored bend and continuous projection.
            shadow_elements = []
            for element in elements:
                shadow_element = copy.deepcopy(element)
                # Project each sheet piece onto one flat board-facing plane.
                # Keep in-plane Z rotation, but remove fold/bend rotations
                # around X/Y so a folded paper's shadow lies on the board.
                rotation = shadow_element.get("rotation")
                if rotation and rotation.get("axis") in ("x", "y"):
                    shadow_element.pop("rotation", None)
                shadow_element["from"][2] = 8.0
                shadow_element["to"][2] = 8.0
                shadow_element["faces"] = {face_name: copy.deepcopy(shadow_face)}
                shadow_elements.append(shadow_element)
            shadow_id = f"bulletin_shadow_variant_{variant}_{'front' if side == 0 else 'back'}"
            write(ASSETS / f"models/item/{shadow_id}.json", {
                "parent": "minecraft:block/block",
                "textures": copy.deepcopy(source_model["textures"]),
                "elements": shadow_elements,
            })
            write(ASSETS / f"items/{shadow_id}.json", {"model": {
                "type": "minecraft:model", "model": f"pastoral_home:item/{shadow_id}"}})
        width, height = bounds[3] - bounds[0], bounds[4] - bounds[1]
        specs.append({"variant": variant, "source_element": source_index,
                      "render_source_element": render_source_index,
                      "render_source_elements": render_source_indices,
                      "width": round(width, 6), "height": round(height, 6),
                      "depth": round(center[2], 6),
                      "rotation": element.get("rotation")})

    widths = ", ".join(f"{spec['width']:.6f}D" for spec in specs)
    heights = ", ".join(f"{spec['height']:.6f}D" for spec in specs)
    depths = ", ".join(f"{spec['depth']:.6f}D" for spec in specs)
    axes = ", ".join(str({None: -1, "x": 0, "y": 1, "z": 2}.get(
        (spec.get("rotation") or {}).get("axis"), -1)) for spec in specs)
    angles = ", ".join(f"{float((spec.get('rotation') or {}).get('angle', 0.0)):.6f}D" for spec in specs)
    java = f'''package com.pastoralhome.block;

import net.minecraft.resources.Identifier;
import java.util.ArrayList;
import java.util.List;

/** Dimensions and item-model keys generated from the original bulletin-board paper planes. */
public final class BulletinPageTemplates {{
    private static final double[] WIDTHS = {{{widths}}};
    private static final double[] HEIGHTS = {{{heights}}};
    private static final double[] DEPTHS = {{{depths}}};
    private static final int[] ROTATION_AXES = {{{axes}}};
    private static final double[] ROTATION_ANGLES = {{{angles}}};
    // One entry per distinct authored silhouette; legacy IDs 7/8/9 remain
    // valid but alias the folded/page models already represented by 0/1/2.
    private static final int[] VISUAL_VARIANTS = {{10, 11, 4, 3, 2, 5, 1, 6, 0}};
    private BulletinPageTemplates() {{}}

    public static int count() {{ return WIDTHS.length; }}
    public static int normalize(int variant) {{ return Math.floorMod(variant, WIDTHS.length); }}
    public static double width(int variant) {{ return WIDTHS[normalize(variant)]; }}
    public static double height(int variant) {{ return HEIGHTS[normalize(variant)]; }}
    public static double depth(int variant) {{ return DEPTHS[normalize(variant)]; }}
    public static int rotationAxis(int variant) {{ return ROTATION_AXES[normalize(variant)]; }}
    public static double rotationAngle(int variant) {{ return ROTATION_ANGLES[normalize(variant)]; }}
    public static double area(int variant) {{ return width(variant) * height(variant); }}
    public static Identifier itemModel(int variant, int side) {{
        return Identifier.fromNamespaceAndPath("pastoral_home", "bulletin_page_variant_" + normalize(variant)
                + (side == 1 ? "_back" : "_front"));
    }}
    public static Identifier shadowItemModel(int variant, int side) {{
        return Identifier.fromNamespaceAndPath("pastoral_home", "bulletin_shadow_variant_" + normalize(variant)
                + (side == 1 ? "_back" : "_front"));
    }}

    public static int choose(String title, String body) {{ return choose(title, body, 0, List.of()); }}
    public static int choose(String title, String body, int variationSalt) {{
        return choose(title, body, variationSalt, List.of());
    }}
    public static double targetAreaForTextLength(int length) {{
        if (length <= 8) return area(10);
        return Math.min(area(0), area(10) + Math.max(0, length) * 0.75D);
    }}
    public static int choose(String title, String body, int variationSalt, List<Integer> existingStyles) {{
        int length = title.codePointCount(0, title.length()) + body.codePointCount(0, body.length());
        double targetArea = targetAreaForTextLength(length);
        double minimumArea = targetArea * 0.78D;
        double maximumArea = targetArea * 1.35D;
        List<Integer> candidates = new ArrayList<>();
        double nearestDifference = Double.POSITIVE_INFINITY;
        for (int variant : VISUAL_VARIANTS) {{
            double difference = Math.abs(area(variant) - targetArea);
            nearestDifference = Math.min(nearestDifference, difference);
            if (area(variant) >= minimumArea && area(variant) <= maximumArea) candidates.add(variant);
        }}
        if (candidates.isEmpty()) {{
            for (int variant : VISUAL_VARIANTS) {{
                if (Math.abs(area(variant) - targetArea) <= nearestDifference + 1.0e-6D) candidates.add(variant);
            }}
        }}
        double bestScore = Double.POSITIVE_INFINITY;
        List<Integer> balanced = new ArrayList<>();
        for (int candidate : candidates) {{
            int uses = 0;
            for (int existing : existingStyles) if (canonical(existing) == candidate) uses++;
            double sizeDifference = Math.abs(area(candidate) - targetArea) / Math.max(1.0D, targetArea);
            int candidateHash = 31 * (31 * title.hashCode() + body.hashCode())
                    + variationSalt + candidate * 0x9E3779B9;
            double variation = Integer.toUnsignedLong(mix(candidateHash)) / (double) 0xFFFFFFFFL * 0.10D;
            double score = sizeDifference * 0.5D + uses * 0.35D + variation;
            if (score < bestScore - 1.0e-9D) {{ bestScore = score; balanced.clear(); }}
            if (Math.abs(score - bestScore) <= 1.0e-9D) balanced.add(candidate);
        }}
        return balanced.get(0);
    }}
    private static int canonical(int variant) {{
        return switch (normalize(variant)) {{
            case 7 -> 0;
            case 8 -> 1;
            case 9 -> 2;
            default -> normalize(variant);
        }};
    }}
    private static int mix(int value) {{
        value ^= value >>> 16;
        value *= 0x7feb352d;
        value ^= value >>> 15;
        value *= 0x846ca68b;
        return value ^ (value >>> 16);
    }}
}}
'''
    (ROOT / "src/main/java/com/pastoralhome/block/BulletinPageTemplates.java").write_text(java, encoding="utf-8")
    write(STAGE / "bulletin_page_variants.json", {"variants": specs})
    shadow_report = read(STAGE / "bulletin_page_shadow_source_report.json")
    shadow_report["generated_shadow_models"] = len(specs) * 2
    write(STAGE / "bulletin_page_shadow_source_report.json", shadow_report)
    write(STAGE / "bulletin_page_shadow_report.json", {
        "shadow_source_element": shadow_index,
        "paired_paper_source_element": paired_page_index,
        "source_offset_pixels": shadow_delta,
        "generated_shadow_models": len(specs) * 2,
        "policy": "flatten paper shadows onto the corresponding board face while reusing the source-authored shadow UV",
    })


def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    block_models = ASSETS / "models/block"
    states = ASSETS / "blockstates"
    coat = import_model("coat_rack")
    assign_particle_from_model_face(coat, "coat_rack", 0, "north", "coat_rack_particle")
    set_item_display(coat, 0.40, 0.28)
    write(block_models / "coat_rack.json", coat)
    write_coat_rack_shape_helper()
    # The authored garments are on the +Z face; a north-facing rack turns them toward the player.
    write(states / "coat_rack.json", layered_rotations("coat_rack", {"north": 180, "east": 270, "south": 0, "west": 90}, 2))
    write_item("coat_rack", "coat_rack")

    parasol = import_model("parasol")
    parasol = transform(parasol, y=2.1844)
    write(STAGE / "parasol_world_model.json", copy.deepcopy(parasol))
    parasol_fence = transform(parasol, y=-2.0)
    write(STAGE / "parasol_fence_world_model.json", copy.deepcopy(parasol_fence))
    set_item_display(parasol, 0.18, 0.11)
    write(block_models / "parasol.json", parasol)
    write(block_models / "parasol_fence.json", parasol_fence)
    parasol_variants = {}
    for face, y in {"north": 0, "east": 90, "south": 180, "west": 270}.items():
        for fence_mounted in (False, True):
            model_id = "parasol_fence" if fence_mounted else "parasol"
            parasol_variants[f"facing={face},fence_mounted={str(fence_mounted).lower()}"] = {
                "model": f"pastoral_home:block/{model_id}", **({"y": y} if y else {})}
    write(states / "parasol.json", {"variants": parasol_variants})
    write_parasol_shape_helper(parasol)
    write_item("parasol", "parasol")

    rug = import_model("rug")
    rug_original_base = copy.deepcopy(rug["elements"][0])
    rug_original_borders = {index: copy.deepcopy(rug["elements"][index]) for index in (7, 8)}
    rug_geometry_report = fit_rug_top_strips_to_single_surface(rug)
    # The outliner labels map to the four edge groups: side tassels and their inner border strips.
    edge_remove = {
        "west": {1, 2, 6, 10}, "east": {3, 4, 5, 9},
        "north": {5, 6, 7}, "south": {8, 9, 10},
    }
    for stale in (ASSETS / "items").glob("rug_surface_*.json"):
        stale.unlink()
    variants = {}
    for mask in range(16):
        active = {face for bit, face in enumerate(("north", "east", "south", "west")) if mask & (1 << bit)}
        removed = set().union(*(edge_remove[face] for face in active)) if active else set()
        variant = copy.deepcopy(rug)
        variant_elements = []
        for index, authored_element in enumerate(rug["elements"]):
            if index in removed:
                continue
            element = copy.deepcopy(authored_element)
            if index in (7, 8):
                # The north/south border strip reaches across a west/east seam
                # only when that side trim is hidden; otherwise the side trim
                # owns the corner and the two top faces meet without overlap.
                element = copy.deepcopy(rug_original_borders[index])
                edge_from, edge_to = list(element["from"]), list(element["to"])
                edge_from[0] = 0.0 if "west" in active else 2.0
                edge_to[0] = 16.0 if "east" in active else 14.0
                crop_element_uv_to_bounds(element, edge_from, edge_to)
            variant_elements.append(element)
        variant["elements"] = variant_elements
        # When an edge strip is hidden by a neighboring rug, extend the main
        # carpet surface to that cell edge. Otherwise the 2px border partition
        # would turn into a visible grass gap at every internal seam.
        base = copy.deepcopy(rug_original_base)
        base_from, base_to = list(base["from"]), list(base["to"])
        base_from[0] = 0.0 if "west" in active else 2.0
        base_to[0] = 16.0 if "east" in active else 14.0
        base_from[2] = 0.0 if "north" in active else 2.0
        base_to[2] = 16.0 if "south" in active else 14.0
        crop_element_uv_to_bounds(base, base_from, base_to)
        variant["elements"][0] = base
        model_id = f"rug_{mask:02x}"
        set_item_display(variant, 0.58, 0.48)
        write(block_models / f"{model_id}.json", variant)
        # The GUI case is owned by normalize_item_icons.py, which runs after this
        # stage and derives one proxy per item id; do not pin it here or the pin is
        # silently overwritten by the full-tree icon pass.
        write(ASSETS / f"items/rug_surface_{mask:02x}.json", {"model": {
            "type": "minecraft:model", "model": f"pastoral_home:block/{model_id}"}})
        key = ",".join(f"{face}={'true' if face in active else 'false'}" for face in ("north", "east", "south", "west"))
        variants[key] = {"model": f"pastoral_home:block/{model_id}"}
    write(block_models / "rug.json", copy.deepcopy(rug))
    write(states / "rug.json", {"variants": variants})
    write_item("rug", "rug")
    rug_bounds = geometry_bounds(rug)
    rug_y_min, rug_y_max = float(rug_bounds[1]), float(rug_bounds[4])
    # The lowest authored point, including fringe, must sit just above the host
    # top. Aligning the highest point hid all lower tassel planes inside the block.
    rug_origin_y = rug_y_min / 16.0
    rug_surface_height = (rug_y_max - rug_y_min) / 16.0
    (ROOT / "src/main/java/com/pastoralhome/block/RugSurfaceTemplates.java").write_text('''package com.pastoralhome.block;

import net.minecraft.resources.Identifier;

/** Item-model selectors for carpet overlays with their artist-authored seam variants. */
public final class RugSurfaceTemplates {
    private static final double SURFACE_ORIGIN_Y = ''' + f"{rug_origin_y:.6f}D" + ''';
    private static final double SURFACE_HEIGHT = ''' + f"{rug_surface_height:.6f}D" + ''';
    private RugSurfaceTemplates() {}
    public static int normalize(int mask) { return mask & 0xF; }
    public static int rotateMaskToLocal(int worldMask, int quarterTurns) {
        int localMask = 0;
        int turns = Math.floorMod(quarterTurns, 4);
        for (int local = 0; local < 4; local++) {
            int world = Math.floorMod(local - turns, 4);
            if ((worldMask & (1 << world)) != 0) localMask |= 1 << local;
        }
        return localMask;
    }
    public static int rotationForFacing(net.minecraft.core.Direction facing) {
        return switch (facing) {
            case NORTH -> 0;
            case WEST -> 1;
            case SOUTH -> 2;
            case EAST -> 3;
            default -> 0;
        };
    }
    public static double surfaceOriginY() { return SURFACE_ORIGIN_Y; }
    public static double surfaceHeight() { return SURFACE_HEIGHT; }
    public static Identifier itemModel(int mask) {
        return Identifier.fromNamespaceAndPath("pastoral_home", "rug_surface_%02x".formatted(normalize(mask)));
    }
}
''', encoding="utf-8")

    board = import_model("bulletin_board")
    # The BBModel atlas contains roof, stone feet, paper pins and wood. Pointing
    # the block's particle at that full atlas makes break fragments randomly
    # sample unrelated parts. Use a coherent wood tile for all board pieces.
    board_texture = Image.open(ASSETS / "textures/block/bulletin_board.png").convert("RGBA")
    board_particle = ASSETS / "textures/block/bulletin_board_particle.png"
    board_texture.crop((0, 32, 16, 48)).save(board_particle)
    board["textures"]["particle"] = "pastoral_home:block/bulletin_board_particle"
    authored_board = copy.deepcopy(board)
    write(STAGE / "bulletin_board_authored_full.json", authored_board)
    source_board = read(SOURCE / "bulletin_board.bbmodel")
    if len(board["elements"]) != len(source_board["elements"]):
        raise ValueError("Bulletin board importer changed element ordering/count; update the source-index filter")
    for stale in block_models.glob("bulletin_board_layer*.json"):
        stale.unlink()
    # The blank board keeps its frame and removes all authored notice planes.
    # The imported model preserves source order, so guard that assumption above.
    # The two colored notes (elements 8 and 9) are small paper templates, not
    # permanent board decoration; remove them from the blank board and include
    # them among the data-bearing pages generated below.
    notice_plane_indices = {2, 3, 4, 5, 6, 7, 8, 9, 10, 22, 23, 24}
    for source_index, element in enumerate(board["elements"]):
        element["_bb_source_index"] = source_index
    board["elements"] = [e for i, e in enumerate(board["elements"])
                         if i not in notice_plane_indices and i != 1]
    # The artist baked the pin-head colors into the front-board atlas tile.
    # A blank notice board must not look pre-pinned, so reuse the clean wood
    # tile from the reverse face for the visible north/front face.
    board["elements"][0]["faces"]["north"]["uv"] = copy.deepcopy(board["elements"][0]["faces"]["south"]["uv"])
    # Keep the model's authored center at the clicked anchor (x/z=8px). The
    # previous +3z nudge aligned one edge to a grid plane and shifted the whole
    # freestanding structure off-center; centered roof overhangs need cells on
    # both sides of the anchor row.
    board = transform(board, y=16, z=0)
    write(STAGE / "bulletin_board_world.json", board)
    write(STAGE / "bulletin_board_collision_source.json", board)
    split_cells, split_warnings = split_model(board, with_source_index=True)

    # Clip ordinary cuboids to block-grid cells and crop their face UVs. This
    # keeps a 3-block writing panel split into three real render/break pieces;
    # the old center-of-element assignment put the entire panel in one cell.
    cell_models = {(layer, column, row): []
                   for layer in range(3) for column in range(3) for row in range(3)}
    for (dx, dy, dz), elements in split_cells.items():
        # The roof overhang spans the front and back depth rows, but those
        # rows must stay free for adjacent placement. Render their roof pieces
        # from the retained center-row cells using off-cell model coordinates.
        render_dz = 0 if dy == 2 and dz != 0 else dz
        if render_dz != dz:
            z_shift = dz * 16.0
            for element in elements:
                for point in ("from", "to"):
                    element[point][2] += z_shift
                if element.get("rotation"):
                    element["rotation"]["origin"][2] += z_shift
        column, row = dx + 1, render_dz + 1
        if not (0 <= column < 3 and 0 <= dy < 3 and 0 <= row < 3):
            raise ValueError(f"bulletin board fragment was assigned outside its 3×3×3 structure: {(dx, dy, dz)}")
        cell_models[(dy, column, row)].extend(elements)
    # Build each block's VoxelShape from only the mesh pieces rendered by that
    # block. This keeps the selection outline aligned with the occupied model
    # cells instead of wrapping the whole notice board in one oversized box.
    collision_render_cells = {(column - 1, layer, row - 1): elements
                              for (layer, column, row), elements in cell_models.items()}
    collision_report = write_board_collision_helper(board, collision_render_cells)
    collision_report["rotated_element_cell_crossings"] = split_warnings
    write(STAGE / "bulletin_board_model_split_report.json", {
        "render_elements_by_cell": {f"{layer},{column},{row}": len(elements)
                                    for (layer, column, row), elements in cell_models.items()},
        "source_elements_in_world_model": sorted({
            element.get("_bb_source_index") for elements in cell_models.values()
            for element in elements if element.get("_bb_source_index") is not None}),
        "paper_template_source_elements": sorted(COLOR_NOTE_SOURCE_INDICES),
        "canopy_collision_excluded_source_elements": sorted(BOARD_CANOPY_COLLISION_SOURCE_INDICES),
        "rotated_element_cell_crossings": split_warnings,
        "placement_center_px": [8.0, 8.0],
    })
    for (layer, column, row), elements in cell_models.items():
        part = copy.deepcopy(board)
        part["elements"] = [{key: value for key, value in element.items()
                              if key not in {"_source_element_index", "_bb_source_index"}}
                             for element in elements]
        model_id = f"bulletin_board_l{layer}_c{column}_r{row}"
        write(block_models / f"{model_id}.json", part)

    # Keep a compact, single-piece item preview. World rendering uses the
    # localized layer models above; scaling geometry here also satisfies the
    # same model coordinate limits as vanilla items.
    icon = copy.deepcopy(board)
    for element in icon["elements"]:
        for point in ("from", "to"):
            for axis in range(3):
                element[point][axis] = 8 + (element[point][axis] - 8) * 0.32
        if element.get("rotation"):
            for axis in range(3):
                element["rotation"]["origin"][axis] = 8 + (element["rotation"]["origin"][axis] - 8) * 0.32
    set_item_display(icon, 0.76, 0.48)
    write(block_models / "bulletin_board.json", icon)

    # Blockbench's front view looks along -Z; north-facing uses the authored orientation.
    angles = {"north": 0, "east": 90, "south": 180, "west": 270}
    variants = {}
    for (layer, column, row) in cell_models:
        model_id = f"bulletin_board_l{layer}_c{column}_r{row}"
        for face, y in angles.items():
            variants[f"facing={face},layer={layer},column={column},row={row}"] = {
                "model": f"pastoral_home:block/{model_id}", **({"y": y} if y else {})}
    write(states / "bulletin_board.json", {"variants": variants})
    write_item("bulletin_board", "bulletin_board")

    page_faces = {face: {"uv": [0, 0, 16, 16], "texture": "#layer0"}
                  for face in ("north", "south", "east", "west", "up", "down")}
    page_display = {
        "gui": {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [0.58, 0.58, 0.58]},
        "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [0.45, 0.45, 0.45]},
        "firstperson_righthand": {"rotation": [0, 225, 0], "translation": [0, 1, 0], "scale": [0.4, 0.4, 0.4]},
        "firstperson_lefthand": {"rotation": [0, 45, 0], "translation": [0, 1, 0], "scale": [0.4, 0.4, 0.4]},
        "thirdperson_righthand": {"rotation": [0, 45, 0], "translation": [0, 2, 0], "scale": [0.35, 0.35, 0.35]},
        "thirdperson_lefthand": {"rotation": [0, 225, 0], "translation": [0, 2, 0], "scale": [0.35, 0.35, 0.35]},
        "fixed": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
    }
    write_bulletin_page_variants(authored_board, page_display)
    # The hand-held data-bearing paper uses the same first artist-authored page
    # plane as the board templates, rather than a separately fabricated sheet.
    # Give the plain bulletin-page item a BB-authored colored-note silhouette;
    # data-bearing stacks replace this with their saved style.
    authored_page = read(ASSETS / "models/item/bulletin_page_variant_10_front.json")
    authored_page["display"] = {
        "gui": {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [1.0, 1.0, 1.0]},
        "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [0.7, 0.7, 0.7]},
        "fixed": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1.0, 1.0, 1.0]},
        "firstperson_righthand": {"rotation": [0, 225, 0], "translation": [0, 1, 0], "scale": [0.8, 0.8, 0.8]},
        "firstperson_lefthand": {"rotation": [0, 45, 0], "translation": [0, 1, 0], "scale": [0.8, 0.8, 0.8]},
        "thirdperson_righthand": {"rotation": [0, 45, 0], "translation": [0, 2, 0], "scale": [0.7, 0.7, 0.7]},
        "thirdperson_lefthand": {"rotation": [0, 225, 0], "translation": [0, 2, 0], "scale": [0.7, 0.7, 0.7]},
    }
    write(ASSETS / "models/item/bulletin_page.json", authored_page)
    write(ASSETS / "items/bulletin_page.json", {"model": {
        "type": "minecraft:select", "property": "minecraft:display_context",
        "cases": [{"when": "gui", "model": {"type": "minecraft:model", "model": "pastoral_home:item/bulletin_page"}}],
        "fallback": {"type": "minecraft:model", "model": "pastoral_home:item/bulletin_page"}}})
    write(ASSETS / "font/notebook.json", {"providers": [
        {"type": "ttf", "file": "pastoral_home:lxgw_wenkai_lite_regular.ttf",
         "size": 10.0, "oversample": 2.0, "shift": [0.0, 0.0]},
        {"type": "reference", "id": "minecraft:default"}
    ]})
    write(ASSETS / "font/notebook_title.json", {"providers": [
        {"type": "ttf", "file": "pastoral_home:lxgw_wenkai_lite_regular.ttf",
         "size": 12.0, "oversample": 2.0, "shift": [0.0, 0.0]},
        {"type": "reference", "id": "minecraft:default"}
    ]})

    # Keep generated language resources in sync without rewriting unrelated entries.
    names = {"en_us": {"coat_rack": "Coat Rack", "parasol": "Parasol", "rug": "Rug", "bulletin_board": "Bulletin Board",
                        "item.pastoral_home.rug": "Rug", "entity.pastoral_home.rug_surface": "Rug Surface",
                        "bulletin_page": "Pinned Notice", "container.pastoral_home.bulletin_board": "Bulletin Board · Pinned Notices",
                        "gui.pastoral_home.notice.title": "A Note for the Board", "gui.pastoral_home.notice.heading": "Title",
                        "gui.pastoral_home.notice.body": "Your note", "gui.pastoral_home.notice.author": "By %s",
                        "gui.pastoral_home.notice.read_only": "Pinned by %s", "gui.pastoral_home.notice.save": "Save",
                        "gui.pastoral_home.notice.pin": "Pin",
                        "gui.pastoral_home.notice.cancel": "Cancel", "gui.pastoral_home.notice.close": "Close",
                        "gui.pastoral_home.notice.blank": "Write a few kind words…", "gui.pastoral_home.notice.saving": "Saving…",
                        "gui.pastoral_home.notice.error.empty": "Write something before pinning.",
                        "gui.pastoral_home.notice.error.spectator": "Spectators cannot pin notices.",
                        "gui.pastoral_home.notice.error.unavailable": "That paper position is no longer available.",
                        "gui.pastoral_home.notice.error.board_full": "There is no room for another sheet in this area.",
                        "gui.pastoral_home.notice.error.paper_missing": "Keep a sheet of paper in your hand to pin this.",
                        "gui.pastoral_home.notice.error.slot_taken": "Someone filled this paper position.",
                        "gui.pastoral_home.notice.error.not_owner": "Only the author can revise this notice.",
                        "gui.pastoral_home.notice.error.changed": "This notice changed while you were editing; reopen it to continue.",
                        "gui.pastoral_home.notice.error.page_missing": "That notice sheet is no longer in your hand.",
                        "message.pastoral_home.rug.unsupported_surface": "A rug needs a full, level support surface.",
                        "tooltip.pastoral_home.bulletin_page.author": "Written by %s",
                        "tooltip.pastoral_home.bulletin_page.edit": "Right-click to reread or revise"},
             "zh_cn": {"coat_rack": "衣帽架", "parasol": "遮阳伞", "rug": "地毯", "bulletin_board": "公告栏",
                        "item.pastoral_home.rug": "地毯", "entity.pastoral_home.rug_surface": "地毯",
                        "bulletin_page": "张贴公告", "container.pastoral_home.bulletin_board": "公告栏 · 张贴内容",
                        "gui.pastoral_home.notice.title": "写一张公告", "gui.pastoral_home.notice.heading": "标题",
                        "gui.pastoral_home.notice.body": "写下想说的话", "gui.pastoral_home.notice.author": "作者：%s",
                        "gui.pastoral_home.notice.read_only": "%s 张贴", "gui.pastoral_home.notice.save": "保存",
                        "gui.pastoral_home.notice.pin": "张贴",
                        "gui.pastoral_home.notice.cancel": "取消", "gui.pastoral_home.notice.close": "合上",
                        "gui.pastoral_home.notice.blank": "写下几句温柔的话……", "gui.pastoral_home.notice.saving": "正在保存……",
                        "gui.pastoral_home.notice.error.empty": "请先写下内容。",
                        "gui.pastoral_home.notice.error.spectator": "旁观者不能张贴公告。",
                        "gui.pastoral_home.notice.error.unavailable": "这个纸位已不可用。",
                        "gui.pastoral_home.notice.error.board_full": "这个位置附近已经没有空隙了。",
                        "gui.pastoral_home.notice.error.paper_missing": "请手持一张纸再进行张贴。",
                        "gui.pastoral_home.notice.error.slot_taken": "这个纸位已被其他玩家占用。",
                        "gui.pastoral_home.notice.error.not_owner": "只有作者可以修改这条公告。",
                        "gui.pastoral_home.notice.error.changed": "你编辑期间这条公告已发生变化，请重新打开后再修改。",
                        "gui.pastoral_home.notice.error.page_missing": "手中的公告纸已不在了。",
                        "message.pastoral_home.rug.unsupported_surface": "地毯需要完整、平整的承托面。",
                        "tooltip.pastoral_home.bulletin_page.author": "作者：%s",
                        "tooltip.pastoral_home.bulletin_page.edit": "右键重新阅读或修改"}}
    for locale, entries in names.items():
        lang_path = ROOT / f"src/generated/resources/assets/pastoral_home/lang/{locale}.json"
        lang = read(lang_path)
        for key, value in entries.items():
            if key.startswith(("item.", "container.", "entity.", "gui.", "tooltip.", "message.")):
                lang[key] = value
            else:
                lang[f"block.pastoral_home.{key}"] = value
        write(lang_path, lang, newline="\n")

    # Loot tables for these blocks come from ModBlockLootProvider, which reads the anchor cell off
    # the block itself. Hand-writing them here would let the two copies drift (parasol pointed at
    # row 0 while the block anchors on row 1, so it dropped nothing at all).

    icon_items = "coat_rack,parasol,rug,bulletin_board"
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/normalize_item_icons.py"),
                    "--apply", "--items", icon_items,
                    "--report", str(STAGE / "item_icon_normalization_report.json")], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_item_icons.py"),
                    "--items", icon_items, "--output",
                    str(STAGE / "item_icons.png"), "--report", str(STAGE / "item_icons.json"),
                    "--columns", "4"], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_item_icons.py"),
                    "--items", "bulletin_page", "--output",
                    str(STAGE / "bulletin_page_item_preview.png"), "--report",
                    str(STAGE / "bulletin_page_item_preview.json"), "--columns", "1"], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_multiblock_collision.py"),
                    "--model", str(STAGE / "bulletin_board_world.json"),
                    "--report", str(STAGE / "bulletin_board_collision_report.json"),
                    "--output", str(STAGE / "bulletin_board_collision_preview.png")], check=True)
    # parasol_fence is a real blockstate variant (the fence-mounted pose), so it needs its own
    # preview. It reuses the ground pose's cell shapes on purpose: the mounted model is the same
    # geometry shifted two pixels, so ParasolBlock derives one shape table for both.
    for model_id, report_id in (("coat_rack", "coat_rack"), ("parasol", "parasol"),
                                ("parasol_fence", "parasol")):
        subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_multiblock_collision.py"),
                        "--model", str(block_models / f"{model_id}.json"),
                        "--report", str(STAGE / f"{report_id}_cell_shapes.json"),
                        "--output", str(STAGE / f"{model_id}_collision_preview.png")], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_bulletin_notice_screen.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_bulletin_posted_pages.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/deploy/preview_bulletin_page_variants.py")], check=True)
    print("Prepared entryway assets, cell-split hit/collision previews, notice UI, posted pages and typography checks.")


if __name__ == "__main__":
    main()
