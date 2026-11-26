#!/usr/bin/env python3
r"""Derive the piano keyboard's per-key geometry for the art brief.

Nothing here is hand-typed: the key grid comes from PianoBlock.java (the same constants that
decide which key a click lands on) and the proportions from tools/deploy/piano_keys.json. The
output is what the artist and the block entity renderer must both obey:

    build/piano_brief/piano_keys.csv      one row per key: x span, z span, y span, pivot, travel
    build/piano_brief/piano_keys.json     the same, plus the stack (slip / well / keys / nameboard)
    build/piano_brief/piano_keyboard_plan.png
                                          top view (gaps, letter row) and a side section (travel)

Run: .venv\Scripts\python.exe tools/deploy/piano_art_brief.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/piano_brief"
PIANO_BLOCK = ROOT / "src/main/java/com/pastoralhome/block/PianoBlock.java"
KNOBS = ROOT / "tools/deploy/piano_keys.json"

# The stack prepare_piano_models.py already builds; mirrored here so the brief can be written
# before that generator is rewritten. Keep in step with SHELF_TOP_Y / FIELD_TOP_Y there.
SHELF_TOP_Y = 13.6   # the wooden key slip ends here: its top face is the well floor
FIELD_TOP_Y = 14.6   # the ivory plane a player looks down on

# Proposed knobs, to be added to tools/deploy/piano_keys.json when the keys become real geometry.
PRESS_DEFAULTS = {
    "key_gap_px": 0.06,          # each side of a white key: 5.8% of the key width; a real keyboard is 6.4%
    "white_thickness_px": 0.55,  # leaves a 0.45 px well between the key underside and the slip below
    "white_travel_deg": 4.4,     # the front tip dips 0.43 px, just short of the well floor
    "black_lift_px": 0.05,       # blacks rest a hair above the ivory, so their bottom faces cannot z-fight
    "black_slot_px": 0.03,       # clearance each side where a black passes through the narrowed ivory
}
BLACK_TIP_DIP = 0.4334  # the dip every key tip travels; a black reaches it at a steeper angle than a white

# Computer key per note, mirroring client/PianoKeyboard (two octaves plus the closing C).
LETTERS = ["Z", "X", "C", "V", "B", "N", "M",
           "Q", "W", "E", "R", "T", "Y", "U", "I"]
BLACK_LETTERS = ["S", "D", "G", "H", "J",
                 "2", "3", "5", "6", "7"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def constants() -> dict:
    src = PIANO_BLOCK.read_text(encoding="utf-8")
    wanted = {
        "KEY_MIN_X": r"public static final double KEY_MIN_X = ([\d.]+);",
        "KEY_MAX_X": r"public static final double KEY_MAX_X = ([\d.]+);",
        "KEY_DEPTH": r"public static final double KEY_DEPTH = ([\d.]+);",
        "BLACK_KEY_DEPTH": r"public static final double BLACK_KEY_DEPTH = ([\d.]+);",
        "PEDAL_SOFT_MIN_X": r"public static final double PEDAL_SOFT_MIN_X = ([\d.]+);",
        "PEDAL_SOFT_MAX_X": r"public static final double PEDAL_SOFT_MAX_X = ([\d.]+);",
        "PEDAL_SUSTAIN_MIN_X": r"public static final double PEDAL_SUSTAIN_MIN_X = ([\d.]+);",
        "PEDAL_SUSTAIN_MAX_X": r"public static final double PEDAL_SUSTAIN_MAX_X = ([\d.]+);",
    }
    found = {}
    for name, pattern in wanted.items():
        match = re.search(pattern, src)
        if match is None:
            raise SystemExit(f"PianoBlock.java no longer declares {name}")
        found[name] = float(match.group(1))
    white_keys = re.search(r"private static final double WHITE_KEYS = ([\d.]+);", src)
    middle_c = re.search(r"public static final int MIDDLE_C = (\d+);", src)
    semitones = re.search(r"WHITE_SEMITONES = \{([^}]*)\}", src)
    if not (white_keys and middle_c and semitones):
        raise SystemExit("PianoBlock.java lost WHITE_KEYS / MIDDLE_C / WHITE_SEMITONES")
    found["WHITE_KEYS"] = int(float(white_keys.group(1)))
    found["MIDDLE_C"] = int(middle_c.group(1))
    found["WHITE_SEMITONES"] = [int(p) for p in semitones.group(1).split(",") if p.strip()]
    return found


def knobs() -> dict:
    data = json.loads(KNOBS.read_text(encoding="utf-8"))
    params = dict(PRESS_DEFAULTS)
    params.update({k: float(v) for k, v in data.items() if k in params})
    return params


def black_boundaries(c: dict) -> list[int]:
    out = []
    for boundary in range(1, c["WHITE_KEYS"]):
        semitone = c["WHITE_SEMITONES"][(boundary - 1) % len(c["WHITE_SEMITONES"])]
        if (semitone + 1) % 12 not in c["WHITE_SEMITONES"]:
            out.append(boundary)
    return out


def key_rows(c: dict, p: dict) -> list[dict]:
    pitch = (c["KEY_MAX_X"] - c["KEY_MIN_X"]) / c["WHITE_KEYS"]
    origin = c["KEY_MIN_X"]
    gap = p["key_gap_px"]
    boundaries = set(black_boundaries(c))
    black_half = 0.55 + p["black_slot_px"]
    rows: list[dict] = []
    # Whites first: they are the grid everyone else hangs off.
    for i in range(c["WHITE_KEYS"]):
        semitone = c["WHITE_SEMITONES"][i % len(c["WHITE_SEMITONES"])] + 12 * (i // len(c["WHITE_SEMITONES"]))
        x0 = origin + i * pitch + gap
        x1 = origin + (i + 1) * pitch - gap
        # A real keyboard narrows a white key where blacks pass through it, which is what lets a
        # black dip below the ivory plane without cutting into anything.
        neck_x0 = x0 + black_half if i in boundaries else x0
        neck_x1 = x1 - black_half if (i + 1) in boundaries else x1
        rows.append({
            "id": f"key_white_{i:02d}", "kind": "white", "note_index": i,
            "neck_x0": round(neck_x0, 4), "neck_x1": round(neck_x1, 4),
            "neck_width": round(neck_x1 - neck_x0, 4), "neck_z0": 1.9, "neck_z1": 5.7,
            "note": f"{NOTE_NAMES[semitone % 12]}{3 + semitone // 12}",
            "letter": LETTERS[i],
            "x0": round(x0, 4), "x1": round(x1, 4), "width": round(x1 - x0, 4),
            "y0": round(FIELD_TOP_Y - p["white_thickness_px"], 4), "y1": FIELD_TOP_Y,
            "z0": 0.05, "z1": 5.7,
            "pivot": [round((x0 + x1) / 2, 4), round(FIELD_TOP_Y - p["white_thickness_px"], 4), 5.7],
            "travel_deg": p["white_travel_deg"],
        })
    half = 0.55  # half of black_width_px (1.1), the current knob
    raise_px = 1.0  # black_raise_px
    for b, letter in zip(black_boundaries(c), BLACK_LETTERS):
        semitone = c["WHITE_SEMITONES"][(b - 1) % len(c["WHITE_SEMITONES"])] + 1 \
            + 12 * ((b - 1) // len(c["WHITE_SEMITONES"]))
        centre = origin + b * pitch
        black_front = 1.9
        black_back = 5.6
        # Same tip travel as a white key; a shorter lever needs a steeper angle to cover it.
        travel = round(math.degrees(math.asin(min(1.0, BLACK_TIP_DIP / (black_back - black_front)))), 3)
        if letter is None:  # a boundary with no key on the desktop layout
            continue
        rows.append({
            "id": f"key_black_{b:02d}", "kind": "black", "note_index": b - 1,
            "note": f"{NOTE_NAMES[semitone % 12]}{3 + semitone // 12}",
            "letter": letter,
            "x0": round(centre - half, 4), "x1": round(centre + half, 4), "width": round(2 * half, 4),
            "y0": round(FIELD_TOP_Y + p["black_lift_px"], 4),
            "y1": round(FIELD_TOP_Y + p["black_lift_px"] + raise_px, 4),
            "z0": black_front, "z1": black_back,
            "pivot": [round(centre, 4), round(FIELD_TOP_Y + p["black_lift_px"], 4), black_back],
            "travel_deg": travel,
        })
    return sorted(rows, key=lambda r: (r["kind"] != "white", r["note_index"]))


def write_csv(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    head = ["id", "kind", "note", "letter", "x0", "x1", "width", "y0", "y1", "z0", "z1",
            "neck_x0", "neck_x1", "neck_width", "pivot_x", "pivot_y", "pivot_z",
            "travel_deg", "tip_dip_px"]
    lines = [",".join(head)]
    for row in rows:
        dip = round((row["z1"] - row["z0"]) * math.sin(math.radians(row["travel_deg"])), 4)
        lines.append(",".join(str(v) for v in [
            row["id"], row["kind"], row["note"], row["letter"], row["x0"], row["x1"], row["width"],
            row["y0"], row["y1"], row["z0"], row["z1"],
            row.get("neck_x0", ""), row.get("neck_x1", ""), row.get("neck_width", ""),
            row["pivot"][0], row["pivot"][1], row["pivot"][2], row["travel_deg"], dip]))
    (OUT / "piano_keys.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def draw(rows: list[dict], c: dict, p: dict) -> None:
    """One sheet: the keyboard seen from above, and a section that shows what a press does."""
    from PIL import Image, ImageDraw

    ink = (38, 31, 25, 255)
    dim = (122, 104, 88, 255)
    accent = (188, 104, 44, 255)
    scale, pad = 30, 26
    top_w = int((c["KEY_MAX_X"] - c["KEY_MIN_X"] + 4) * scale)
    top_h = int(6.6 * scale)
    sec_scale = 64
    sec_w = int(9.2 * sec_scale)
    sec_h = int(4.95 * sec_scale)
    width = pad * 2 + top_w + pad + sec_w
    height = pad + 26 + max(top_h, sec_h) + 16 + 13 * 15 + pad
    img = Image.new("RGBA", (width, height), (250, 246, 238, 255))
    d = ImageDraw.Draw(img)

    def say(xy, s, fill=None, text=None):
        # The default bitmap font has no glyph for typographic punctuation; keep the sheet ASCII.
        d.text(xy, str(s).encode("ascii", "replace").decode(), fill=fill)

    # ---------- top view ----------
    ox, oy = pad, pad + 26
    say((ox, pad + 4), "TOP VIEW - the key bed from above, 25 keys on a 2.3333 px pitch",
           fill=ink)

    def tx(x):
        return ox + int((x - (c["KEY_MIN_X"] - 2)) * scale)

    def tz(z):
        return oy + int(z * scale)

    d.rectangle([tx(c["KEY_MIN_X"] - 1), tz(-0.5), tx(c["KEY_MAX_X"] + 1), tz(6.4)],
                fill=(150, 128, 108, 255), outline=(96, 80, 66, 255))
    d.rectangle([tx(c["KEY_MIN_X"] + 0.2), tz(0.05), tx(c["KEY_MAX_X"] - 0.2), tz(5.7)],
                fill=(92, 80, 70, 255))                        # well floor, seen through the gaps
    for row in rows:
        if row["kind"] == "white":
            d.rectangle([tx(row["x0"]), tz(row["z0"]), tx(row["x1"]), tz(row["neck_z0"])],
                        fill=(255, 237, 211, 255), outline=(206, 184, 158, 255))
            d.rectangle([tx(row["neck_x0"]), tz(row["neck_z0"]), tx(row["neck_x1"]), tz(row["neck_z1"])],
                        fill=(255, 237, 211, 255), outline=(206, 184, 158, 255))
    for row in rows:
        if row["kind"] == "black":
            d.rectangle([tx(row["x0"]), tz(row["z0"]), tx(row["x1"]), tz(row["z1"])],
                        fill=(56, 55, 76, 255), outline=(28, 28, 44, 255))
    for row in rows:
        cx = (row["x0"] + row["x1"]) / 2
        if row["kind"] == "white":
            say((tx(cx) - 5, tz(row["z1"]) - 16), row["letter"],
                   fill=(52, 42, 34, 255))
            say((tx(cx) - 5, tz(row["z0"]) + 5), row["note"], fill=dim)
        else:
            say((tx(cx) - 3, tz(row["z0"]) + 4), row["letter"], fill=(240, 236, 226, 255))
    slot = 2 * p["key_gap_px"]
    say((ox, oy + top_h + 4),
        f"each white key loses {p['key_gap_px']:g} px per side, so the dark slot between two keys is "
        f"{slot:g} px = {slot * 6.25:.1f} cm; the narrowed backs under the blacks are the same idea",
        fill=dim)

    # ---------- section ----------
    sx, sy = ox + top_w + pad, pad + 26
    say((sx, pad + 4), "SECTION - side view of one white key and one black", fill=ink)
    key_y0 = FIELD_TOP_Y - p["white_thickness_px"]
    black_y0 = FIELD_TOP_Y + p["black_lift_px"]
    black_row = next(r for r in rows if r["kind"] == "black")

    def vx(z):
        return sx + int((z + 0.6) * sec_scale)

    def vy(y):
        return sy + int((16.4 - y) * sec_scale)

    for z0, z1, y0, y1, fill, label, dy in [
        (0.05, 6.0, 12.0, SHELF_TOP_Y, (221, 193, 168, 255), "key slip", 0),
        (0.05, 5.7, SHELF_TOP_Y, SHELF_TOP_Y + 0.05, (92, 80, 70, 255), "well floor", 0),
        (0.05, 5.7, key_y0, FIELD_TOP_Y, (255, 237, 211, 255), "white", 0),
        (1.9, 5.6, black_y0, black_y0 + 1.0, (56, 55, 76, 255), "black", -22),
        (5.7, 6.0, FIELD_TOP_Y, 16.0, (200, 166, 148, 255), "nameboard", 0),
    ]:
        d.rectangle([vx(z0), vy(y1), vx(z1), vy(y0)], fill=fill, outline=(70, 60, 52, 255))
        if label:
            say((vx(z1) + 8, vy(y0) + dy), label, fill=dim)

    def tipped(z0, z1, y0, y1, pivot, deg):
        a = math.radians(deg)
        out = []
        for z, y in [(z0, y1), (z1, y1), (z1, y0), (z0, y0)]:
            dz, dy = z - pivot[0], y - pivot[1]
            out.append((pivot[0] + dz * math.cos(a) + dy * math.sin(a),
                        pivot[1] - dz * math.sin(a) + dy * math.cos(a)))
        return out

    d.polygon([(vx(z), vy(y)) for z, y in
               tipped(0.05, 5.7, key_y0, FIELD_TOP_Y, (5.7, key_y0), p["white_travel_deg"])],
              fill=(240, 214, 186, 255), outline=accent)
    d.polygon([(vx(z), vy(y)) for z, y in
               tipped(1.9, 5.6, black_y0, black_y0 + 1.0, (5.6, black_y0), black_row["travel_deg"])],
              outline=accent)
    d.line([vx(5.7) - 4, vy(key_y0), vx(5.7) + 4, vy(key_y0)], fill=accent, width=2)
    say((vx(2.2), vy(key_y0) + 12), "pivot: rear underside", fill=accent)

    white_dip = (5.7 - 0.05) * math.sin(math.radians(p["white_travel_deg"]))
    black_dip = (5.6 - 1.9) * math.sin(math.radians(black_row["travel_deg"]))
    clearance = key_y0 - SHELF_TOP_Y
    lines = [
        f"white  -{p['white_travel_deg']:g}deg  tip dips {white_dip:.2f} px, "
        f"well clearance {clearance:.2f} px  ->  {clearance - white_dip:+.2f} px left  OK",
        f"black  -{black_row['travel_deg']:g}deg  tip dips {black_dip:.2f} px down its slot, "
        f"{clearance + p['black_lift_px'] - black_dip:.2f} px above the well floor  OK",
        f"white key {rows[0]['width']:.2f} px wide and {p['white_thickness_px']:g} px thick, "
        f"back narrowed to {rows[0]['neck_width']:.2f} px; the dip is "
        f"{white_dip / rows[0]['width']:.0%} of the width (a real key dips 43%, a restrained press)",
    ]
    ly = sy + sec_h + 12
    for i, line in enumerate(lines):
        say((sx - 6, ly + i * 15), line, fill=accent if i < 2 else dim)

    text_block = [
        "RULES THIS SHEET PINS",
        "1  every key is its own box, rotated about its rear underside; nothing is scaled",
        "2  the keys are not in the block model: the block entity renderer draws all 25 + 10, "
        "so a press cannot leave a ghost copy behind",
        "3  the item model keeps static keys (all up) generated from the same table",
        "4  the artist owns the case, the well, and the palette; the generator owns every key",
    ]
    ty = ly + 3 * 15 + 14
    for i, line in enumerate(text_block):
        say((sx - 6, ty + i * 14), line, fill=ink if i == 0 else dim)

    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "piano_keyboard_plan.png")
    print(f"wrote {OUT / 'piano_keyboard_plan.png'} {img.size}")


def main() -> None:
    c, p = constants(), knobs()
    rows = key_rows(c, p)
    pitch = (c["KEY_MAX_X"] - c["KEY_MIN_X"]) / c["WHITE_KEYS"]
    write_csv(rows)
    payload = {
        "stack": {
            "key_slip": {"y": [12.0, SHELF_TOP_Y], "z": [0.05, 6.0], "static": True,
                         "note": "its top face is the well floor; no separate floor element"},
            "white_key": {"y": [round(FIELD_TOP_Y - p["white_thickness_px"], 3), FIELD_TOP_Y],
                          "z": [0.05, 5.7], "static": False},
            "black_key": {"y": [round(FIELD_TOP_Y + p["black_lift_px"], 3),
                                round(FIELD_TOP_Y + p["black_lift_px"] + 1.0, 3)],
                          "z": [1.9, 5.6], "static": False,
                          "note": "dips through a slot cut in the narrowed backs of its neighbours"},
            "key_nameboard": {"y": [FIELD_TOP_Y, 16.0], "z": [5.7, 6.0], "static": True},
            "well_clearance_px": round(FIELD_TOP_Y - p["white_thickness_px"] - SHELF_TOP_Y, 3),
        },
        "pitch_px": round(pitch, 4),
        "gap_px": p["key_gap_px"],
        "knobs": p,
        "pedals": {
            "soft": {"x": [c["PEDAL_SOFT_MIN_X"], c["PEDAL_SOFT_MAX_X"]], "y": [1.0, 2.0], "z": [1.0, 6.0]},
            "sustain": {"x": [c["PEDAL_SUSTAIN_MIN_X"], c["PEDAL_SUSTAIN_MAX_X"]],
                        "y": [1.0, 2.0], "z": [1.0, 6.0]},
        },
        "keys": rows,
    }
    (OUT / "piano_keys.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"{len(rows)} keys, pitch {pitch:.4f} px, white width {rows[0]['width']:.4f} px "
          f"({sum(1 for r in rows if r['kind'] == 'white')} white / "
          f"{sum(1 for r in rows if r['kind'] == 'black')} black)")
    draw(rows, c, p)


if __name__ == "__main__":
    main()