#!/usr/bin/env python3
"""Every block that splits its model into per-cell slices must draw every cell.

`DecorativeStructureBlock` hides non-anchor cells (`RenderShape.INVISIBLE`) so that a single
model spanning several cells is drawn once, from the anchor. Blocks that instead ship one model
file per cell (`piano_l0_c0`, `wardrobe_l2_c1`, ...) have to override `getRenderShape` and return
`RenderShape.MODEL`, otherwise only the anchor's slice is drawn and the rest of the furniture is
missing in game while every offline asset check still passes.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLOCKSTATES = ROOT / "src/main/resources/assets/pastoral_home/blockstates"
SOURCES = ROOT / "src/main/java/com/pastoralhome/block"

MODEL_REF = re.compile(r"pastoral_home:block/([a-z0-9_]+)")
SLICE_NAME = re.compile(r"^([a-z0-9_]+?)_l\d+(_c\d+)?(_r\d+)?$")
RENDER_SHAPE = "RenderShape getRenderShape("


def sliced_blocks() -> dict[str, dict[str, set[str]]]:
    """blockstate stem -> owner block -> the distinct per-cell models it references.

    One slice name reused by every cell means the block draws its whole model from the anchor
    and only reserves space elsewhere (see RecordPlayerBlock), so hiding the other cells is
    correct there. Two or more slice names mean each cell owns geometry and must draw it.
    """
    found: dict[str, dict[str, set[str]]] = {}
    for path in sorted(BLOCKSTATES.glob("*.json")):
        owners: dict[str, set[str]] = {}
        for ref in MODEL_REF.findall(path.read_text(encoding="utf-8")):
            match = SLICE_NAME.match(ref)
            if match:
                owners.setdefault(match.group(1), set()).add(ref)
        if owners:
            found[path.stem] = owners
    return found


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def block_source(owner: str) -> Path | None:
    """Class file implementing `owner`, walking prefixes when one class registers several blocks.

    `wardrobe_closed` and `wardrobe_open` are both instances of `WardrobeBlock`, so the owner name
    alone does not always name the class.
    """
    parts = owner.split("_")
    for end in range(len(parts), 0, -1):
        candidate = SOURCES / f"{pascal('_'.join(parts[:end]))}Block.java"
        if candidate.exists():
            return candidate
    return None


def method_body(source: str, signature: str) -> str | None:
    """Text between the method's braces, or None when the method is not declared."""
    start = source.find(signature)
    if start < 0:
        return None
    opening = source.find("{", start)
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
    return None


class SlicedRenderShapeTests(unittest.TestCase):
    def test_detection_finds_the_split_blocks(self):
        found = sliced_blocks()
        # The gramophone is not here: its horn tilts on three axes, so the whole model
        # ships as one neoforge:obj file drawn by the anchor cell.
        self.assertEqual(
            sorted(found),
            ["bulletin_board", "piano", "spruce_planter", "wardrobe"],
        )

    def test_every_sliced_block_draws_each_cell(self):
        problems: list[str] = []
        for blockstate, owners in sliced_blocks().items():
            for owner, slices in sorted(owners.items()):
                source = block_source(owner)
                if source is None:
                    problems.append(f"{blockstate}: no class file for sliced model owner {owner}")
                    continue
                body = method_body(source.read_text(encoding="utf-8"), RENDER_SHAPE)
                if body is None:
                    problems.append(
                        f"{blockstate}: {source.name} has no getRenderShape override, "
                        "so the base class hides every non-anchor cell"
                    )
                    continue
                if len(slices) == 1:
                    continue
                if "RenderShape.MODEL" not in body:
                    problems.append(f"{blockstate}: {source.name} getRenderShape never returns MODEL")
                elif "INVISIBLE" in body:
                    problems.append(
                        f"{blockstate}: {source.name} getRenderShape still hides cells "
                        "(INVISIBLE), but every cell owns a slice"
                    )
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
