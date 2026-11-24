#!/usr/bin/env python3
"""Build the inventory and hand model of a multiblock furniture piece.

Minecraft 26.1 refuses any cuboid element whose coordinates leave [-16, 32]:
CuboidModelElement.getPosition throws "to specifier exceeds the allowed
boundaries". The piano is authored 43 pixels wide, so shipping the raw
assembly as its item model made the whole model fail to bake; the held item
then drew the missing model, the purple-black square players see.

A hand model also has to read at a sane size. Every furniture item model is
therefore normalized into one block the same way its GUI icon is, and inherits
minecraft:block/block display instead of carrying a per-model scale. One
camera, one size rule: the icon, the hand and the ground item all agree.
"""
from __future__ import annotations

import copy

from item_icon_proxy import TARGET_BLOCK_SIZE, geometry_bounds, normalize_to_block

# Minecraft hard element bounds; staying inside them is what keeps a model
# baking at all.
MODEL_LOW = -16.0
MODEL_HIGH = 32.0


def block_item_model(model: dict, *, label: str = "item") -> dict:
    """Return the one-block item model for an authored furniture model."""
    normalized = normalize_to_block(model, target_size=TARGET_BLOCK_SIZE)
    if normalized is None:
        raise ValueError(f"{label}: model carries no geometry to normalize")
    textures = copy.deepcopy(model.get("textures") or {})
    if not textures:
        raise ValueError(f"{label}: model carries no textures block")
    result = {
        "parent": "minecraft:block/block",
        "textures": textures,
        "elements": copy.deepcopy(normalized["model"]["elements"]),
    }
    bounds = geometry_bounds(result)
    if bounds is None:
        raise ValueError(f"{label}: normalized model lost its geometry")
    outside = [round(value, 3) for value in bounds
               if value < MODEL_LOW or value > MODEL_HIGH]
    if outside:
        raise ValueError(f"{label}: normalized geometry leaves the model bounds: {outside}")
    return result
