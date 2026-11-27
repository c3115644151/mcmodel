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

FIELDS = ("source", "target_px", "anchor", "yaw", "offset_x", "offset_y", "note")
ANCHOR_CHOICES = ("auto", "center", "floor")


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
        for key in ("target_px", "yaw", "offset_x", "offset_y"):
            if key in entry and not isinstance(entry[key], (int, float)):
                raise ValueError(f"{path}: {item_id}.{key} must be a number")
        if "target_px" in entry and entry["target_px"] <= 0:
            raise ValueError(f"{path}: {item_id}.target_px must be positive")
        result[item_id] = entry
    return result


def save_overrides(root: Path, overrides: dict[str, dict[str, Any]]) -> Path:
    """Write the override file atomically-ish (temp then replace), dropping no-op entries."""
    path = overrides_path(root)
    clean: dict[str, dict[str, Any]] = {}
    for item_id, raw in sorted(overrides.items()):
        entry = {key: raw[key] for key in FIELDS if key in raw and raw[key] not in (None, "", 0)}
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
    if "note" in override:
        out["note"] = str(override["note"])
    out["overridden"] = bool(override)
    return out


def apply_yaw_rotation(model: dict[str, Any], yaw_delta: float) -> dict[str, Any]:
    """Rotate every element around the block centre by an extra yaw (degrees).

    Implemented as a geometry rotation so display.gui stays the vanilla camera;
    fit_gui_projection's inverse-projection maths assumes yaw 225. Exact for
    elements whose own rotation is about y, approximate for x/z rotations.
    """
    if abs(yaw_delta) < 1e-9:
        return model
    from gui_measure import apply_rotation

    result = copy.deepcopy(model)

    def rotate_point(point):
        return [round(value, 6) for value in apply_rotation(point, [0.0, yaw_delta, 0.0], [8.0, 8.0, 8.0])]

    for element in result.get("elements", []):
        for key in ("from", "to", "origin"):
            if key in element:
                element[key] = rotate_point(element[key])
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and "origin" in rotation:
            rotation["origin"] = rotate_point(rotation["origin"])
    return result


def screen_offset_to_geometry(offset_x: float, offset_y: float,
                              gui_scale: float) -> tuple[float, float, float]:
    """Convert a screen-pixel offset (+right, +down) into geometry translation."""
    cos45 = math.cos(math.radians(45.0))
    cos30 = math.cos(math.radians(30.0))
    # 游戏的 screen x 是 -(x+z)*cos45（见 fit_gui_projection 的推导），所以
    # 正 offset_x 需要负的 dx+dz。
    sx = -offset_x / gui_scale
    sy = offset_y / gui_scale
    dx = dz = sx / (2.0 * cos45)
    dy = -sy / cos30
    return dx, dy, dz


def apply_screen_offset(model: dict[str, Any], texture_resolver,
                        offset_x: float, offset_y: float,
                        gui_scale: float) -> dict[str, Any] | None:
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
    dx, dy, dz = screen_offset_to_geometry(offset_x, offset_y, gui_scale)
    cos45 = math.cos(math.radians(45.0))
    cos30 = math.cos(math.radians(30.0))

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
        rx = rz = residual_x / (2.0 * cos45)
        ry = residual_y / cos30  # sy = -cos30*dy -> dy = -sy/cos30; ry is -dy
        ry = -ry
        for element in result.get("elements", []):
            shift(element, rx, ry, rz)
    return result
