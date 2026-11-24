#!/usr/bin/env python3
"""Import the authored vertical-rope segment and terminal models as block assets."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/deploy/model_sources/bridge_rope"
WORK = ROOT / "build/bridge_rope_models"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
IMPORTER = ROOT / "tools/deploy/import_java_block_bbmodel.py"
VARIANTS = {
    "segment": "bridge_rope_vertical_segment",
    "end": "bridge_rope_vertical_end",
}


def import_model(name: str, suffix: str) -> dict:
    model_path = WORK / f"{name}.json"
    texture_path = ASSETS / f"textures/block/hanging_rope_{suffix}.png"
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, str(IMPORTER), str(SOURCE / f"{name}.bbmodel"),
        "--model-out", str(model_path), "--texture-out", str(texture_path),
        "--texture-name", f"hanging_rope_{suffix}",
    ], cwd=ROOT, check=True)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model.setdefault("textures", {})["particle"] = f"pastoral_home:block/hanging_rope_{suffix}"
    target = ASSETS / f"models/block/hanging_rope_{suffix}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return model


def main() -> None:
    models = {suffix: import_model(name, suffix) for suffix, name in VARIANTS.items()}
    for suffix, model in models.items():
        if not model.get("elements"):
            raise ValueError(f"hanging rope {suffix} model has no rendered elements")
    blockstate = {
        "variants": {
            "end=false": {"model": "pastoral_home:block/hanging_rope_segment"},
            "end=true": {"model": "pastoral_home:block/hanging_rope_end"},
        }
    }
    path = ASSETS / "blockstates/hanging_rope.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blockstate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (WORK / "hanging_rope_asset_manifest.json").write_text(json.dumps({
        suffix: {"source": name, "elements": len(models[suffix]["elements"])}
        for suffix, name in VARIANTS.items()
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Prepared authored hanging-rope segment and end models.")


if __name__ == "__main__":
    main()
