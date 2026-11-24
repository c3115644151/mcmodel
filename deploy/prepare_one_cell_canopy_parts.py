#!/usr/bin/env python3
"""Split canopy side sheets so adjacent canopies hide only their shared skins."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE = ASSETS / "models/block/one_cell_canopy.json"


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    model = json.loads(SOURCE.read_text(encoding="utf-8"))
    if len(model.get("elements", [])) != 4:
        raise SystemExit("Canopy source geometry changed; re-map the two thin side skins before splitting")
    parts = {
        "one_cell_canopy_core": [0, 1],
        "one_cell_canopy_side_left": [2],
        "one_cell_canopy_side_right": [3],
    }
    for name, indices in parts.items():
        part = copy.deepcopy(model)
        part["elements"] = [copy.deepcopy(model["elements"][index]) for index in indices]
        write(ASSETS / f"models/block/{name}.json", part)

    multipart = []
    left_direction = {"north": "west", "east": "north", "south": "east", "west": "south"}
    right_direction = {"north": "east", "east": "south", "south": "west", "west": "north"}
    for facing, angle in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        def part(model_id: str, condition: dict | None = None) -> None:
            apply = {"model": f"pastoral_home:block/{model_id}"}
            if angle:
                apply["y"] = angle
            row = {"apply": apply}
            if condition:
                row["when"] = {"facing": facing, **condition}
            else:
                row["when"] = {"facing": facing}
            multipart.append(row)

        part("one_cell_canopy_core")
        part("one_cell_canopy_side_left", {"connect_left": False})
        part("one_cell_canopy_side_right", {"connect_right": False})
    write(ASSETS / "blockstates/one_cell_canopy.json", {"multipart": multipart})
    print("Canopy models split into core/left/right skins with facing-aware shared-edge hiding.")


if __name__ == "__main__":
    main()
