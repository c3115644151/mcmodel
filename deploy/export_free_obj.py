#!/usr/bin/env python3
"""Export the record player's free-format Blockbench model as a NeoForge OBJ block model.

A java block model rotates an element on one axis only. The gramophone horn is five
tilted leaves plus a turntable disc, and the two side leaves carry three axes at
once, so every native-JSON attempt flattened one tilt and tore the disc into loose
plates. NeoForge's obj loader takes arbitrary geometry, so the horn keeps the
authored rotation and stays one closed fan.

The cabinet occupies one cell, so the authored pixels are centred on a 16px
footprint and divided by 16: the body lands inside the block the player placed
instead of straddling the seam to its neighbour.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE = ROOT / "tools/deploy/model_sources/instruments/record_player.bbmodel"
MODEL_DIR = ASSETS / "models/block"
TEXTURE = "pastoral_home:block/record_player"

sys.path.insert(0, str(ROOT / "tools/deploy"))
from gui_measure import apply_rotation  # noqa: E402
from item_icon_preview import FACE_VERTICES  # noqa: E402


# Screen-space axes of each face as seen from outside the cube: which element axes
# run right and down on that face. f(o, z) is the uv corner, matching the uv box
# [u1, v1, u2, v2] that Blockbench authored.
FACE_SCREEN = {
    "north": (lambda o, z: 1 - o[0], lambda o, z: 1 - o[1]),
    "south": (lambda o, z: o[0], lambda o, z: 1 - o[1]),
    "east": (lambda o, z: 1 - o[2], lambda o, z: 1 - o[1]),
    "west": (lambda o, z: o[2], lambda o, z: 1 - o[1]),
    "up": (lambda o, z: o[0], lambda o, z: 1 - o[2]),
    "down": (lambda o, z: o[0], lambda o, z: o[2]),
}
FACE_ORDER = ("north", "south", "east", "west", "up", "down")

# A leaf authored as a flat plate has no volume: only the two faces perpendicular
# to its missing axis exist. The other four are degenerate slivers that only add
# stray edges across the horn, so they are never emitted.
THIN_EPSILON = 0.05
AXIS_FACES = {0: ("west", "east"), 1: ("down", "up"), 2: ("north", "south")}


def emitted_faces(element: dict) -> tuple[str, ...]:
    """The faces a box actually owns: two for a plate, six for a solid cube."""
    low, high = element["from"], element["to"]
    thin = [axis for axis in range(3)
            if abs(float(high[axis]) - float(low[axis])) <= THIN_EPSILON]
    if len(thin) != 1:
        return FACE_ORDER
    return AXIS_FACES[thin[0]]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def visible_elements(model: dict) -> list[dict]:
    """Only the authored visibility flag may exclude an element."""
    return [element for element in model["elements"] if element.get("visibility", True)]


def face_points(element: dict, face: str) -> list[tuple[float, float, float]]:
    low, high = element["from"], element["to"]
    points = []
    for xbit, ybit, zbit in FACE_VERTICES[face]:
        point = (float(high[0] if xbit else low[0]),
                 float(high[1] if ybit else low[1]),
                 float(high[2] if zbit else low[2]))
        if element.get("rotation"):
            point = apply_rotation(point, element["rotation"], element.get("origin"))
        points.append(tuple(float(value) for value in point))
    return points


def face_uvs(element: dict, face: str, resolution: tuple[int, int]) -> list[tuple[float, float]]:
    uv = element["faces"][face].get("uv")
    if uv is None:
        return []
    u1, v1, u2, v2 = (float(value) for value in uv)
    if abs(u2 - u1) < 1e-6 or abs(v2 - v1) < 1e-6:
        # Blockbench leaves a flat uv box on the sides of a zero-thickness plate.
        # Those faces are invisible in the editor; drawing them samples one texel
        # row and shows up in world as a stray line across the model.
        return []
    width, height = resolution
    right, down = FACE_SCREEN[face]
    corner_bits = [(xbit, ybit, zbit) for xbit, ybit, zbit in FACE_VERTICES[face]]
    uvs = []
    for bits in corner_bits:
        s, t = right(bits, None), down(bits, None)
        uvs.append(((u1 + s * (u2 - u1)) / width, (v1 + t * (v2 - v1)) / height))
    return uvs


def model_bounds(elements: list[dict]) -> tuple[float, float, float, float, float, float]:
    xs, ys, zs = [], [], []
    for element in elements:
        for face in FACE_ORDER:
            if face not in element["faces"]:
                continue
            for point in face_points(element, face):
                xs.append(point[0])
                ys.append(point[1])
                zs.append(point[2])
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def build_obj(elements: list[dict], resolution: tuple[int, int]) -> tuple[str, int]:
    x0, y0, z0, x1, y1, z1 = model_bounds(elements)
    # The cabinet occupies one cell: centre the 17px body on the 16px footprint,
    # otherwise the wider assembly straddles the seam between two blocks.
    centre_offset = (16.0 - (x1 - x0)) * 0.5
    offset = (-x0 + centre_offset, -y0, -z0)

    lines = ["# Pastoral Home record player, exported from the free-format source",
             "mtllib record_player.mtl"]
    vertices: list[str] = []
    uvs: list[str] = []
    quads: list[str] = []
    vertex_count = 0
    uv_count = 0
    for element in elements:
        for face in emitted_faces(element):
            if face not in element["faces"]:
                continue
            corners_uv = face_uvs(element, face, resolution)
            if not corners_uv:
                continue
            base_v = vertex_count
            base_t = uv_count
            for point in face_points(element, face):
                vertices.append(f"v {(point[0] + offset[0]) / 16.0:.6f} "
                                f"{(point[1] + offset[1]) / 16.0:.6f} "
                                f"{(point[2] + offset[2]) / 16.0:.6f}")
                vertex_count += 1
            for u, v in corners_uv:
                uvs.append(f"vt {u:.6f} {v:.6f}")
                uv_count += 1
            quads.append("usemtl base")
            quads.append("f " + " ".join(f"{base_v + index + 1}/{base_t + index + 1}"
                                         for index in range(4)))
    lines.extend(vertices)
    lines.extend(uvs)
    lines.extend(quads)
    return "\n".join(lines) + "\n", len(quads) // 1


def write_material() -> str:
    return "\n".join([
        "# NeoForge resolves texture variables against the model's textures block.",
        "newmtl base",
        "Kd 1.0 1.0 1.0",
        "Ka 0.0 0.0 0.0",
        "Ks 0.0 0.0 0.0",
        "d 1.0",
        "illum 1",
        "map_Kd #texture0",
        "",
    ])


def write_texture(source: dict) -> int:
    """The model carries its own png; re-exporting it keeps the texture reproducible."""
    raw = source["textures"][0]["source"].split(",", 1)[1]
    data = base64.b64decode(raw)
    target = ASSETS / "textures/block/record_player.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return len(data)


def blockstate() -> dict:
    parts = []
    for facing, rotation in (("north", 0), ("east", 90), ("south", 180), ("west", 270)):
        apply = {"model": "pastoral_home:block/record_player"}
        if rotation:
            apply["y"] = rotation
        parts.append({"when": {"facing": facing}, "apply": apply})
    return {"multipart": parts}


def gui_display() -> dict:
    """Return minecraft:block/block's GUI display, unchanged.

    An earlier revision solved a per-model centering translation offline and pinned
    the yaw to the piano's 45 degrees. That combination showed the model's back face
    and displaced the icon by more than a third of a slot: the solved offset assumed
    a transform order Minecraft does not use. A block-shaped item is placed by the
    vanilla camera, so this model ships that camera verbatim.
    """
    return {"rotation": [30, 225, 0], "translation": [0, 0, 0], "scale": [0.625, 0.625, 0.625]}


def parsed_bounds(obj_text: str):
    """Return the OBJ vertex bounding box in model pixels."""
    xs, ys, zs = [], [], []
    for line in obj_text.splitlines():
        if line.startswith("v "):
            _, x, y, z = line.split()
            xs.append(float(x))
            ys.append(float(y))
            zs.append(float(z))
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def descriptor() -> dict:
    return {
        "loader": "neoforge:obj",
        "model": "pastoral_home:models/block/record_player.obj",
        "mtl_override": "pastoral_home:models/block/record_player.mtl",
        # The particle tile is the dedicated face texture, the way every other
        # furniture model in the mod names it.
        "textures": {"texture0": TEXTURE, "particle": "pastoral_home:block/record_player_particle"},
        "automatic_culling": False,
        "shade_quads": True,
        # The vt values below are already Minecraft's top-down v axis, so the loader
        # must not flip them a second time.
        "flip_v": False,
        "emissive_ambient": False,
        "display": {
            "gui": gui_display(),
            "ground": {"rotation": [0, 0, 0], "translation": [0, 3, 0], "scale": [0.3, 0.3, 0.3]},
            "fixed": {"rotation": [0, 180, 0], "translation": [0, 0, 0], "scale": [0.5, 0.5, 0.5]},
            "thirdperson_righthand": {"rotation": [75, 45, 0], "translation": [0, 2.5, 1.5], "scale": [0.3, 0.3, 0.3]},
            "thirdperson_lefthand": {"rotation": [75, 45, 0], "translation": [0, 2.5, 1.5], "scale": [0.3, 0.3, 0.3]},
            "firstperson_righthand": {"rotation": [0, 45, 0], "translation": [0, 2, 0], "scale": [0.28, 0.28, 0.28]},
            "firstperson_lefthand": {"rotation": [0, 45, 0], "translation": [0, 2, 0], "scale": [0.28, 0.28, 0.28]},
        },
    }


def main() -> None:
    source = load(SOURCE)
    if source.get("meta", {}).get("model_format") != "free":
        raise ValueError("Expected the authoring source to stay in Blockbench free format")
    resolution = (int(source["resolution"]["width"]), int(source["resolution"]["height"]))
    elements = visible_elements(source)
    obj, faces = build_obj(elements, resolution)
    (MODEL_DIR / "record_player.obj").write_text(obj, encoding="utf-8")
    (MODEL_DIR / "record_player.mtl").write_text(write_material(), encoding="utf-8")
    texture_bytes = write_texture(source)
    save(MODEL_DIR / "record_player.json", descriptor())
    save(ASSETS / "blockstates/record_player.json", blockstate())
    save(ASSETS / "items/record_player.json",
         {"model": {"type": "minecraft:model", "model": "pastoral_home:block/record_player"}})
    x0, y0, z0, x1, y1, z1 = model_bounds(elements)
    print(f"record_player.obj: {len(elements)} elements, {faces // 2} quads, "
          f"texture {texture_bytes} bytes, "
          f"bounds {x0:.3f} {y0:.3f} {z0:.3f} -> {x1:.3f} {y1:.3f} {z1:.3f}"
          f" (offset x {(16.0 - (x1 - x0)) * 0.5 - x0:.3f} y {-y0:.3f} z {-z0:.3f})")


if __name__ == "__main__":
    main()
