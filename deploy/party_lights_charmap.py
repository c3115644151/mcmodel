"""Print the sheet content as a character map so the layout is read as data, not as pixels."""
from __future__ import annotations

import base64
import io
import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    for si, tex in enumerate(data["textures"]):
        raw = base64.b64decode(tex["source"].split(",", 1)[1])
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        px = image.load()
        print(f"=== sheet {'ab'[si]} {image.size} ===")
        for frame in range(4):
            colours = Counter()
            for y in range(32):
                for x in range(32):
                    a = px[x, frame * 32 + y]
                    if a[3] > 0:
                        colours[a[:3]] += 1
            print(f"-- frame {frame}: " + ", ".join(f"{k}:{v}" for k, v in colours.most_common(6)))
        print("legend: #=dark orange, O=orange, o=light orange, Y=cream, W=white, g=grey, .=clear")
        for frame in (0, 1, 2, 3):
            print(f"-- sheet {'ab'[si]} frame {frame} (rows 0..16 only; 17..31 are empty) --")
            print("    " + "".join(str(x % 10) for x in range(32)))
            for y in range(17):
                row = []
                for x in range(32):
                    r, g, b, a = px[x, frame * 32 + y]
                    if a == 0:
                        row.append(".")
                    elif r > 200 and g > 220 and b > 190:
                        row.append("W")
                    elif r > 200 and g > 160 and b > 100:
                        row.append("Y")
                    elif r > 190 and g < 170 and b < 110:
                        row.append("O")
                    elif r > 150 and g < 160 and b < 110:
                        row.append("o")
                    elif abs(r - g) < 40 and abs(g - b) < 60 and r < 170:
                        row.append("g")
                    else:
                        row.append("#")
                print(f"{y:3d} " + "".join(row))


if __name__ == "__main__":
    main()
