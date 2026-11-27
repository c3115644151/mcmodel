"""Build candle (烛台) block models from the imported java_block source.

Source has 23 cubes across two embedded textures:
  elements 0..16 -> body, 128x128 texture (the metal holder)
  elements 17..22 -> flame, 16x64 four-frame animated texture (uv_width/height 16)

The flame is emitted as its own model so the blockstate can show it only when lit.
UVs are taken verbatim from Blockbench's native java_block export; the importer
already normalised them against the project's 128px texture space, which matches
the V=0..4 range used by the working garden_lantern_flame (also 16x64).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "build/candle_probe/candle_raw.json"
OUT = ROOT / "src/main/resources/assets/pastoral_home/models/block"

BODY_SLOT = "#candle_body"
FLAME_SLOT = "#candle_flame"


def retint(elements, slot):
    out = []
    for e in elements:
        e = dict(e)
        faces = {}
        for face, spec in (e.get("faces") or {}).items():
            spec = dict(spec)
            spec["texture"] = slot
            faces[face] = spec
        e["faces"] = faces
        out.append(e)
    return out


def shell(elements, textures):
    return {
        "format_version": "1.21.6",
        "credit": "Made with Blockbench",
        "textures": textures,
        "elements": elements,
        "parent": "minecraft:block/block",
    }


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def main():
    source = json.loads(SRC.read_text(encoding="utf-8"))
    elements = source["elements"]
    if len(elements) != 23:
        raise SystemExit(f"expected 23 elements, got {len(elements)}")

    body = retint(elements[:17], BODY_SLOT)
    flame = retint(elements[17:], FLAME_SLOT)

    tex_body = {"candle_body": "pastoral_home:block/candle_body",
                "particle": "pastoral_home:block/candle_particle"}
    tex_flame = {"candle_flame": "pastoral_home:block/candle_flame",
                 "particle": "pastoral_home:block/candle_particle"}

    write(OUT / "candle_holder_base.json", shell(body, tex_body))
    write(OUT / "candle_holder_flame.json", shell(flame, tex_flame))
    # Item form shows the unlit holder only.
    write(OUT / "candle_holder_item.json", shell(body, tex_body))


if __name__ == "__main__":
    main()
