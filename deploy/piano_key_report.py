#!/usr/bin/env python3
"""Assert the shipped piano keyboard against the numbers a real keyboard obeys.

The report reads the shipped assets (the palette sheet, the key sheet and the six cell
models), never the generator's memory, so a stale or hand-edited model fails here instead
of in-game. Numbers come first and images second: every claim about key pitch, seam width,
black-key proportions and uv density is a comparison, not an eyeball.

Run it through Gradle ("gradlew.bat testPianoKeys") or directly:
    .venv\Scripts\python.exe tools\deploy\piano_key_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/deploy"))

from prepare_piano_models import (  # noqa: E402
    ART_LIP_ROWS,
    ART_TEXELS,
    BED_TOP_Y,
    CASING_TOP_Y,
    DEPTH_EPSILON,
    FIELD_TOP_Y,
    KEYS_SIZE,
    KEYS_UV_PER_PX,
    PALETTE_SIZE,
    SHELF_TOP_Y,
    TEXELS_PER_BLOCK,
    TONES,
    black_key_boundaries,
    block_constants,
    load_band_params,
    white_key_width,
)

ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
PALETTE = ASSETS / "textures/block/piano_palette.png"
KEYS = ASSETS / "textures/block/piano_keys.png"

COLUMNS = 3
LAYERS = 2
TOLERANCE = 1e-6
DEPTH_RANGE = (DEPTH_EPSILON, 15.95)

PALETTE_TONE_BY_TEXEL = {texel: tone for tone, (texel, _) in TONES.items()}
PALETTE_UV_SCALE = PALETTE_SIZE / 16.0   # uv units are 1/16 of the sheet: multiply to get texels
KEYS_UV_SCALE = KEYS_SIZE / 16.0


def cell_path(layer: int, column: int) -> Path:
    return MODELS / f"piano_l{layer}_c{column}.json"


def load_cells() -> dict[tuple[int, int], dict]:
    cells = {}
    for layer in range(LAYERS):
        for column in range(COLUMNS):
            path = cell_path(layer, column)
            if not path.is_file():
                raise SystemExit(f"missing {path.relative_to(ROOT)}; run prepare_piano_models.py")
            cells[(layer, column)] = json.loads(path.read_text(encoding="utf-8"))
    return cells


def keyed(cells: dict) -> list[dict]:
    """Every named key piece, positioned in piano space rather than in its own cell."""
    pieces = []
    for (layer, column), model in cells.items():
        for element in model["elements"]:
            name = element.get("name", "")
            if not name.startswith("key_"):
                continue
            pieces.append({
                "cell": (layer, column),
                "layer": layer,
                "column": column,
                "name": name,
                "x0": element["from"][0] + 16.0 * column,
                "x1": element["to"][0] + 16.0 * column,
                "y0": element["from"][1],
                "y1": element["to"][1],
                "z0": element["from"][2],
                "z1": element["to"][2],
                "faces": element["faces"],
            })
    return pieces


def one(pieces: list[dict], name: str) -> list[dict]:
    return [piece for piece in pieces if piece["name"] == name]


def near(left: float, right: float, tol: float = TOLERANCE) -> bool:
    return abs(left - right) <= tol


def palette_checks(cells: dict) -> list[tuple[bool, str]]:
    """The palette sheet is four flat blocks and every face samples a block's middle."""
    from PIL import Image

    checks: list[tuple[bool, str]] = []
    if not PALETTE.is_file():
        return [(False, f"palette sheet {PALETTE.name} is missing")]
    sheet = Image.open(PALETTE).convert("RGBA")
    checks.append((sheet.size == (PALETTE_SIZE, PALETTE_SIZE),
                   f"the palette sheet is {PALETTE_SIZE}x{PALETTE_SIZE}"))

    wrong = []
    for tone, (texel, colour) in TONES.items():
        for y in range(0, PALETTE_SIZE, 4):
            for x in range(texel * TEXELS_PER_BLOCK, (texel + 1) * TEXELS_PER_BLOCK, 4):
                if sheet.getpixel((x, y)) != colour:
                    wrong.append(f"{tone} at {x},{y}")
    checks.append((not wrong, "every palette block is one flat tone"
                   + (f": {wrong[:3]}" if wrong else "")))

    # Faces that sample the palette must sit in the middle of a block, or the mip chain
    # blends two tones and the key band smears into a gradient at block scale.
    off_centre = []
    for (layer, column), model in cells.items():
        for element in model["elements"]:
            for face, definition in element.get("faces", {}).items():
                if definition.get("texture") != "#piano_palette":
                    continue
                uv = definition.get("uv")
                if uv is None:
                    off_centre.append(f"l{layer}c{column} {element.get('name') or '?'} {face}: no uv")
                    continue
                centre = (uv[0] + uv[2]) * 0.5 * PALETTE_UV_SCALE
                texel = int(centre // TEXELS_PER_BLOCK)
                middle = texel * TEXELS_PER_BLOCK + TEXELS_PER_BLOCK * 0.5
                tone = PALETTE_TONE_BY_TEXEL.get(texel)
                if tone is None or abs(centre - middle) > 1.0:
                    off_centre.append(f"{element.get('name') or '?'} {face} centre {centre:g}")
    checks.append((not off_centre, "every palette face samples the middle of one tone block"
                   + (f": {off_centre[:3]}" if off_centre else "")))
    return checks


def field_checks(pieces: list[dict], params: dict, constants: dict) -> list[tuple[bool, str]]:
    """The ivory field is one continuous band, exactly one pixel high, from lip to nameboard."""
    checks: list[tuple[bool, str]] = []
    fields = sorted(one(pieces, "key_field"), key=lambda piece: piece["x0"])

    wanted = int(COLUMNS)
    checks.append((len(fields) == wanted,
                   f"the ivory field is cut into {len(fields)} cell pieces"
                   + ("" if len(fields) == wanted else f", expected {wanted}")))

    if fields:
        gaps = []
        cursor = constants["KEY_MIN_X"]
        for piece in fields:
            if not near(piece["x0"], cursor, 1e-4):
                gaps.append(f"gap at {cursor:g} -> {piece['x0']:g}")
            cursor = piece["x1"]
        if not near(cursor, constants["KEY_MAX_X"], 1e-4):
            gaps.append(f"ends at {cursor:g}, expected {constants['KEY_MAX_X']:g}")
        checks.append((not gaps, "the three field pieces tile one continuous ivory band"
                       + (f": {gaps[:3]}" if gaps else "")))

    missing = [piece["name"] for piece in fields
               if "north" not in piece["faces"] or "up" not in piece["faces"]]
    checks.append((not missing, "every field piece keeps a front and a top face"
                   + (f": {missing[:3]}" if missing else "")))

    bad_y = [piece["name"] for piece in fields
             if not (near(piece["y0"], SHELF_TOP_Y) and near(piece["y1"], FIELD_TOP_Y))]
    checks.append((not bad_y, f"the ivory band is exactly {FIELD_TOP_Y - SHELF_TOP_Y:g} px tall "
                              f"at y {SHELF_TOP_Y:g}..{FIELD_TOP_Y:g}"
                   + (f": {bad_y[:3]}" if bad_y else "")))

    bad_z = [piece["name"] for piece in fields
             if not (near(piece["z0"], DEPTH_EPSILON) and near(piece["z1"], params["field_back_px"]))]
    checks.append((not bad_z, f"the field runs back to the nameboard at {params['field_back_px']:g} px"
                   + (f": {bad_z[:3]}" if bad_z else "")))

    return checks


def merged(pieces: list[dict]) -> list[dict]:
    """One logical key per name: a black key the cell seam cut comes back as one span."""
    merged: dict[str, dict] = {}
    for piece in pieces:
        entry = merged.setdefault(piece["name"], dict(piece))
        entry["x0"] = min(entry["x0"], piece["x0"])
        entry["x1"] = max(entry["x1"], piece["x1"])
    return list(merged.values())


def black_key_checks(pieces: list[dict], params: dict, constants: dict) -> list[tuple[bool, str]]:
    """Black keys: the semantics of a real keyboard, not a decorative stripe."""
    checks: list[tuple[bool, str]] = []
    blacks = merged([piece for piece in pieces if piece["name"].startswith("key_black")])
    boundaries = black_key_boundaries(constants)
    pitch = white_key_width(constants)
    depth = params["field_back_px"] - DEPTH_EPSILON

    checks.append((len(blacks) == len(boundaries),
                   f"{len(blacks)} black keys sit on the {len(boundaries)} semitone boundaries"))
    names = sorted(piece["name"] for piece in blacks)
    checks.append((names == sorted(f"key_black_{boundary}" for boundary in boundaries),
                   "every black key is named after the boundary it stands on"
                   + (f": {names[:3]}" if names else "")))

    widths = [piece["x1"] - piece["x0"] for piece in blacks]
    widest = max(widths) if widths else 0.0
    narrowest = min(widths) if widths else 0.0
    ratio = widest / pitch if pitch else 0.0
    checks.append((bool(widths) and near(widest, params["black_width_px"], 1e-4)
                   and near(narrowest, params["black_width_px"], 1e-4)
                   and 0.40 <= ratio <= 0.55,
                   f"the blacks are {widest:.4f} px wide, {ratio:.0%} of the {pitch:.4f} px pitch"))

    deep = [(piece["z1"] - piece["z0"]) / depth for piece in blacks] if blacks else []
    checks.append((bool(deep) and all(0.55 <= value <= 0.80 for value in deep),
                   f"the blacks cover {min(deep):.0%}..{max(deep):.0%} of the key depth"
                   if deep else "the blacks cover the key depth"))

    front = [(piece["z0"] - DEPTH_EPSILON) / depth for piece in blacks] if blacks else []
    checks.append((bool(front) and all(0.20 <= value <= 0.40 for value in front),
                   f"the blacks start {min(front):.0%}..{max(front):.0%} of the way back"
                   if front else "the blacks start a third of the way back"))

    gaps = [params["field_back_px"] - piece["z1"] for piece in blacks] if blacks else []
    checks.append((bool(gaps) and all(0.0 <= value <= 0.25 for value in gaps),
                   f"the blacks butt the nameboard within {max(gaps):.2f} px" if gaps
                   else "the blacks butt the nameboard"))

    raise_px = [piece["y1"] - FIELD_TOP_Y for piece in blacks] if blacks else []
    tall = [piece["name"] for piece in blacks if piece["y1"] > CASING_TOP_Y + TOLERANCE]
    checks.append((bool(raise_px) and all(near(value, params["black_raise_px"], 1e-4) for value in raise_px)
                   and not tall,
                   f"the blacks stand {params['black_raise_px']:g} px above the ivory and stay under "
                   f"the casing at {CASING_TOP_Y:g}"
                   + (f": {tall[:3]}" if tall else "")))
    return checks


def keys_sheet_checks(pieces: list[dict], constants: dict, params: dict) -> list[tuple[bool, str]]:
    """The key sheet: one light body, one shade texel on every key boundary, evenly spaced."""
    from PIL import Image

    checks: list[tuple[bool, str]] = []
    if not KEYS.is_file():
        return [(False, f"key sheet {KEYS.name} is missing")]
    sheet = Image.open(KEYS).convert("RGBA")
    checks.append((sheet.size == (KEYS_SIZE, KEYS_SIZE), f"the key sheet is {KEYS_SIZE}x{KEYS_SIZE}"))

    keys = int(constants["WHITE_KEYS"])
    span = (constants["KEY_MAX_X"] - constants["KEY_MIN_X"]) * KEYS_UV_PER_PX * KEYS_UV_SCALE
    wanted = [min(KEYS_SIZE - 1, int(round(boundary * span / keys))) for boundary in range(keys + 1)]
    row = [sheet.getpixel((x, 1)) for x in range(KEYS_SIZE)]
    shade = TONES["shade"][1]
    lights = TONES["light"][1]
    columns = [x for x, pixel in enumerate(row) if pixel == shade]
    checks.append((columns == wanted,
                   f"the sheet carries {len(columns)} boundary lines at {wanted[:4]}..." ))
    spread = [b - a for a, b in zip(columns, columns[1:])]
    checks.append((bool(spread) and len(set(spread)) == 1,
                   f"every boundary is {spread[0] if spread else 0} texels from the next"
                   if spread else "every boundary is evenly spaced"))

    runs = {}
    for x in columns:
        length = 0
        while x + length < KEYS_SIZE and row[x + length] == shade:
            length += 1
        runs[length] = runs.get(length, 0) + 1
    checks.append((list(runs) == [1], f"each boundary line is one texel wide: {runs}"))

    body = {pixel for pixel in row if pixel != shade}
    checks.append((body == {lights}, "the key bodies are one flat light tone"
                   + (f": {sorted(body)[:3]}" if body != {lights} else "")))

    fields = one(pieces, "key_field")
    total = (constants["KEY_MAX_X"] - constants["KEY_MIN_X"]) * KEYS_UV_PER_PX
    bad_density = []
    spans = []
    for piece in fields:
        definition = piece["faces"].get("north", {})
        if definition.get("texture") != "#piano_keys":
            bad_density.append(f"{piece['cell']} front is not the key sheet")
            continue
        uv = definition["uv"]
        width_px = piece["x1"] - piece["x0"]
        if not near((uv[2] - uv[0]) / width_px, KEYS_UV_PER_PX, 1e-4):
            bad_density.append(f"{piece['cell']} u density {(uv[2] - uv[0]) / width_px:g}")
        spans.append((uv[0], uv[2]))
    checks.append((not bad_density and all(
        min(spans)[0] >= -TOLERANCE and max(span[1] for span in spans) <= 16.0 + TOLERANCE
        for span in [spans]) if spans else False,
                   f"every field front samples {KEYS_UV_PER_PX} uv per pixel"
                   + (f": {bad_density[:3]}" if bad_density else "")))

    covered = sum(uv[1] - uv[0] for uv in spans) if spans else 0.0
    checks.append((bool(spans) and near(covered, total, 1e-3)
                   and near(min(uv[0] for uv in spans), 0.0, 1e-3)
                   and near(max(uv[1] for uv in spans), total, 1e-3),
                   f"the three fronts tile {total:g} uv of key span, {covered:g} accounted for"))

    flat = [piece["cell"] for piece in fields
            if piece["faces"].get("up", {}).get("texture") == "#piano_keys"]
    checks.append((not flat, "the ivory top face stays a flat tone, seams only on the front"
                   + (f": {flat[:3]}" if flat else "")))
    return checks


def seam_and_layer_checks(pieces: list[dict], constants_band: tuple[float, float]) -> list[tuple[bool, str]]:
    """Keys never leave the lower layer, never leave the depth cell, never cross the casing."""
    checks: list[tuple[bool, str]] = []
    leaked = [f"{piece['cell']} {piece['name']}" for piece in pieces if piece["layer"] != 0]
    checks.append((not leaked, "all key geometry stays in the lower layer"
                   + (f": {leaked[:3]}" if leaked else "")))

    outside = [piece["name"] for piece in pieces
               if not (DEPTH_RANGE[0] - TOLERANCE <= piece["z0"] and piece["z1"] <= DEPTH_RANGE[1] + TOLERANCE)]
    checks.append((not outside, "key geometry stays inside the cell depth range"
                   + (f": {outside[:3]}" if outside else "")))

    tall = [piece["name"] for piece in pieces if piece["y1"] > CASING_TOP_Y + TOLERANCE]
    checks.append((not tall, f"no key piece crosses the casing line at y {CASING_TOP_Y:g}"
                   + (f": {tall[:3]}" if tall else "")))

    # The wooden slip keeps the artist's lip rows, so its pixels still come out of piano.png.
    low = ART_LIP_ROWS[0] * 16.0 / ART_TEXELS
    high = ART_LIP_ROWS[1] * 16.0 / ART_TEXELS
    slips = one(pieces, "key_slip")
    wrong = [piece["cell"] for piece in slips
             if piece["faces"].get("north", {}).get("texture") != "#bb_texture_0"
             or not (near(piece["faces"]["north"]["uv"][1], low, 1e-4)
                     and near(piece["faces"]["north"]["uv"][3], high, 1e-4))]
    checks.append((bool(slips) and not wrong,
                   "the key slip keeps the artist's wooden lip rows "
                   f"{ART_LIP_ROWS[0]}..{ART_LIP_ROWS[1]}"
                   + (f": {wrong[:3]}" if wrong else "")))

    boards = [merged(one(pieces, "key_nameboard"))]
    names = boards[0]
    board_shape = [piece["name"] for piece in names
                   if not (near(piece["y0"], FIELD_TOP_Y) and near(piece["y1"], CASING_TOP_Y))
                   or not near(piece["z0"], 5.7, 0.15) or not near(piece["z1"], 6.0)]
    checks.append((bool(names) and not board_shape,
                   f"the nameboard closes the field from y {FIELD_TOP_Y:g} to the casing and "
                   "reaches the case interior"
                   + (f": {board_shape[:3]}" if board_shape else "")))

    slip_shape = [piece["name"] for piece in merged(slips)
                  if not (near(piece["y0"], BED_TOP_Y) and near(piece["y1"], SHELF_TOP_Y))]
    checks.append((bool(slips) and not slip_shape,
                   f"the wooden slip fills the fascia from y {BED_TOP_Y:g} to {SHELF_TOP_Y:g}"
                   + (f": {slip_shape[:3]}" if slip_shape else "")))

    # Neighbouring blacks must not overlap: an overlap would let one key's navy eat the gap
    # between two semitone groups, and the 2-3 grouping would stop reading.
    ordered = sorted(merged([piece for piece in pieces if piece["name"].startswith("key_black")]),
                     key=lambda piece: piece["x0"])
    collisions = [f"{left['name']}/{right['name']}"
                  for left, right in zip(ordered, ordered[1:])
                  if right["x0"] < left["x1"] - TOLERANCE]
    checks.append((not collisions, "no two black keys overlap"
                   + (f": {collisions[:3]}" if collisions else "")))

    outside_band = [piece["name"] for piece in pieces
                    if piece["x0"] < constants_band[0] - TOLERANCE
                    or piece["x1"] > constants_band[1] + TOLERANCE]
    checks.append((not outside_band, f"every key piece stays inside {constants_band[0]:g}..{constants_band[1]:g}"
                   + (f": {outside_band[:3]}" if outside_band else "")))

    carried = [piece["cell"] for piece in slips + one(pieces, "key_field") + one(pieces, "key_nameboard")
               if not (near(piece["y0"], BED_TOP_Y) or near(piece["y0"], SHELF_TOP_Y)
                       or near(piece["y0"], FIELD_TOP_Y))]
    checks.append((not carried, "every key piece starts on one of the shelf lines "
                                f"{BED_TOP_Y:g}/{SHELF_TOP_Y:g}/{FIELD_TOP_Y:g}"
                   + (f": {carried[:3]}" if carried else "")))
    return checks


def declaration_checks(cells: dict) -> list[tuple[bool, str]]:
    """A cell declares a sheet only when one of its faces samples it."""
    checks: list[tuple[bool, str]] = []
    unused = []
    unclaimed = []
    for (layer, column), model in cells.items():
        textures = model.get("textures", {})
        painted = {definition.get("texture") for element in model["elements"]
                   for definition in element.get("faces", {}).values()}
        for name in ("#piano_palette", "#piano_keys"):
            declared = name.lstrip("#") in textures
            if declared and name not in painted:
                unused.append(f"l{layer}c{column} {name}")
            if not declared and name in painted:
                unclaimed.append(f"l{layer}c{column} {name}")
    checks.append((not unused, "no cell declares a sheet none of its faces sample"
                   + (f": {unused[:3]}" if unused else "")))
    checks.append((not unclaimed, "no cell samples a sheet it does not declare"
                   + (f": {unclaimed[:3]}" if unclaimed else "")))
    return checks


def main() -> int:
    constants = block_constants()
    params = load_band_params()
    cells = load_cells()
    pieces = keyed(cells)

    checks: list[tuple[bool, str]] = []
    checks += palette_checks(cells)
    checks += field_checks(pieces, params, constants)
    checks += black_key_checks(pieces, params, constants)
    checks += keys_sheet_checks(pieces, constants, params)
    checks += seam_and_layer_checks(pieces, (constants["KEY_MIN_X"], constants["KEY_MAX_X"]))
    checks += declaration_checks(cells)

    pitch = white_key_width(constants)
    print(f"piano keyboard: {int(constants['WHITE_KEYS'])} white keys at {pitch:.4f} px pitch on a "
          f"continuous field, {len(merged([piece for piece in pieces if piece['name'].startswith('key_black')]))} "
          f"blacks {params['black_width_px']:.4f} px wide raised {params['black_raise_px']:g} px, "
          f"{len(pieces)} named key pieces in {COLUMNS * LAYERS} cell models")
    failed = 0
    for ok, message in checks:
        print(("  ok   " if ok else "  FAIL ") + message)
        failed += 0 if ok else 1
    print(f"{len(checks) - failed} of {len(checks)} checks passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())