#!/usr/bin/env python3
"""GUI icon art-direction overrides: a small, auditable data layer shared by the
tuner preview and the generator so what you tune is what ships.

The override file (item_icon_overrides.json at the project root) is keyed by item
id. Every field is optional; absent fields keep the generator's automatic value.

Schema (per item):
  source       str   replace the GUI source model id (e.g. swap a wrong variant)
  target_px    float visible long edge in slot pixels (16px slot; vanilla full
                     block = 15.7). Overrides the automatic size-class target.
  anchor       str   "auto" | "center" | "floor" - overrides the automatic
                     short-model floor-anchor decision.
  yaw          float extra yaw in degrees applied as a geometry rotation around
                     the block centre (keeps display.gui at the vanilla camera).
                     NOTE: exact for y-rotated elements, approximate for x/z ones.
  offset_x     float horizontal screen offset in slot pixels (+ = right).
  offset_y     float vertical screen offset in slot pixels (+ = down).
  note         str   human note. "structural" notes flag art bugs no slider can
                     fix (missing texture, wrong crop) for the maintainer.

Offsets are converted back into geometry-space translation (never display.gui.
translation, which Minecraft applies *before* the GUI rotation). The projection
for camera [30,225,0] is sx=cos45*(x+z), sy=-(cos30*y - sin30*(x-z)/sqrt2);
choosing dx=dz cancels the sin30 term, so a screen offset (sx,sy) maps to
dx=dz=sx/(2*cos45), dy=-sy/cos30.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

OVERRIDE_FILENAME = "item_icon_overrides.json"
OVERRIDE_VERSION = 1

FIELDS = ("source", "target_px", "anchor", "yaw", "offset_x", "offset_y",
          "shade", "shade_strength", "note")
ANCHOR_CHOICES = ("auto", "center", "floor")
# 明暗三件套：
# - shade_strength 是当前写法，0 = 不乘明暗，1 = 真机实测（默认），上限 1.5；
# - shade 是旧写法（game/flat），只为了读得懂老文件，写入时不再产生；
# - 只影响预览/缩略图观感，不改几何，也不进 proxy。
SHADE_CHOICES = ("game", "flat")
LEGACY_SHADE_TO_STRENGTH = {"game": 1.0, "flat": 0.0}
SHADE_STRENGTH_RANGE = (0.0, 1.5)
DEFAULT_SHADE_STRENGTH = 1.0


def overrides_path(root: Path) -> Path:
    return Path(root) / OVERRIDE_FILENAME


def load_overrides(root: Path) -> dict[str, dict[str, Any]]:
    """Read the override file. Missing/empty => {}. Malformed => clear error."""
    path = overrides_path(root)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items", {}), dict):
        raise ValueError(f"{path}: expected {{'version': 1, 'items': {{...}}}}")
    result: dict[str, dict[str, Any]] = {}
    for item_id, raw in data.get("items", {}).items():
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: entry for {item_id} must be an object")
        entry = {key: raw[key] for key in FIELDS if key in raw}
        anchor = entry.get("anchor")
        if anchor is not None and anchor not in ANCHOR_CHOICES:
            raise ValueError(f"{path}: {item_id}.anchor must be one of {ANCHOR_CHOICES}")
        shade = entry.get("shade")
        if shade is not None and shade not in SHADE_CHOICES:
            raise ValueError(f"{path}: {item_id}.shade must be one of {SHADE_CHOICES}")
        for key in ("target_px", "yaw", "offset_x", "offset_y", "shade_strength"):
            if key in entry and not isinstance(entry[key], (int, float)):
                raise ValueError(f"{path}: {item_id}.{key} must be a number")
        if "shade_strength" in entry:
            low, high = SHADE_STRENGTH_RANGE
            if not low <= float(entry["shade_strength"]) <= high:
                raise ValueError(
                    f"{path}: {item_id}.shade_strength must be within {SHADE_STRENGTH_RANGE}")
        if "target_px" in entry and entry["target_px"] <= 0:
            raise ValueError(f"{path}: {item_id}.target_px must be positive")
        result[item_id] = entry
    return result


# 写入时视为"等于没写"的值：默认强度 1.0；其余字段的 0/空串也是 no-op。
# 旧档位 shade 不在这里：老文件怎么写就怎么留存，避免读一次写一次就改人家的语义。
_NOOP_VALUES = {"shade_strength": DEFAULT_SHADE_STRENGTH}


def save_overrides(root: Path, overrides: dict[str, dict[str, Any]]) -> Path:
    """Write the override file atomically-ish (temp then replace), dropping no-op entries."""
    path = overrides_path(root)
    clean: dict[str, dict[str, Any]] = {}
    for item_id, raw in sorted(overrides.items()):
        entry: dict[str, Any] = {}
        for key in FIELDS:
            if key not in raw:
                continue
            value = raw[key]
            if value in (None, ""):
                continue
            if key in _NOOP_VALUES and value == _NOOP_VALUES[key]:
                continue
            # 其余数值字段的 0 仍然是"没改"，但 shade_strength 的 0 是有效值（等于关阴影）。
            if key != "shade_strength" and value == 0:
                continue
            entry[key] = value
        if entry:
            clean[item_id] = entry
    payload = {"version": OVERRIDE_VERSION, "items": clean}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def effective_params(item_id: str, auto: dict[str, Any],
                     overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge automatic generator params with an item's overrides."""
    out: dict[str, Any] = {
        "target_px": auto.get("target_px"),
        "floor_anchor": bool(auto.get("floor_anchor", False)),
        "yaw": 0.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "source": None,
        "shade": "game",
        "shade_strength": DEFAULT_SHADE_STRENGTH,
        "note": "",
    }
    override = overrides.get(item_id, {})
    if "target_px" in override:
        out["target_px"] = float(override["target_px"])
    anchor = override.get("anchor", "auto")
    if anchor == "floor":
        out["floor_anchor"] = True
    elif anchor == "center":
        out["floor_anchor"] = False
    for key in ("yaw", "offset_x", "offset_y"):
        if key in override:
            out[key] = float(override[key])
    if "source" in override:
        out["source"] = override["source"]
    if "shade" in override:
        out["shade"] = override["shade"]
        out["shade_strength"] = LEGACY_SHADE_TO_STRENGTH.get(str(override["shade"]),
                                                              DEFAULT_SHADE_STRENGTH)
    if "shade_strength" in override:
        # 新写法优先于旧档位：显式强度覆盖 shade 推导出来的值。
        out["shade_strength"] = float(override["shade_strength"])
        out["shade"] = "flat" if out["shade_strength"] <= 0 else "game"
    if "note" in override:
        out["note"] = str(override["note"])
    out["overridden"] = bool(override)
    return out


def yaw_gui_rotation(yaw_delta: float, base_rotation=(30.0, 225.0, 0.0)) -> list[float]:
    """Camera rotation for an extra yaw: turn the *view*, never the geometry.

    旋转模型几何走不通：JSON 模型的 element 只能表达轴对齐 box（from/to 是两端角），
    把角点各自绕 Y 转任意角度就不再是同一个 box，于是模型被压扁、翻倒、甚至解体。
    正确做法是把 yaw 加进 proxy 的 display.gui.rotation——游戏按这个视角渲染，
    几何原样不动，fit 也按同一视角量尺寸与居中。
    """
    rotation = [float(value) for value in base_rotation]
    rotation[1] = (rotation[1] + float(yaw_delta)) % 360.0
    return rotation


def screen_offset_to_geometry(offset_x: float, offset_y: float, gui_scale: float,
                              gui_rotation=(30.0, 225.0, 0.0)) -> tuple[float, float, float]:
    """Convert a screen-pixel offset (+right, +down) into a geometry translation.

    Solved in the camera plane at the given rotation (see
    item_icon_proxy.translation_for_screen), so it stays exact when an extra yaw
    moves the display rotation off the vanilla 225.
    """
    from item_icon_proxy import translation_for_screen

    return translation_for_screen(offset_x / gui_scale, offset_y / gui_scale, gui_rotation)


def apply_screen_offset(model: dict[str, Any], texture_resolver,
                        offset_x: float, offset_y: float, gui_scale: float,
                        gui_rotation=None) -> dict[str, Any] | None:
    """Translate the fitted geometry so its visible silhouette moves by a screen
    offset. Includes one residual-correction pass for rasterisation rounding.
    Returns None only if the offset model cannot be measured.
    """
    from item_icon_preview import visible_projected_measurements

    if abs(offset_x) < 1e-9 and abs(offset_y) < 1e-9:
        return model
    result = copy.deepcopy(model)
    # Measure the CURRENT centre before shifting. A floor-anchored icon is not at
    # the slot centre to begin with, so the correction target must be relative to
    # where it actually is, not the origin.
    before = visible_projected_measurements(result, texture_resolver, pixels_per_unit=16)
    if before is None:
        return None
    before_bounds = before["bounds"]
    base_cx = (before_bounds[0] + before_bounds[2]) * 0.5
    base_cy = (before_bounds[1] + before_bounds[3]) * 0.5
    rotation = tuple(gui_rotation or
                     model.get("display", {}).get("gui", {}).get("rotation",
                                                                 (30.0, 225.0, 0.0)))
    dx, dy, dz = screen_offset_to_geometry(offset_x, offset_y, gui_scale, rotation)

    def shift(element, tx, ty, tz):
        for key in ("from", "to", "origin"):
            if key in element:
                element[key] = [round(element[key][0] + tx, 6),
                                round(element[key][1] + ty, 6),
                                round(element[key][2] + tz, 6)]
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and "origin" in rotation:
            origin = rotation["origin"]
            rotation["origin"] = [round(origin[0] + tx, 6),
                                  round(origin[1] + ty, 6),
                                  round(origin[2] + tz, 6)]

    for element in result.get("elements", []):
        shift(element, dx, dy, dz)

    measured = visible_projected_measurements(result, texture_resolver, pixels_per_unit=16)
    if measured is None:
        return None
    # Target centre is the original centre plus the intended offset (in projected
    # units). Using a relative target keeps floor-anchored models on their floor.
    target_cx = base_cx + offset_x / gui_scale
    target_cy = base_cy + offset_y / gui_scale  # screen y grows downward
    bounds = measured["bounds"]
    residual_x = (bounds[0] + bounds[2]) * 0.5 - target_cx
    residual_y = (bounds[1] + bounds[3]) * 0.5 - target_cy
    if abs(residual_x) > 1e-4 or abs(residual_y) > 1e-4:
        from item_icon_proxy import translation_for_screen
        rx, ry, rz = translation_for_screen(-residual_x, -residual_y, rotation)
        for element in result.get("elements", []):
            shift(element, rx, ry, rz)
    return result
