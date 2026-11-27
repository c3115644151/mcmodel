#!/usr/bin/env python3
"""Import the authored thin-rope bbmodel as a block asset.

The thin cord shares every mechanic with the coarse bridge rope: one entity type,
one item behaviour, one sag curve and the same lamps. Only the cuboid cross
section differs (1x1 here vs 2x2 for the coarse rope), and the mesh renderer
reads the cross-section centre from this model, so there is no render branch.
The fence collar is shared with the coarse rope on purpose: same function.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/bridge_rope/bridge_rope_thin.bbmodel"
WORK = ROOT / "build/bridge_rope_models"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
NAME = "bridge_rope_thin"


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    model_path = WORK / (NAME + ".json")
    texture_path = ASSETS / ("textures/block/" + NAME + ".png")
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, str(IMPORTER), str(SOURCE),
        "--model-out", str(model_path), "--texture-out", str(texture_path),
        "--texture-name", NAME,
    ], cwd=ROOT, check=True)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model.setdefault("textures", {})["particle"] = "pastoral_home:block/" + NAME + "_particle"
    elements = model.get("elements", [])
    if len(elements) != 1:
        raise SystemExit("thin rope must have exactly one cube, got " + str(len(elements)))
    target = ASSETS / ("models/block/" + NAME + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Prepared thin bridge-rope model and texture.")


if __name__ == "__main__":
    main()
