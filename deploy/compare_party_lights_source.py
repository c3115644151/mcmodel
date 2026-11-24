"""Diff the generated party-light models against the artist's .bbmodel, face by face.

Run this before trusting any screenshot: it proves the twelve models still carry every source cube
at the source position with the source uv, so a render that looks wrong is a render problem, not
silently lost geometry.  Exit code equals the number of mismatches.

    .venv\\Scripts\\python.exe tools/deploy/compare_party_lights_source.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
MODELS = ROOT / "src/main/resources/assets/pastoral_home/models/block"

CELL = 16.0
SHEET_V_SCALE = 0.25
SHELL_EXPAND = 0.5

MOUNT_OFFSETS = {
    "ceiling": (0.0, 10.0, 0.0),
    "wall": (0.0, 5.0, -5.0),
    "floor": (0.0, 10.0, 0.0),
}
GLOWS = ("none", "west", "east", "both")
# source cube index groups: shell, mount/neck, core
LAMPS = {"west": (3, 4, 5), "east": (0, 1, 2)}
PARTS = ("shell", "neck", "core")

problems: list[str] = []


def check(ok: bool, label: str) -> None:
    if not ok:
        problems.append(label)


def ordered(element: dict) -> tuple[list[float], list[float]]:
    low = [min(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    high = [max(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    return low, high


def near(a: list[float], b: list[float], eps: float = 1e-3) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= eps for x, y in zip(a, b))


def expected_uv(uv: list[float], expand: bool) -> list[float]:
    u0, v0, u1, v1 = (float(value) for value in uv)
    if expand:
        u0, u1 = min(u0, u1), max(u0, u1) + SHELL_EXPAND
        v0, v1 = min(v0, v1), max(v0, v1) + SHELL_EXPAND
    return [u0, round(v0 * SHEET_V_SCALE, 4), u1, round(v1 * SHEET_V_SCALE, 4)]


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    source = data["elements"]
    for i, texture in enumerate(data["textures"]):
        check(texture.get("uv_width") == 32 and texture.get("uv_height") == 32,
              f"source texture {i}: the project reads a 32x32 uv frame, not the whole strip")

    for mount in MOUNT_OFFSETS:
        offset = MOUNT_OFFSETS[mount]
        for glow in GLOWS:
            path = MODELS / f"party_lights_{mount}_{glow}.json"
            if not path.exists():
                problems.append(f"{path.name}: missing")
                continue
            model = json.loads(path.read_text(encoding="utf-8"))
            by_name = {element["name"]: element for element in model["elements"]}
            for side, indices in LAMPS.items():
                lit = glow in (side, "both")
                for part, index in zip(PARTS, indices):
                    name = f"{part}_{side}"
                    element = by_name.get(name)
                    check(element is not None, f"{path.name}: {name} lost")
                    if element is None:
                        continue
                    low, high = ordered(source[index])
                    want_low = [round(low[i] + offset[i], 4) for i in range(3)]
                    want_high = [round(high[i] + offset[i], 4) for i in range(3)]
                    check(near(element["from"], want_low) and near(element["to"], want_high),
                          f"{path.name}: {name} moved off the source cube "
                          f"({element['from']}..{element['to']} vs {want_low}..{want_high})")
                    src_faces = {face: spec for face, spec in source[index]["faces"].items()
                                 if spec.get("texture") is not None}
                    check(set(element["faces"]) == set(src_faces),
                          f"{path.name}: {name} face set differs from the source "
                          f"({sorted(element['faces'])} vs {sorted(src_faces)})")
                    for face, spec in src_faces.items():
                        got = element["faces"].get(face)
                        if got is None:
                            continue
                        want = expected_uv(spec["uv"], expand=(part == "shell"))
                        check(near(got["uv"], want),
                              f"{path.name}: {name}.{face} uv {got['uv']} != {want}")
                        want_ref = "#lamp_on" if (lit and part != "neck") else "#lamp_off"
                        check(got["texture"] == want_ref,
                              f"{path.name}: {name}.{face} reads {got['texture']}, wanted {want_ref}")
    if problems:
        for line in problems:
            print("FAIL", line)
        print(f"{len(problems)} mismatches against the source art")
        return len(problems)
    print("source parity: every cube, position, uv and palette matches the .bbmodel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
