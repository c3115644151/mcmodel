#!/usr/bin/env python3
"""Split the globe sphere from its fixed stand for block-entity rendering."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE = ASSETS / "models/block/globe.json"


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    model = json.loads(SOURCE.read_text(encoding="utf-8"))
    elements = model.get("elements", [])
    if len(elements) != 9 or list(elements[0]["from"]) != [4, 9, 3] or list(elements[0]["to"]) != [14, 19, 13]:
        raise SystemExit("Globe source geometry changed; identify the sphere element before splitting")
    stand = copy.deepcopy(model)
    stand["elements"] = [copy.deepcopy(element) for element in elements[1:]]
    sphere = copy.deepcopy(model)
    sphere["elements"] = [copy.deepcopy(elements[0])]
    write(ASSETS / "models/block/globe_stand.json", stand)
    write(ASSETS / "models/block/globe_sphere.json", sphere)
    for item, model_name in (("globe_stand_render", "globe_stand"),
                             ("globe_sphere_render", "globe_sphere")):
        write(ASSETS / f"items/{item}.json", {
            "model": {"type": "minecraft:model", "model": f"pastoral_home:block/{model_name}"}
        })
    print("Globe sphere and static stand render resources generated.")


if __name__ == "__main__":
    main()
