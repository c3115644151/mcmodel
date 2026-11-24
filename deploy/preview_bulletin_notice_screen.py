#!/usr/bin/env python3
"""Compose a local screen preview using the same TTF providers as the in-game editor."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
OUT = ROOT / "build/entryway_models/paper_notice_screen_preview.png"
INK = (69, 56, 47, 255)


def minecraft_ascii_glyphs():
    client_jar = ROOT / ".gradle/caches/minecraft/versions/26.1.2/client.jar"
    with zipfile.ZipFile(client_jar) as jar:
        provider = json.loads(jar.read("assets/minecraft/font/include/default.json"))
        provider = next(p for p in provider["providers"] if p.get("file") == "minecraft:font/ascii.png")
        atlas = Image.open(jar.open("assets/minecraft/textures/font/ascii.png")).convert("RGBA")
    cell_w, cell_h = atlas.width // 16, atlas.height // 16
    glyphs = {}
    for row, chars in enumerate(provider["chars"]):
        for column, char in enumerate(chars):
            cell = atlas.crop((column * cell_w, row * cell_h,
                               (column + 1) * cell_w, (row + 1) * cell_h))
            bounds = cell.getchannel("A").getbbox()
            advance = 4 if char.isspace() else (max(2, bounds[2]) if bounds else 4)
            glyphs[char] = (cell, advance)
    return glyphs, cell_h


def draw_minecraft_line(image, glyphs, text, x, y, color):
    pen_x = x
    for char in text:
        cell, advance = glyphs.get(char, glyphs.get("?"))
        if cell is not None and not char.isspace():
            tinted = Image.new("RGBA", cell.size, color)
            tinted.putalpha(cell.getchannel("A"))
            image.alpha_composite(tinted, (pen_x, y + 1))
        pen_x += advance
    return pen_x


def wrap(text: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw, width: int):
    lines, line = [], ""
    for char in text:
        if char == "\n":
            lines.append(line)
            line = ""
            continue
        if line and draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = char
        else:
            line += char
    if line or not lines:
        lines.append(line)
    return lines


def main():
    image = Image.open(ASSETS / "textures/gui/paper_notebook.png").convert("RGBA")
    draw = ImageDraw.Draw(image)
    fonts = ASSETS / "font/lxgw_wenkai_lite_regular.ttf"
    body_font = ImageFont.truetype(str(fonts), 9)
    title_font = ImageFont.truetype(str(fonts), 12)
    label_font = ImageFont.truetype(str(fonts), 9)

    def draw_centered(text: str, y: int, font, color):
        box = draw.textbbox((0, 0), text, font=font)
        x = (256 - (box[2] - box[0])) // 2
        draw.text((x, y), text, font=font, fill=color)

    draw_centered("写一张公告", 18, title_font, (75, 55, 41, 255))
    draw.text((30, 38), "标题", font=label_font, fill=(128, 102, 82, 255))
    draw.text((228, 38), "作者：Dev", font=label_font, fill=(142, 112, 96, 255), anchor="rt")
    glyphs, _ = minecraft_ascii_glyphs()
    title_end = draw_minecraft_line(image, glyphs, "11", 30, 52, INK)
    draw.line((title_end, 54, title_end, 65), fill=INK, width=1)
    draw.text((30, 74), "写下想说的话", font=label_font, fill=(128, 102, 82, 255))

    body = "周日下午三点，在老橡树旁见。\n新鲜水果和刚出炉的面包都会准备好。"
    for line_index, line in enumerate(wrap(body, body_font, draw, 188)):
        draw.text((34, 90 + line_index * 9), line, font=body_font, fill=INK)

    for x, label in ((35, "张贴"), (135, "取消")):
        draw.rectangle((x, 190, x + 85, 209), fill=(128, 96, 68, 255))
        draw.rectangle((x + 1, 191, x + 84, 208), fill=(240, 225, 193, 255))
        draw.line((x + 2, 192, x + 83, 192), fill=(250, 240, 220, 255), width=1)
        box = draw.textbbox((0, 0), label, font=body_font)
        width = box[2] - box[0]
        draw.text((x + (86 - width) // 2, 195), label, font=body_font, fill=(96, 71, 51, 255))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((1024, 896), Image.Resampling.NEAREST).save(OUT)
    print(f"Rendered local screen composition to {OUT}")


if __name__ == "__main__":
    main()
