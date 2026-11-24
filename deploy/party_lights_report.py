#!/usr/bin/env python3
"""Check the generated party-light model against the artist's own .bbmodel.

One cell carries one lamp, the geometry is the three cubes the artist drew, and the strip ships as a
four-frame animation. The gate is therefore mostly a *difference* check: every face uv, every cube
box, every texel of the strip, and the animation descriptor must still equal what the source file
says. Pictures are the illustration; the numbers are the gate, because this lamp has been misread
from small screenshots three times.

The frame is the unit that matters. One 16x16 uv space covers one 32x32 frame, so the gate also
proves that every face samples a solid window inside a single frame - no transparent texel, no
straddling of a frame boundary - because that is precisely what the strip-as-one-image mistake broke.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures/block"
STATE = ASSETS / "blockstates/party_lights.json"
SOURCE = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"

SHELL = 4.0
CORE = 3.0
NECK = [2.0, 1.0, 2.0]
CELL = 16.0
LAMP_BOTTOM_Y = 1.0
LAMP_SHIFT_X = -4.0

FRAME_SIZE = 32
FRAME_COUNT = 4
TEXELS_PER_UV = FRAME_SIZE / 16.0
SHEET_INDEX = 0
# One artist sheet, two opacities: the shell keeps the artist's texels at alpha 190 (paper over a
# bulb), the core keeps them opaque. The window checks below prove both read the same frame.
SHELL_SHEET = "party_lights_shell.png"
CORE_SHEET = "party_lights_core.png"
SHELL_TEXTURE = "pastoral_home:block/party_lights_shell"
CORE_TEXTURE = "pastoral_home:block/party_lights_core"
SHELL_ALPHA = 140
# The two opacity variants of the same artist sheet. The particle texture is a separate key that
# only the break effect reads, so it is excluded rather than required.
EXPECTED_TEXTURES = {SHELL_TEXTURE, CORE_TEXTURE}

FACINGS = (("north", 0), ("east", 90), ("south", 180), ("west", 270))
MODES = ("off", "chase", "steady")
LITS = ("false", "true")

checks: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    checks.append((bool(ok), label))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def named(model: dict, name: str) -> dict:
    hits = [element for element in model["elements"] if element.get("name") == name]
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one {name} element, found {len(hits)}")
    return hits[0]


def box(element: dict) -> tuple[list[float], list[float]]:
    return [float(v) for v in element["from"]], [float(v) for v in element["to"]]


def source_box(index: int) -> tuple[list[float], list[float]]:
    element = load(SOURCE)["elements"][index]
    low = [min(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    high = [max(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    return low, high


def source_strip() -> Image.Image:
    data = load(SOURCE)
    raw = base64.b64decode(data["textures"][SHEET_INDEX]["source"].split(",", 1)[1])
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def frame_of(index: int) -> Image.Image:
    strip = source_strip()
    top = index * FRAME_SIZE
    return strip.crop((0, top, FRAME_SIZE, top + FRAME_SIZE))


def same_box(actual, expected, shift_x: float = 0.0) -> bool:
    for axis in range(3):
        offset = shift_x if axis == 0 else 0.0
        if abs(actual[0][axis] - (expected[0][axis] + offset)) > 1e-4:
            return False
        if abs(actual[1][axis] - (expected[1][axis] + offset)) > 1e-4:
            return False
    return True


def geometry_checks() -> None:
    for name in ("party_lights", "party_lights_inventory"):
        model = load(MODELS / f"{name}.json")
        check(len(model["elements"]) == 3, f"geometry: {name} is the artist's three cubes "
                                           f"({len(model['elements'])})")
        check(model.get("parent") == "minecraft:block/block", f"geometry: {name} declares a parent")
        for label, index in (("shell", 0), ("core", 2), ("neck", 1)):
            element = named(model, label)
            expected = source_box(index)
            check(same_box(box(element), expected, LAMP_SHIFT_X),
                  f"geometry: {name} {label} sits where the artist drew it")
        shell_low, shell_high = box(named(model, "shell"))
        core_low, core_high = box(named(model, "core"))
        neck_low, neck_high = box(named(model, "neck"))
        check(abs((shell_high[0] - shell_low[0]) - SHELL) < 1e-4
              and abs((shell_high[1] - shell_low[1]) - SHELL) < 1e-4, "geometry: the cage is 4x4x4")
        check(abs((core_high[0] - core_low[0]) - CORE) < 1e-4
              and abs((core_high[1] - core_low[1]) - CORE) < 1e-4, "geometry: the core is 3x3x3")
        check(all(core_low[axis] > shell_low[axis] and core_high[axis] < shell_high[axis]
                  for axis in range(3)), "geometry: the core is fully inside the cage")
        check(abs((neck_high[0] - neck_low[0]) - NECK[0]) < 1e-4
              and abs((neck_high[1] - neck_low[1]) - NECK[1]) < 1e-4
              and abs((neck_high[2] - neck_low[2]) - NECK[2]) < 1e-4,
              "geometry: the hanger is the artist's 2x1x2 cap")
        check(abs(neck_low[1] - shell_high[1]) < 1e-4, "geometry: the hanger sits on top of the cage")
        centre = (shell_low[0] + shell_high[0]) / 2.0
        check(abs(centre - CELL / 2.0) < 1e-4, f"geometry: the cage is centred in the cell ({centre})")
        check(abs(shell_low[1] - LAMP_BOTTOM_Y) < 1e-4, "geometry: the lamp keeps the artist's y 1..6")


def uv_checks() -> None:
    elements = load(SOURCE)["elements"]
    for name in ("party_lights", "party_lights_inventory"):
        model = load(MODELS / f"{name}.json")
        textures = model["textures"]
        drawn = {value for key, value in textures.items() if "particle" not in key}
        check(drawn == EXPECTED_TEXTURES,
              f"uv: {name} reads the artist sheet through both opacity variants ({sorted(drawn)})")
        for label, index in (("shell", 0), ("core", 2), ("neck", 1)):
            element = named(model, label)
            source = elements[index]
            painted = {face for face, spec in source["faces"].items() if spec.get("texture") is not None}
            check(set(element["faces"]) == painted,
                  f"uv: {name} {label} paints exactly the faces the artist painted "
                  f"({len(painted)} faces)")
            for face, spec in element["faces"].items():
                want = [float(value) for value in source["faces"][face]["uv"]]
                check([round(float(v), 4) for v in spec["uv"]] == [round(v, 4) for v in want],
                      f"uv: {name} {label}.{face} keeps the artist's uv verbatim {want}")
                key = "#lamp_shell" if label == "shell" else "#lamp_core"
                check(spec["texture"] == key,
                      f"uv: {name} {label}.{face} reads {key}, the variant the element asks for")


def element_order() -> list[str]:
    model = load(MODELS / "party_lights.json")
    return [element.get("name") for element in model["elements"]]


def order_checks() -> None:
    """Draw order inside one collection decides who wins the translucent pass: core first, shell last.

    Every quad of a block model shares a single render type, and a chunk section sorts by block, not
    by quad - so the json element order is the paint order. Shell before core paints the opaque core
    on top of the paper and turns the lamp into a cream brick; that mistake was measured in game.
    """
    order = element_order()
    check(order.index("core") < order.index("shell"),
          f"order: the core is drawn before the shell so the paper blends over it ({order})")


def strip_checks() -> None:
    source = source_strip()
    core_path = TEXTURES / CORE_SHEET
    check(core_path.exists(), f"sheet: {CORE_SHEET} exists")
    if core_path.exists():
        shipped = Image.open(core_path).convert("RGBA")
        check(shipped.size == source.size,
              f"sheet: {CORE_SHEET} keeps the artist's {FRAME_COUNT}-frame size {source.size}")
        check(list(shipped.getdata()) == list(source.getdata()),
              f"sheet: {CORE_SHEET} equals source sheet {SHEET_INDEX} texel for texel")
    shell_path = TEXTURES / SHELL_SHEET
    check(shell_path.exists(), f"sheet: {SHELL_SHEET} exists")
    if shell_path.exists():
        shipped = Image.open(shell_path).convert("RGBA")
        check(shipped.size == source.size,
              f"sheet: {SHELL_SHEET} keeps the artist's {FRAME_COUNT}-frame size {source.size}")
        rgb_equal = all(a[:3] == b[:3] for a, b in zip(shipped.getdata(), source.getdata()))
        check(rgb_equal, "sheet: the shell keeps every artist texel's colour")
        alpha_ok = all((a[3] == SHELL_ALPHA if b[3] else a[3] == 0)
                       for a, b in zip(shipped.getdata(), source.getdata()))
        check(alpha_ok, f"sheet: the shell is the same texels at alpha {SHELL_ALPHA}, clear stays clear")
    for name in (SHELL_SHEET, CORE_SHEET):
        meta_path = TEXTURES / f"{name}.mcmeta"
        check(meta_path.exists(), f"sheet: {name}.mcmeta exists, so the frames actually play")
        if not meta_path.exists():
            continue
        animation = load(meta_path).get("animation") or {}
        check(animation.get("frametime") == 4,
              f"sheet: {name} runs 4 ticks per frame ({animation.get('frametime')})")
        frames = animation.get("frames")
        check(frames is None or len(frames) == FRAME_COUNT,
              f"sheet: {name} cycles all {FRAME_COUNT} frames ({frames})")
    for stale in ("party_lights_off.png", "party_lights_on.png", "party_lights_a.png",
                  "party_lights_b.png", "party_lights_shell_off.png", "party_lights_shell_on.png",
                  "party_lights_neck.png", "party_lights.png"):
        check(not (TEXTURES / stale).exists(), f"sheet: superseded {stale} is gone")
    for stale in ("party_lights_off.json", "party_lights_on.json"):
        check(not (MODELS / stale).exists(), f"sheet: superseded {stale} is gone")


def window_checks() -> None:
    """Every face must sample solid texels inside one frame - the invariant the strip mistake broke."""
    model = load(MODELS / "party_lights.json")
    frames = [frame_of(index) for index in range(FRAME_COUNT)]
    for label in ("shell", "core", "neck"):
        element = named(model, label)
        for face, spec in element["faces"].items():
            u0, v0, u1, v1 = (float(v) for v in spec["uv"])
            x0, x1 = sorted((int(round(u0 * TEXELS_PER_UV)), int(round(u1 * TEXELS_PER_UV))))
            y0, y1 = sorted((int(round(v0 * TEXELS_PER_UV)), int(round(v1 * TEXELS_PER_UV))))
            inside = 0 <= x0 < x1 <= FRAME_SIZE and 0 <= y0 < y1 <= FRAME_SIZE
            check(inside, f"window: {label}.{face} stays inside one {FRAME_SIZE}px frame "
                          f"(x{x0}..{x1} y{y0}..{y1})")
            if not inside:
                continue
            for index, frame in enumerate(frames):
                pixels = [frame.getpixel((x, y))
                          for x in range(x0, x1) for y in range(y0, y1)]
                clear = sum(1 for pixel in pixels if pixel[3] == 0)
                check(clear == 0, f"window: {label}.{face} on frame {index} samples no transparent "
                                  f"texel ({clear} of {len(pixels)})")
                tones = {pixel[:3] for pixel in pixels}
                check(len(tones) <= 3, f"window: {label}.{face} on frame {index} samples one tile, "
                                       f"not a seam ({len(tones)} tones)")


def state_checks() -> None:
    variants = load(STATE)["variants"]
    expected = {f"facing={facing},mode={mode},lit={lit}"
                for facing, _ in FACINGS for mode in MODES for lit in LITS}
    check(set(variants) == expected, f"state: blockstates cover {len(expected)} combinations "
                                     f"({len(variants)})")
    for facing, rotation in FACINGS:
        for mode in MODES:
            for lit in LITS:
                entry = variants[f"facing={facing},mode={mode},lit={lit}"]
                check(entry["model"] == "pastoral_home:block/party_lights",
                      f"state: {facing}/{mode}/{lit} draws the single lamp model")
                check(entry.get("y", 0) == rotation,
                      f"state: {facing}/{mode}/{lit} rotates {rotation} degrees")


def main() -> int:
    geometry_checks()
    uv_checks()
    order_checks()
    strip_checks()
    window_checks()
    state_checks()
    failed = [label for ok, label in checks if not ok]
    for ok, label in checks:
        print(("PASS " if ok else "FAIL ") + label)
    print(f"{len(checks) - len(failed)} of {len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
