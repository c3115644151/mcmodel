"""Inspect the party-lights .bbmodel source: element bounds, face uvs, texture sheets.

Writes decoded sheets plus a structure report to build/party_lights_src/.
Nothing here touches src/ - it is the reference the generator reads.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
OUT = ROOT / "build/party_lights_src"


def row_runs(im: Image.Image) -> list[tuple[int, int, int]]:
    px = im.load()
    width, height = im.size
    counts = [sum(1 for x in range(width) if px[x, y][3] > 0) for y in range(height)]
    runs: list[tuple[int, int, int]] = []
    cur, start = counts[0], 0
    for y in range(1, height + 1):
        if y == height or counts[y] != cur:
            runs.append((start, y - 1, cur))
            if y < height:
                cur, start = counts[y], y
    return runs


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"format={data['meta']['model_format']} resolution={data['resolution']}")
    print(f"elements={len(data['elements'])} textures={len(data['textures'])}")
    sheets = []
    for i, tex in enumerate(data["textures"]):
        source = tex.get("source", "")
        raw = base64.b64decode(source.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        path = OUT / f"sheet_{chr(ord('a') + i)}.png"
        im.save(path)
        sheets.append(path)
        print(f"[tex {i}] name={tex.get('name')!r} declared_uv={tex.get('uv_width')}x{tex.get('uv_height')}"
              f" png={im.size} -> {path.relative_to(ROOT)}")
        for start, end, count in row_runs(im):
            if count:
                print(f"    rows {start}..{end} ({end - start + 1}) opaque x {count}")
    for i, e in enumerate(data["elements"]):
        rot = e.get("rotation") or None
        print(f"[cube {i}] {e['name']} from={e['from']} to={e['to']} rot={rot}")
        for face, spec in e["faces"].items():
            print(f"    {face:6s} texture={spec.get('texture')} uv={spec.get('uv')} rotation={spec.get('rotation')}")


if __name__ == "__main__":
    main()
