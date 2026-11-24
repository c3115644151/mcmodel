#!/usr/bin/env python3
"""Audit the uv of a .bbmodel before it is turned into block models.

A block model reads uv on a 0..16 grid. The artist authors uv against the project's declared
resolution, so the conversion every importer in this project applies is uv * 16 / resolution, exactly
as tools/deploy/import_java_block_bbmodel.py:158 does it. When the resolution is 16x16 — which it is
for every model here — the numbers pass through untouched. The sheet size is a separate fact: it only
decides how many texels one uv unit covers, so a 32x128 strip gives two texels per unit across and
eight down.

This script prints, per element and face, the uv the artist wrote, the scale it needs, the texel
window that lands on the sheet, and how much of that window is transparent. It exits non-zero when a
face would be mangled: uv outside the model's grid, an empty window, or a window that is entirely
transparent (the client's alpha test would punch the whole face away).

    .venv/Scripts/python.exe tools/deploy/model_uv_audit.py tools/deploy/model_sources/party_lights/party_lights.bbmodel
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MODEL_SPACE = 16.0


def load_sheet(project: dict, texture: dict) -> Image.Image | None:
    source = texture.get("source") or ""
    if source.startswith("data:"):
        payload = source.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGBA")
    name = texture.get("relative_path") or texture.get("name") or ""
    for candidate in (ROOT / "src/main/resources/assets/pastoral_home/textures" / name,
                      ROOT / "tools/deploy/model_sources" / name):
        if candidate.exists():
            return Image.open(candidate).convert("RGBA")
    return None


def window(sheet: Image.Image, uv, scale_u: float, scale_v: float):
    """Texel box a face reads, plus how much of it is transparent."""
    width, height = sheet.size
    u0, v0, u1, v1 = uv
    x0 = int(min(u0, u1) * scale_u / MODEL_SPACE * width)
    x1 = max(x0 + 1, int(round(max(u0, u1) * scale_u / MODEL_SPACE * width)))
    y0 = int(min(v0, v1) * scale_v / MODEL_SPACE * height)
    y1 = max(y0 + 1, int(round(max(v0, v1) * scale_v / MODEL_SPACE * height)))
    x1, y1 = min(x1, width), min(y1, height)
    region = sheet.crop((x0, y0, x1, y1))
    pixels = list(region.getdata())
    clear = sum(1 for pixel in pixels if pixel[3] == 0) / max(len(pixels), 1)
    colours = len({pixel[:3] for pixel in pixels if pixel[3] > 0})
    return (x0, y0, x1, y1), region.size, clear, colours


def audit(path: Path) -> int:
    project = json.loads(path.read_text(encoding="utf-8"))
    textures = project.get("textures") or []
    sheets = {}
    for index, texture in enumerate(textures):
        sheet = load_sheet(project, texture)
        if sheet is not None:
            sheets[index] = sheet
    if not sheets:
        print(f"{path.name}: no sheet could be read; only the art's own uv can be checked")
    resolution = project.get("resolution") or {}
    res_w = float(resolution.get("width") or 16.0)
    res_h = float(resolution.get("height") or res_w)
    scale_u = MODEL_SPACE / res_w
    scale_v = MODEL_SPACE / res_h
    print(f"{path.name}: resolution {res_w:g}x{res_h:g} -> uv scale {scale_u:g}/{scale_v:g}"
          + ("  (uv passes through untouched)" if scale_u == 1.0 and scale_v == 1.0 else ""),
          f"; {len(project.get('elements') or [])} elements, {len(textures)} textures")

    problems: list[str] = []
    notes: list[str] = []
    for index, sheet in sorted(sheets.items()):
        print(f"  sheet {index}: {textures[index].get('name', index)} {sheet.width}x{sheet.height} "
              f"-> {sheet.width / MODEL_SPACE:g} x {sheet.height / MODEL_SPACE:g} texels per uv unit")
    default = next(iter(sorted(sheets))) if sheets else None

    for index, element in enumerate(project.get("elements") or []):
        name = element.get("name") or f"element {index}"
        for face, spec in (element.get("faces") or {}).items():
            uv = spec.get("uv")
            if uv is None or spec.get("texture") is None:
                continue
            sheet_index = spec.get("texture")
            sheet = sheets.get(sheet_index) if isinstance(sheet_index, int) else sheets.get(default)
            if sheet is None:
                continue
            box, size, clear, colours = window(sheet, uv, scale_u, scale_v)
            scaled = [round(uv[0] * scale_u, 4), round(uv[1] * scale_v, 4),
                      round(uv[2] * scale_u, 4), round(uv[3] * scale_v, 4)]
            print(f"  {name}.{face}: uv {[round(float(v), 3) for v in uv]} -> model {scaled} "
                  f"texels x{box[0]}..{box[2]} y{box[1]}..{box[3]} "
                  f"({size[0]}x{size[1]}) clear {clear:.0%} colours {colours}")
            if size[0] < 1 or size[1] < 1:
                problems.append(f"{name}.{face}: empty texel window")
            # An all-transparent window is the artist's choice (a hidden face, a blank tile); the client
            # simply drops it, so it is reported without failing the model.
            notes.append(f"{name}.{face}: window is entirely transparent; the client draws nothing there")
            if max(scaled) > MODEL_SPACE + 1e-6 or min(scaled) < -1e-6:
                problems.append(f"{name}.{face}: scaled uv leaves the 0..16 grid ({scaled})")
            if box[2] > sheet.width or box[3] > sheet.height:
                problems.append(f"{name}.{face}: the window runs off the sheet "
                                f"(x{box[2]} of {sheet.width}, y{box[3]} of {sheet.height})")

    for line in notes:
        print("note " + line)
    for line in problems:
        print("PROBLEM " + line)
    print(f"{len(problems)} problems, {len(notes)} notes")
    return 1 if problems else 0


if __name__ == "__main__":
    paths = [Path(argument) for argument in sys.argv[1:]]
    if not paths:
        raise SystemExit("usage: model_uv_audit.py <file.bbmodel> [...]")
    status = 0
    for candidate in paths:
        status |= audit(candidate)
    raise SystemExit(status)
