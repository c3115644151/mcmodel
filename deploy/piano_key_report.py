#!/usr/bin/env python3
"""Assert the shipped recolor piano keyboard geometry against the design brief.

This report reads shipped assets and the generator's recorded geometry, never an in-memory
model, so stale numbers or hand-edited models fail here instead of in game.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_piano_models import block_constants, load_band_params, white_key_width  # noqa: E402

ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
GEOMETRY = ROOT / "build/instrument_models/piano_key_geometry.json"
TOLERANCE = 1e-6


def main() -> int:
    failures: list[str] = []

    def check(ok: bool, message: str) -> None:
        if not ok:
            failures.append(message)

    data = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    constants = block_constants()
    params = load_band_params()
    pitch = white_key_width(constants)
    check(abs(data["pitch_px"] - pitch) < TOLERANCE, "pitch does not match PianoBlock")
    check(abs(data["white_face_width_px"] - (pitch - 2 * params["key_gap_px"])) < TOLERANCE,
          "white face width does not include both key gaps")
    check(abs(data["black_width_px"] - params["black_width_px"]) < TOLERANCE,
          "black width does not match the band parameters")
    check(abs(data["key_gap_px"] - params["key_gap_px"]) < TOLERANCE, "key gap drifted")

    expected = {
        "white": {"pivot_y_px": 14.4, "pivot_z_px": 4.0, "length_px": 4.0,
                  "thickness_px": 1.6, "dip_px": 0.4334},
        "black": {"pivot_y_px": 14.3, "pivot_z_px": 4.0, "length_px": 2.7,
                  "thickness_px": 2.4, "dip_px": 0.4334},
        "well": {"floor_top_y_px": 13.6, "back_front_z_px": 5.7, "back_bottom_y_px": 13.6},
    }
    for group, values in expected.items():
        for key, value in values.items():
            check(abs(data[group][key] - value) < TOLERANCE, f"{group}.{key} does not match the brief")

    for kind, texture in (("white", "piano_recolor_tex3"), ("black", "piano_recolor_tex4")):
        path = MODELS / f"piano_{kind}_key_standalone.json"
        check(path.is_file(), f"missing standalone {kind} key model")
        if not path.is_file():
            continue
        model = json.loads(path.read_text(encoding="utf-8"))
        check(model["textures"]["bb_texture_" + ("3" if kind == "white" else "4")]
              == f"pastoral_home:block/{texture}", f"{kind} key texture is wrong")
        check(len(model["elements"]) == 1, f"{kind} key model must be a single cuboid")
        element = model["elements"][0]
        width = data["white_face_width_px"] if kind == "white" else data["black_width_px"]
        # Element coords are pixel units; FaceBakery divides by 16 when baking.
        check(abs((element["to"][0] - element["from"][0]) - width) < 1e-4,
              f"{kind} key width is wrong")
        check(abs((element["to"][2] - element["from"][2]) - data[kind]["length_px"]) < TOLERANCE,
              f"{kind} key length is wrong")
        check(abs((element["to"][1] - element["from"][1]) - data[kind]["thickness_px"]) < TOLERANCE,
              f"{kind} key thickness is wrong")
        check(abs(element["to"][2]) < TOLERANCE, f"{kind} key pivot is not at its rear edge")

    item = json.loads((MODELS / "piano_item.json").read_text(encoding="utf-8"))
    names = [str(element.get("name", "")) for element in item["elements"]]
    check(names.count("item_white_key") == int(constants["WHITE_KEYS"]), "item model lost white keys")
    check(names.count("item_black_key") == 10, "item model lost black keys")

    for layer in range(2):
        for column in range(3):
            model = json.loads((MODELS / f"piano_l{layer}_c{column}.json").read_text(encoding="utf-8"))
            self_named = {str(element.get("name", "")) for element in model["elements"]}
            check("piano_white_key" not in self_named and "piano_black_key" not in self_named,
                  f"piano_l{layer}_c{column} bakes dynamic keys")
            values = set(model["textures"].values())
            check(not {"pastoral_home:block/piano_palette", "pastoral_home:block/piano_keys"} & values,
                  f"piano_l{layer}_c{column} still uses the retired programmatic key art")

    if failures:
        print("piano key report FAILED:")
        for failure in failures:
            print(" -", failure)
        return 1
    print(f"piano key report OK: pitch={pitch:.4f}, white face={data['white_face_width_px']:.4f}, "
          f"gap={data['key_gap_px']:.2f}, 15 white + 10 black standalone/item keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
