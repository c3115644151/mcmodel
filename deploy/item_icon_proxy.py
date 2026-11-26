"""Build GUI-only item models normalized to Minecraft's one-block model space."""
from __future__ import annotations

import copy
import json
import math
from itertools import product
from pathlib import Path
from typing import Any

from gui_measure import apply_rotation, corners, project_iso


# The single authoritative GUI display for a block-shaped item: assets/minecraft/models/block/block.json.
# Every proxy inherits it unchanged. Yaw 225 looks at a model's -Z (front) and +X sides,
# which is the three-quarter view vanilla uses; yaw 45 shows the back face.
VANILLA_BLOCK_GUI = {
    "rotation": [30.0, 225.0, 0.0],
    "translation": [0.0, 0.0, 0.0],
    "scale": [0.625, 0.625, 0.625],
}
# Art decision recorded by the generator next to the project so validators read one
# expectation instead of recomputing their own (a stale recomputation is what made
# facing-aware items 42 degrees off after the GUI camera convention changed).
ITEM_ICON_MANIFEST = "item_icons_manifest.json"
# Vanilla models used only to carry a display transform inside a composite GUI model.
TRANSFORM_CARRIER_MODELS = frozenset({"minecraft:block/block"})
TARGET_BLOCK_SIZE = 16.0
MAX_PROJECTED_ICON_PIXELS = 15.74
GUI_ICON_TARGET_PX = 15.7
"""Visible long edge of a full-block GUI icon in slot pixels (16px slot).

This is the measured size of a vanilla full block / furnace GUI icon: the
[30,225,0] isometric projection of a 16x16x16 block at scale 0.625 spans
~15.7px, i.e. it nearly touches the 16px slot edge. A block-sized model is
fitted to this edge; a genuinely smaller model gets a proportional target
via ``gui_icon_target_px`` so it is not inflated to a full slot.
"""
# 满格方块经 GUI 相机投影后的可见下边缘(投影单位, 未乘 0.625 scale)。
# 矮模型(<1格)贴底时把可见下边缘对齐到这里, 等于原版地毯的贴地表现。
GUI_FLOOR_Y = 12.5625


def gui_icon_target_px(source_longest: float) -> float:
    """Honest GUI target: full vanilla edge for >=1 block, proportional below.

    ``normalize_to_block`` inflates every model to a one-block AABB, so fitting
    every proxy to the full 15.7px edge erased the real size difference between
    a one-block wardrobe and a half-block teacup. The source model's original
    longest AABB edge is its true size class in block units: a 5-unit teacup is
    31% of a block and should read as ~31% of the vanilla icon edge. Above one
    block we cap at 1.0 so multi-block models stay at the vanilla edge instead
    of overflowing the slot.
    """
    if source_longest <= 0:
        return GUI_ICON_TARGET_PX
    ratio = min(1.0, source_longest / TARGET_BLOCK_SIZE)
    return round(GUI_ICON_TARGET_PX * ratio, 4)


def rotate_relative_to_vanilla_gui(point, rotation):
    """Apply only the item's yaw difference; the GUI camera pitch stays level."""
    rotation = rotation or VANILLA_BLOCK_GUI["rotation"]
    yaw_delta = float(rotation[1]) - float(VANILLA_BLOCK_GUI["rotation"][1])
    return apply_rotation(point, [0.0, yaw_delta, 0.0], [8.0, 8.0, 8.0])


def rotate_for_display(point, rotation):
    """Full display rotation, pitch included: the offline views must not bake 30 degrees in."""
    """Rotate a point by the difference between an authored display transform and
    the vanilla GUI camera the shared projection is built around (pitch 30, yaw 225).

    Yaw alone was not enough: a painter that only applies the yaw difference keeps
    the vanilla camera elevation, so an authored level camera (pitch 0) still drew
    the model's top faces at 30 degrees and a low camera hid nothing. Every preview
    of a firstperson/thirdperson/gui transform has to move the elevation too.
    """
    rotation = rotation or VANILLA_BLOCK_GUI["rotation"]
    pitch_delta = float(rotation[0]) - float(VANILLA_BLOCK_GUI["rotation"][0])
    yaw_delta = float(rotation[1]) - float(VANILLA_BLOCK_GUI["rotation"][1])
    return apply_rotation(point, [pitch_delta, yaw_delta, 0.0], [8.0, 8.0, 8.0])


def geometry_bounds(model: dict[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    points = corners(model)
    if not points:
        return None
    return (
        min(p[0] for p in points), min(p[1] for p in points), min(p[2] for p in points),
        max(p[0] for p in points), max(p[1] for p in points), max(p[2] for p in points),
    )


def geometry_fingerprint(model: dict[str, Any]):
    """Stable element-corner fingerprint shared by exported JSON and bbmodel."""
    elements = []
    for element in model.get("elements", []):
        low, high = element.get("from"), element.get("to")
        if not low or not high:
            continue
        points = []
        for x, y, z in product((low[0], high[0]), (low[1], high[1]), (low[2], high[2])):
            point = (x, y, z)
            rotation = element.get("rotation")
            if rotation:
                point = apply_rotation(point, rotation, element.get("origin"))
            points.append(tuple(round(float(value), 3) for value in point))
        elements.append(tuple(sorted(points)))
    return tuple(sorted(elements))


def index_bbmodel_gui_transforms(source_directories: list[Path]):
    """Index only exact geometry matches; ambiguous matches are discarded."""
    candidates: dict[tuple, list[tuple[Path, dict]]] = {}
    for directory in source_directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.bbmodel"):
            try:
                model = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            gui = model.get("display", {}).get("gui")
            fingerprint = geometry_fingerprint(model)
            if fingerprint:
                candidates.setdefault(fingerprint, []).append((path, gui))
    return {
        fingerprint: entries[0]
        for fingerprint, entries in candidates.items()
        if len(entries) == 1 and isinstance(entries[0][1], dict)
    }


def normalize_to_block(model: dict[str, Any], target_size: float = TARGET_BLOCK_SIZE,
                       reference_bounds: tuple[float, float, float, float, float, float] | None = None):
    """Fit geometry to one block so the icon reads at the size a block item does.

    All three axes center on the block center. A model that fills the slot height
    lands exactly on the slot floor either way, but a flat icon (a rug, a parasol
    canopy) measured 3-4 icon pixels below the slot centre while it was floored,
    which is what the entryway icon gate reported. The longest AABB side is scaled
    to 16 model units in both directions:
    a multiblock wardrobe shrinks, a teacup grows. Vanilla block items are exactly
    one block and draw at their true size, so matching one block is what makes
    every furniture icon the same visual weight in the slot; leaving small pieces
    at authored scale is what made them unreadable. The GUI display is
    minecraft:block/block's own, so Minecraft places the icon. Face UVs and
    texture references are untouched.
    """
    if target_size <= 0:
        raise ValueError("target_size must be positive")
    source_bounds = geometry_bounds(model)
    if source_bounds is None:
        return None
    bounds = reference_bounds or source_bounds
    minimum, maximum = bounds[:3], bounds[3:]
    spans = [maximum[i] - minimum[i] for i in range(3)]
    longest = max(spans)
    if longest <= 1e-8:
        return None
    scale = target_size / longest
    center_x = (minimum[0] + maximum[0]) * 0.5
    center_y = (minimum[1] + maximum[1]) * 0.5
    center_z = (minimum[2] + maximum[2]) * 0.5

    def transform_point(point):
        return [round((point[0] - center_x) * scale + 8.0, 6),
                round((point[1] - center_y) * scale + 8.0, 6),
                round((point[2] - center_z) * scale + 8.0, 6)]

    result = copy.deepcopy(model)
    for element in result.get("elements", []):
        element["from"] = transform_point(element["from"])
        element["to"] = transform_point(element["to"])
        if "origin" in element:
            element["origin"] = transform_point(element["origin"])
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and "origin" in rotation:
            rotation["origin"] = transform_point(rotation["origin"])

    gui = copy.deepcopy(VANILLA_BLOCK_GUI)
    # Vanilla's 0.625 stays fixed: the mesh is already one block, so this is the
    # same camera and scale a vanilla block item uses. slot_cap below is only a
    # safety net for a projected outline that still reaches past the slot.
    gui_scale = list(VANILLA_BLOCK_GUI["scale"])
    result["display"] = {"gui": gui}
    final_bounds = geometry_bounds(result)
    if final_bounds is None:
        return None
    projected = []
    for point in corners(result):
        view_point = rotate_relative_to_vanilla_gui(point, gui["rotation"])
        projected.append(project_iso(((view_point[0] - 8.0) * gui_scale[0],
                                      (view_point[1] - 8.0) * gui_scale[1],
                                      (view_point[2] - 8.0) * gui_scale[2])))
    projected_extent = max((abs(value) for point in projected for value in point), default=0.0)
    slot_cap = min(1.0, (MAX_PROJECTED_ICON_PIXELS * 0.5) / projected_extent) if projected_extent else 1.0
    gui_scale = [value * slot_cap for value in gui_scale]
    gui["scale"] = [round(value, 6) for value in gui_scale]
    result["display"]["gui"] = gui
    return {
        "model": result,
        "scale": scale,
        "gui_scale": gui_scale,
        "source_bounds": source_bounds,
        "normalization_bounds": bounds,
        "final_bounds": final_bounds,
        "target_size": target_size,
    }


def fit_gui_projection(model: dict[str, Any], texture_resolver,
                       target_px: float = GUI_ICON_TARGET_PX,
                       floor_anchor: bool = False):
    """Fit an icon by its texture-visible GUI projection, not its 3D AABB.

    ``normalize_to_block`` scales by the longest axis-aligned edge, but Minecraft
    draws a 30-degree isometric projection. A flat parasol and a tall clock can
    share an AABB edge and still render at wildly different sizes; an asymmetric
    brazier can project well off-centre. This pass measures the alpha-visible
    projection in the vanilla GUI camera, scales the geometry so its longest
    visible edge reaches ``target_px`` slot pixels, then translates the geometry
    so the visible centroid sits at slot centre. Geometry-space translation is
    used rather than ``display.gui.translation`` because Minecraft applies that
    translation *before* the GUI rotation: a y translation moves the icon up
    less than its raw value, while x/z translations are rotated into the screen.

    ``texture_resolver`` maps a texture reference to a PNG path; it is the same
    resolver the preview and gates use, so the fit and the measurement agree.

    ``floor_anchor`` puts the visible bottom edge on the vanilla full-block
    slot floor instead of the slot centre. Models shorter than one block do not
    reach the slot's top/bottom edges, so like a vanilla carpet (modelled at
    y=0..1 with no GUI translation) their icon should sit on the slot floor,
    not float in the middle. Only the vertical target changes; x stays centred.
    """
    from item_icon_preview import visible_projected_measurements

    measured = visible_projected_measurements(
        model, texture_resolver, pixels_per_unit=16)
    if measured is None:
        return None
    bounds = measured["bounds"]
    longest = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    if longest <= 1e-8:
        return None

    # The projected size is measured before GUI scale (0.625), so convert the
    # target slot pixels back into projected model units.
    gui_scale = float(VANILLA_BLOCK_GUI["scale"][0])
    target_units = target_px / gui_scale
    # Unlike normalize_to_block, this pass sizes by what is actually visible:
    # every icon, flat or tall, lands on the same visible long edge so the slot
    # reads consistently. The geometry is checked against the model-format bounds
    # after scaling and stepped back if the fitted shape would overflow them.
    scale = target_units / longest

    fitted = copy.deepcopy(model)
    def scale_point(point):
        return [round(8.0 + (value - 8.0) * scale, 6) for value in point]
    def transform_element(element, transform):
        for key in ("from", "to", "origin"):
            if key in element:
                element[key] = transform(element[key])
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and "origin" in rotation:
            rotation["origin"] = transform(rotation["origin"])
    for element in fitted.get("elements", []):
        transform_element(element, scale_point)

    after_scale = visible_projected_measurements(
        fitted, texture_resolver, pixels_per_unit=16)
    if after_scale is None:
        return None
    bounds = after_scale["bounds"]
    centre_x = (bounds[0] + bounds[2]) * 0.5
    centre_y = (bounds[1] + bounds[3]) * 0.5

    # Undo the GUI projection of a centred offset. Camera [30,225,0] projects
    # sx = cos45*(x+z), sy = -(cos30*y - sin30*(x-z)/sqrt2). Choosing dx=dz
    # cancels x-z in sy (so the sin30 term is unchanged) and adds 2*dx along
    # x+z in sx: dx=dz=-cx/(2cos45) zeroes sx, dy=cy/cos30 zeroes sy.
    cos45 = math.cos(math.radians(45.0))
    cos30 = math.cos(math.radians(30.0))
    dx = -centre_x / (2.0 * cos45)
    dz = dx
    if floor_anchor:
        # 矮模型贴地: 把可见下边缘(bounds[3], 屏幕 y 越大越靠下)移到满格
        # 方块的槽底。sy = -(cos30*y - sin30*(x-z)/sqrt2), 屏幕下移 delta
        # 需要 y 反向变化: dy = (bounds[3] - FLOOR_Y)/cos30。x 仍居中。
        dy = (bounds[3] - GUI_FLOOR_Y) / cos30
    else:
        dy = centre_y / cos30

    def recenter_point(point):
        return [round(point[0] + dx, 6),
                round(point[1] + dy, 6),
                round(point[2] + dz, 6)]
    for element in fitted.get("elements", []):
        transform_element(element, recenter_point)

    fitted.setdefault("display", {})["gui"] = copy.deepcopy(VANILLA_BLOCK_GUI)
    final = visible_projected_measurements(
        fitted, texture_resolver, pixels_per_unit=16)
    if final is None:
        return None

    # Rasterisation rounds the recentred silhouette to whole texels, so a
    # perfectly solved centre can measure ~0.1px off. One correction pass with
    # the residual removes that bias. Use the visible-alpha bounding-box centre
    # here, the same measure the first pass used, so both passes agree on what
    # "centred" means; the alpha-weighted centre would fight it on asymmetric
    # shapes (a lamp with a heavy base and a thin stem, for example).
    final_box = final["bounds"]
    residual_x = (final_box[0] + final_box[2]) * 0.5
    if floor_anchor:
        residual_y = final_box[3] - GUI_FLOOR_Y
    else:
        residual_y = (final_box[1] + final_box[3]) * 0.5
    if abs(residual_x) > 1e-4 or abs(residual_y) > 1e-4:
        rx = -residual_x / (2.0 * cos45)
        rz = rx
        ry = -residual_y / cos30 if floor_anchor else residual_y / cos30
        def refine(point):
            return [round(point[0] + rx, 6),
                    round(point[1] + ry, 6),
                    round(point[2] + rz, 6)]
        for element in fitted.get("elements", []):
            transform_element(element, refine)
        final = visible_projected_measurements(
            fitted, texture_resolver, pixels_per_unit=16)
        if final is None:
            return None

    final_bounds = geometry_bounds(fitted)
    if final_bounds is None:
        return None
    return {
        "model": fitted,
        "fit_scale": scale,
        "fit_source_bounds": tuple(round(value, 6) for value in bounds),
        "fit_final_bounds": tuple(round(value, 6) for value in final_bounds),
        "fit_projected_bounds": tuple(round(value, 6) for value in final["bounds"]),
        "fit_projected_size": (
            round((final["bounds"][2] - final["bounds"][0]) * gui_scale, 4),
            round((final["bounds"][3] - final["bounds"][1]) * gui_scale, 4)),
        "fit_center": tuple(round(value * gui_scale, 4) for value in final["center"]),
    }


def collect_model_ids(model_node: Any) -> list[str]:
    ids = []

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "minecraft:model" and isinstance(node.get("model"), str):
                ids.append(node["model"])
            # `model` is a resource ID only on minecraft:model nodes. On select,
            # condition and fallback nodes it is a nested model tree and must be
            # traversed; skipping it hid the actual GUI branch from both the
            # normalizer and its preview.
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(model_node)
    return list(dict.fromkeys(ids))


def replace_model_ids(model_node: Any, replacements: dict[str, str]) -> Any:
    result = copy.deepcopy(model_node)

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "minecraft:model" and node.get("model") in replacements:
                node["model"] = replacements[node["model"]]
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


def unwrap_generated_gui_select(model_node: Any, mod_id: str) -> Any:
    """Restore only prior GUI proxy references to their source models.

    The GUI model may intentionally differ from the held/world fallback (for
    example, a framed wall painting shows a front-facing sample in inventory).
    Returning only the fallback made a second normalization silently replace
    that authored GUI choice with the world model.
    """
    if not isinstance(model_node, dict) or model_node.get("type") != "minecraft:select":
        return model_node
    if model_node.get("property") != "minecraft:display_context":
        return model_node
    cases = model_node.get("cases", [])
    gui_case = next((case for case in cases if case.get("when") in ("gui", ["gui"])), None)
    if gui_case is None or "fallback" not in model_node:
        return model_node
    gui_ids = collect_model_ids(gui_case.get("model", {}))
    if not gui_ids or not any(model_id.startswith(f"{mod_id}:item_icons/") for model_id in gui_ids):
        return model_node

    assets_root = Path.cwd() / "src/main/resources/assets" / mod_id
    replacements = {}
    for proxy_id in gui_ids:
        if not proxy_id.startswith(f"{mod_id}:item_icons/"):
            continue
        proxy_path = assets_root / "models" / f"{proxy_id.split(':', 1)[1]}.json"
        if not proxy_path.is_file():
            continue
        try:
            parent = json.loads(proxy_path.read_text(encoding="utf-8")).get("parent")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(parent, str) and parent:
            replacements[proxy_id] = parent
    if not replacements:
        return model_node["fallback"]
    result = copy.deepcopy(model_node)
    case_index = next(index for index, case in enumerate(cases) if case is gui_case)
    result["cases"][case_index]["model"] = replace_model_ids(
        result["cases"][case_index].get("model", {}), replacements)
    if result["cases"][case_index]["model"] == result["fallback"]:
        return result["fallback"]
    return result


def wrap_gui_only(gui_model_node: Any, original_model_node: Any) -> dict[str, Any]:
    return {
        "type": "minecraft:select",
        "property": "minecraft:display_context",
        "cases": [{"when": "gui", "model": gui_model_node}],
        "fallback": copy.deepcopy(original_model_node),
    }


def replace_gui_case_model_ids(model_node: Any, replacements: dict[str, str],
                               carrier_replacement: Any | None = None) -> Any:
    """Replace only existing GUI-context model references; leave hand/world fallback intact.

    A GUI case built from a transform carrier alone has no geometry, so the item shows
    an empty slot. The generated proxy of the fallback model takes over that case;
    without one the carrier stays and the validator keeps reporting it.
    """
    result = copy.deepcopy(model_node)
    if not isinstance(result, dict) or result.get("type") != "minecraft:select" \
            or result.get("property") != "minecraft:display_context":
        return replace_model_ids(result, replacements)
    for case in result.get("cases", []):
        if case.get("when") in ("gui", ["gui"]):
            case_ids = collect_model_ids(case.get("model", {}))
            if carrier_replacement is not None and case_ids \
                    and all(model_id in TRANSFORM_CARRIER_MODELS for model_id in case_ids):
                case["model"] = copy.deepcopy(carrier_replacement)
                continue
            case["model"] = replace_model_ids(case.get("model", {}), replacements)
    return result
