#!/usr/bin/env python3
"""Split cuboid model elements into Minecraft cell-owned fragments.

Unrotated cuboids are clipped on all block-grid axes. Single-axis rotated
cuboids can be split on their rotation axis without changing their geometry;
their remaining extents are assigned by the transformed bounds center and
reported when they cross a cell boundary. Face UVs are cropped with the same
quarter-turn convention as the block-model face baker.
"""
from __future__ import annotations

import copy
import itertools
import math
from typing import Any

from item_icon_preview import FACE_VERTICES
from item_icon_proxy import geometry_bounds

ROTATED_CELL_TESSELLATION_STEP = 2.0

FACE_NORMAL_AXIS = {
    "west": (0, -1), "east": (0, 1),
    "down": (1, -1), "up": (1, 1),
    "north": (2, -1), "south": (2, 1),
}


def _segments(low: float, high: float, epsilon: float = 1e-7):
    if high - low <= epsilon:
        return [(low, high, math.floor(((low + high) * 0.5) / 16.0))]
    first = math.floor(low / 16.0)
    last = math.floor((high - epsilon) / 16.0)
    parts = []
    for cell in range(first, last + 1):
        lo = max(low, cell * 16.0)
        hi = min(high, (cell + 1) * 16.0)
        if hi - lo > epsilon:
            parts.append((lo, hi, cell))
    return parts


def _segments_at_step(low: float, high: float, step: float = 1.0):
    parts = []
    current = low
    while current < high - 1e-7:
        nxt = min(high, current + step)
        parts.append((current, nxt, None))
        current = nxt
    return parts or [(low, high, None)]


def _face_uv_points(element: dict[str, Any], face_name: str):
    face = element["faces"][face_name]
    uv = face.get("uv")
    if not uv or len(uv) != 4:
        return None
    rotation = round(float(face.get("rotation", 0)) / 90.0) % 4
    points = []
    for vertex_index in range(4):
        idx = (vertex_index + rotation) % 4
        u = uv[0] if idx in (0, 1) else uv[2]
        v = uv[1] if idx in (0, 3) else uv[3]
        points.append((float(u), float(v)))
    return points


def _crop_face_uv(original: dict[str, Any], fragment: dict[str, Any], face_name: str):
    source_uv = _face_uv_points(original, face_name)
    if source_uv is None:
        return
    vertices = FACE_VERTICES[face_name]
    varying = [axis for axis in range(3)
               if len({vertex[axis] for vertex in vertices}) > 1]
    if len(varying) != 2:
        return
    axis_a, axis_b = varying
    # Convert source face corners to a bilinear UV map in face-local [0,1]^2.
    lookup = {(vertices[i][axis_a], vertices[i][axis_b]): source_uv[i] for i in range(4)}
    orig_lo, orig_hi = original["from"], original["to"]
    frag_lo, frag_hi = fragment["from"], fragment["to"]

    def uv_at(ta: float, tb: float):
        p00, p10 = lookup[(0, 0)], lookup[(1, 0)]
        p11, p01 = lookup[(1, 1)], lookup[(0, 1)]
        return tuple(
            p00[i] * (1 - ta) * (1 - tb) + p10[i] * ta * (1 - tb)
            + p11[i] * ta * tb + p01[i] * (1 - ta) * tb
            for i in range(2)
        )

    spans = [orig_hi[axis] - orig_lo[axis] for axis in (axis_a, axis_b)]
    if any(abs(span) < 1e-9 for span in spans):
        return
    desired = []
    for vertex in vertices:
        point = [frag_hi[axis] if vertex[axis] else frag_lo[axis] for axis in range(3)]
        ta = (point[axis_a] - orig_lo[axis_a]) / spans[0]
        tb = (point[axis_b] - orig_lo[axis_b]) / spans[1]
        desired.append(uv_at(ta, tb))

    face = fragment["faces"][face_name]
    rotation = round(float(face.get("rotation", 0)) / 90.0) % 4
    indexed = {(i + rotation) % 4: desired[i] for i in range(4)}
    u0, v0 = indexed[0]
    u1, v1 = indexed[2]
    face["uv"] = [round(u0, 7), round(v0, 7), round(u1, 7), round(v1, 7)]


def split_element(element: dict[str, Any], *, keep_seam_faces: bool = False):
    """Return (cell xyz, localized fragment, warnings) for one cuboid element.

    keep_seam_faces keeps the faces the split created on a cell plane instead of
    dropping them. The default drops them on the assumption that the neighbouring
    cell contributes the matching face; that assumption holds only when the element
    really continues into that cell. With the faces dropped, both halves are open
    shells at the seam, so any oblique view straight into the seam sees through the
    shell into the model's inside. Keeping them makes every fragment a closed box:
    the two seam faces are coplanar and face opposite ways, so backface culling still
    draws exactly one of them and there is no z-fighting.
    """
    bounds = geometry_bounds({"elements": [element]})
    if bounds is None:
        return []
    rotation = element.get("rotation")
    rotation_axis = rotation.get("axis") if isinstance(rotation, dict) else None
    axis_index = {"x": 0, "y": 1, "z": 2}.get(rotation_axis)
    if rotation is not None and axis_index is None:
        raise ValueError(f"unsupported multi-axis element rotation: {rotation!r}")
    cell_split_axes = [0, 1, 2] if rotation is None else [axis_index]
    tessellate_axes = []
    if rotation is not None:
        affected_axes = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[axis_index]
        for world_axis in range(3):
            lo_bound, hi_bound = bounds[world_axis], bounds[world_axis + 3]
            crosses_cell = math.floor(lo_bound / 16.0) != math.floor((hi_bound - 1e-7) / 16.0)
            if crosses_cell and world_axis != axis_index:
                tessellate_axes.extend(axis for axis in affected_axes if axis != axis_index)
                break
    tessellate_axes = sorted(set(tessellate_axes))
    split_axes = sorted(set(cell_split_axes + tessellate_axes))

    segs = []
    for axis in range(3):
        low, high = float(element["from"][axis]), float(element["to"][axis])
        if axis in cell_split_axes:
            segs.append(_segments(low, high))
        elif axis in tessellate_axes:
            segs.append(_segments_at_step(low, high, ROTATED_CELL_TESSELLATION_STEP))
        else:
            segs.append([(low, high, None)])

    output = []
    for pieces in itertools.product(*segs):
        lo = [part[0] for part in pieces]
        hi = [part[1] for part in pieces]
        cell = [part[2] for part in pieces]
        transformed_bounds = geometry_bounds({"elements": [{**element, "from": lo, "to": hi}]}) or bounds
        center = [(transformed_bounds[i] + transformed_bounds[i + 3]) * 0.5 for i in range(3)]
        owner = [int(part[2]) if part[2] is not None else math.floor(center[axis] / 16.0)
                 for axis, part in enumerate(pieces)]
        origin = [cell_index * 16.0 for cell_index in owner]

        fragment = copy.deepcopy(element)
        fragment["from"], fragment["to"] = lo, hi
        if fragment.get("rotation"):
            fragment["rotation"]["origin"] = [
                float(element["rotation"]["origin"][axis]) - origin[axis] for axis in range(3)
            ]

        # Drop the newly created internal side faces; only source exterior faces
        # remain, so adjoining cell fragments do not z-fight along their seams.
        for face_name, (normal_axis, normal_sign) in FACE_NORMAL_AXIS.items():
            if normal_axis not in split_axes:
                continue
            created_negative = (normal_sign < 0
                                and lo[normal_axis] > float(element["from"][normal_axis]) + 1e-7)
            created_positive = (normal_sign > 0
                                and hi[normal_axis] < float(element["to"][normal_axis]) - 1e-7)
            if (created_negative or created_positive) and not keep_seam_faces:
                fragment["faces"].pop(face_name, None)
                continue
            if face_name in fragment.get("faces", {}):
                _crop_face_uv(element, fragment, face_name)

        for axis in range(3):
            fragment["from"][axis] -= origin[axis]
            fragment["to"][axis] -= origin[axis]

        # For rotated elements, flag unsplit axes whose transformed bounds cross
        # cell boundaries. The model toolchain can then require an explicit
        # profile or a finer mesh decomposition instead of silently treating
        # the entire AABB as one cell.
        crossing = []
        if rotation is not None:
            for axis in range(3):
                if axis in cell_split_axes:
                    continue
                lo_bound, hi_bound = transformed_bounds[axis], transformed_bounds[axis + 3]
                cell_low, cell_high = owner[axis] * 16.0, (owner[axis] + 1) * 16.0
                overhang = max(0.0, cell_low - lo_bound, hi_bound - cell_high)
                if overhang > 1e-7:
                    crossing.append({"axis": "xyz"[axis], "overhang_px": round(overhang, 6)})
        output.append((tuple(owner), fragment, crossing))
    return output


def split_model(model: dict[str, Any], *, with_source_index: bool = False,
                keep_seam_faces: bool = False):
    """Return cell-to-model map and cross-cell rotated-element warnings."""
    cells: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    warning_map = {}
    for element_index, element in enumerate(model.get("elements", [])):
        for owner, fragment, crossing in split_element(element, keep_seam_faces=keep_seam_faces):
            if with_source_index:
                fragment["_source_element_index"] = element_index
            cells.setdefault(owner, []).append(fragment)
            for issue in crossing:
                key = (element_index, issue["axis"])
                value = warning_map.setdefault(key, {"element": element_index, "axis": issue["axis"],
                                                     "max_overhang_px": 0.0, "affected_fragments": 0})
                value["max_overhang_px"] = max(value["max_overhang_px"], issue["overhang_px"])
                value["affected_fragments"] += 1
    warnings = list(warning_map.values())
    return cells, warnings
