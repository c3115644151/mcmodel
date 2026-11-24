#!/usr/bin/env python3
"""Prove the render-semantics audit actually fails on the mistakes it exists to catch.

A gate that only ever prints "clean" is indistinguishable from a gate that checks nothing. Both
negative cases here are real regressions this project shipped and had to diagnose from screenshots:

* the opaque shell around a lit core (the party light's first in-game form read as a solid orange
  cube, because a block model does not cull the near faces the way a Blockbench viewport does);
* the shell listed before the core (build/shots/pl_v8.png: the cream brick).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

import audit_model_render_semantics as gate


def make_assets(root: Path, shell_alpha: int) -> Path:
    assets = root / "assets"
    textures = assets / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, alpha in (("shell", shell_alpha), ("core", 255)):
        image = Image.new("RGBA", (16, 16), (226, 145, 65, alpha))
        image.save(textures / f"{name}.png")
    return assets


def cube(low, high, texture, name):
    return {
        "name": name,
        "from": list(low),
        "to": list(high),
        "faces": {face: {"texture": texture, "uv": [0, 0, 16, 16]}
                  for face in ("north", "south", "east", "west", "up", "down")},
    }


def write_model(assets: Path, order: str, shell_alpha: int) -> Path:
    shell = cube((6, 1, 6), (10, 5, 10), "#shell", "shell")
    core = cube((6.5, 1.5, 6.5), (9.5, 4.5, 9.5), "#core", "core")
    elements = [shell, core] if order == "shell_first" else [core, shell]
    model = {
        "parent": "minecraft:block/block",
        "textures": {"particle": "#shell", "shell": "shell", "core": "core"},
        "elements": elements,
    }
    path = assets / "models" / f"{order}_{shell_alpha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model), encoding="utf-8")
    return path


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)

        assets = make_assets(root / "opaque", shell_alpha=255)
        problems = gate.audit(write_model(assets, "core_first", 255), assets)
        if not any("can never be seen in game" in problem for problem in problems):
            print("FAIL opaque shell around a core was not reported")
            failures += 1
        else:
            print("ok   opaque shell around a core is reported")

        assets = make_assets(root / "order", shell_alpha=100)
        problems = gate.audit(write_model(assets, "shell_first", 100), assets)
        if not any("list order is the draw order" in problem for problem in problems):
            print("FAIL shell listed before the core was not reported")
            failures += 1
        else:
            print("ok   shell listed before the core is reported")

        assets = make_assets(root / "good", shell_alpha=100)
        problems = gate.audit(write_model(assets, "core_first", 100), assets)
        if problems:
            print("FAIL a correct translucent shell was reported: " + "; ".join(problems))
            failures += 1
        else:
            print("ok   a translucent shell with the core first passes")

        assets = make_assets(root / "field", shell_alpha=255)
        model = write_model(assets, "core_first", 255)
        data = json.loads(model.read_text(encoding="utf-8"))
        data["render_type"] = "minecraft:cutout"
        model.write_text(json.dumps(data), encoding="utf-8")
        problems = gate.audit(model, assets)
        if not any("render_type" in problem for problem in problems):
            print("FAIL a declared render_type was not reported")
            failures += 1
        else:
            print("ok   a declared render_type is reported")

    print(f"{4 - failures} of 4 negative cases behave")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
