"""Build the party-lights block model straight from the artist's .bbmodel, animated by its own frames.

The artist's texture is a 32x128 strip of four 32x32 frames, and each frame is a pre-unwrapped atlas:
one corner carries the shell's orange, another the pale core, another the grey hanger, and every face
of every cube points its uv at the matching tile. The strip is a real animation, not a palette pair -
frame 0-1 are the dim lamp, frame 2-3 the lit one - so the block ships the strip unchanged with a
.mcmeta that cycles the four frames, and the lamp breathes on its own exactly like the .bbmodel.

That also settles uv. An animated texture maps the whole 0..1 space onto the *current* 32x32 frame,
so one uv unit is two texels and the artist's uv stays verbatim: a 4x4 shell face reads a solid orange
4x4 window, the 3x3 core solid cream, the 2x1x2 hanger solid grey. Reading the strip as one tall
static image stretches v by four, makes every window straddle all four frames and turns each face
into a banded, holed mess - a mistake that shipped twice and cost a week.

One lamp, one block. The twin the artist drew was dropped by request; a cell places exactly one lamp
and multi-lamp behaviour is a later chapter. No texel is repainted and no uv is scaled: the gate
compares the shipped strip texel for texel against the source and checks every face window inside a
single frame.

Run: .venv/Scripts/python.exe tools/deploy/prepare_party_lights_models.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools/deploy/model_sources/party_lights/party_lights.bbmodel"
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures/block"
BLOCKSTATES = ASSETS / "blockstates"

# The lamp that survives is the one drawn with texture 0; its sheet ships in two alpha variants.
SHEET_INDEX = 0
SHELL_TEXTURE = "pastoral_home:block/party_lights_shell"
CORE_TEXTURE = "pastoral_home:block/party_lights_core"
# Paper, not pigment: the artist's orange is translucent paper over a lit bulb, and Blockbench
# previews it that way. Opaque texels read as a solid cube, so the shell keeps the artist's pattern
# at a reduced alpha while the core keeps alpha 255 - the same texels, two opacities.
# 140 measured closest to the viewport: 100 lets the pale core dominate, 180 packs it back into a
# solid orange block. Sweep it again with param_sweep.py if the sheet changes.
SHELL_ALPHA = 140
FRAME_SIZE = 32
FRAME_COUNT = 4
# Four ticks per frame: the same 0.2 s cadence Blockbench previews, one full breath in 0.8 s.
FRAME_TICKS = 4

# Source cubes of the one lamp that survives: shell, hanger, core.
LAMP = (0, 1, 2)

# The dropped twin sat at sheet x 2..6, so the kept lamp needs 4 px back to be centred.
LAMP_SHIFT = (-4.0, 0.0, 0.0)

FACINGS = ("north", "east", "south", "west")
Y_ROTATION = {"north": 0, "east": 90, "south": 180, "west": 270}
MODES = ("off", "chase", "steady")
LIT_STATES = ("false", "true")


def load_source() -> dict:
    return json.loads(SRC.read_text(encoding="utf-8"))


def sheet_rgba(data: dict, index: int) -> Image.Image:
    """The artist's strip, four frames stacked vertically."""
    raw = base64.b64decode(data["textures"][index]["source"].split(",", 1)[1])
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def ordered(element: dict) -> tuple[list[float], list[float]]:
    """The artist stores the cage with the z axis reversed; the model format wants from <= to."""
    low = [min(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    high = [max(float(element["from"][i]), float(element["to"][i])) for i in range(3)]
    return low, high


def shifted(box: tuple[list[float], list[float]], offset) -> tuple[list[float], list[float]]:
    low = [round(box[0][i] + offset[i], 4) for i in range(3)]
    high = [round(box[1][i] + offset[i], 4) for i in range(3)]
    return low, high


def source_faces(element: dict, texture: str) -> dict:
    """Every face keeps the artist's uv verbatim; only faces the artist left untextured are skipped."""
    return {face: {"texture": texture, "uv": [float(value) for value in spec["uv"]]}
            for face, spec in element["faces"].items()
            if spec.get("texture") is not None}


def lamp_elements(data: dict) -> list[dict]:
    elements = data["elements"]
    out: list[dict] = []
    # Draw order inside one block model decides who wins the translucent pass, because every quad of
    # a collection shares one render type and the section sorts by block, not by quad. The core goes
    # first so the shell's paper blends over it; shell first would paint the core on top and turn the
    # lamp into a cream brick (that mistake was measured, not guessed).
    for name, index, key in (("core", LAMP[2], "#lamp_core"),
                             ("shell", LAMP[0], "#lamp_shell"),
                             ("neck", LAMP[1], "#lamp_core")):
        low, high = shifted(ordered(elements[index]), LAMP_SHIFT)
        out.append({"name": name, "from": low, "to": high,
                    "faces": source_faces(elements[index], key)})
    return out


def write_texture(data: dict) -> None:
    strip = sheet_rgba(data, SHEET_INDEX)
    if strip.size != (FRAME_SIZE, FRAME_SIZE * FRAME_COUNT):
        raise SystemExit(f"source sheet is {strip.size}, expected "
                         f"{FRAME_SIZE}x{FRAME_SIZE * FRAME_COUNT}")
    # The animation descriptor is what makes the four frames play; without it the strip is one tall
    # image and every uv window straddles frames. Both opacity variants animate in lockstep.
    meta = json.dumps({"animation": {"frametime": FRAME_TICKS}}, ensure_ascii=False, indent=2) + "\n"
    core = strip
    shell = strip.copy()
    pixels = shell.load()
    for y in range(shell.height):
        for x in range(shell.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha:
                pixels[x, y] = (red, green, blue, SHELL_ALPHA)
    for name, image in (("party_lights_core", core), ("party_lights_shell", shell)):
        image.save(TEXTURES / f"{name}.png")
        (TEXTURES / f"{name}.png.mcmeta").write_text(meta, encoding="utf-8")
    print(f"wrote textures/block/party_lights_{{core,shell}}.png {strip.width}x{strip.height} "
          f"+ .mcmeta ({FRAME_COUNT} frames, {FRAME_TICKS} ticks each, shell alpha {SHELL_ALPHA})")


def write_model(path: Path, elements: list[dict]) -> None:
    # validateModels insists on a parent for every block model. Ambient occlusion is left at the
    # vanilla default: tools/deploy/normalize_block_model_lighting.py restores it for every model
    # that has no documented mask exception, and this lamp is an ordinary lattice, not a mask.
    model = {
        "parent": "minecraft:block/block",
        "credit": "Derived from the artist's 彩灯.bbmodel",
        "textures": {"particle": SHELL_TEXTURE,
                     "lamp_shell": SHELL_TEXTURE,
                     "lamp_core": CORE_TEXTURE},
        "elements": elements,
    }
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_blockstates() -> None:
    variants = {}
    for facing in FACINGS:
        for mode in MODES:
            for lit in LIT_STATES:
                entry: dict = {"model": "pastoral_home:block/party_lights"}
                if Y_ROTATION[facing]:
                    entry["y"] = Y_ROTATION[facing]
                variants[f"facing={facing},mode={mode},lit={lit}"] = entry
    BLOCKSTATES.mkdir(parents=True, exist_ok=True)
    (BLOCKSTATES / "party_lights.json").write_text(
        json.dumps({"variants": variants}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote blockstates/party_lights.json ({len(variants)} variants, one model)")


def mirror_to_build() -> None:
    """Copy the lamp's assets into build/resources/main so a running dev client picks them up.

    processResources costs a minute and a client restart costs four; the dev client reads assets
    straight out of build/resources/main, so a generator that supports --mirror closes the loop at
    "regenerate, then /pastoral_home_preview reload". See design/dev-hot-reload.md.
    """
    built = ROOT / "build/resources/main/assets/pastoral_home"
    copied = []
    for source_dir in (MODELS, TEXTURES, BLOCKSTATES):
        for path in source_dir.glob("party_lights*"):
            target = built / path.relative_to(ASSETS)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            copied.append(target.relative_to(ROOT))
    for source_dir in (MODELS, TEXTURES, BLOCKSTATES):
        for path in (built / source_dir.relative_to(ASSETS)).glob("party_lights*"):
            if not (ASSETS / path.relative_to(built)).exists():
                path.unlink()
                copied.append(f"removed {path.relative_to(ROOT)}")
    for rel in copied:
        print(f"mirrored {rel}")


def main() -> None:
    data = load_source()
    TEXTURES.mkdir(parents=True, exist_ok=True)
    write_texture(data)

    for stale in ("party_lights_off.png", "party_lights_on.png", "party_lights_a.png",
                  "party_lights_b.png", "party_lights_neck.png", "party_lights.png"):
        target = TEXTURES / stale
        if target.exists():
            target.unlink()
            print(f"removed superseded {target.relative_to(ROOT)}")

    MODELS.mkdir(parents=True, exist_ok=True)
    elements = lamp_elements(data)
    write_model(MODELS / "party_lights.json", elements)
    print(f"wrote models/block/party_lights.json ({len(elements)} elements)")
    write_model(MODELS / "party_lights_inventory.json", elements)
    print("wrote models/block/party_lights_inventory.json")
    for stale in ("party_lights_off.json", "party_lights_on.json"):
        target = MODELS / stale
        if target.exists():
            target.unlink()
            print(f"removed superseded {target.relative_to(ROOT)}")
    write_blockstates()
    if "--mirror" in sys.argv[1:]:
        mirror_to_build()


if __name__ == "__main__":
    main()
