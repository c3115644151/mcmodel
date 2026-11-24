#!/usr/bin/env python3
"""Author the brewing GUI pixel art: cask window, glass sheen, slot rims and role glyphs. Flow arrows are drawn in code, not blitted.

Every sprite is drawn from an explicit pixel plan so the set shares one palette and one
light direction (top-left key light). The cask exterior stays artist-authored; only the
iron seat and the glass pane are repainted here, and both repaints are idempotent.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "src/main/resources/assets/pastoral_home/textures/gui"
ART = ROOT / "artwork/brewing-ui/blockbench"
CASK_SOURCE = ART / "cask_source_64x80.png"
CASK = GUI / "brewing_barrel_front.png"

# Palette shared with brewing_workbench.png (sampled from the backdrop planks).
RECESS = (0x1C, 0x10, 0x08, 0xFF)
RECESS_SHADOW = (0x12, 0x0A, 0x05, 0xFF)
RECESS_LIP = (0x3B, 0x23, 0x12, 0xFF)
BRASS_HI = (0xC8, 0x96, 0x5B, 0xFF)
BRASS_MID = (0x9A, 0x6A, 0x38, 0xFF)
BRASS_LO = (0x5E, 0x3E, 0x20, 0xFF)
IRON_SEAT = (0x2E, 0x30, 0x2C, 0xFF)
BONE = (0xE9, 0xDF, 0xC6, 0xFF)
BONE_SHADOW = (0x6B, 0x54, 0x39, 0xFF)

# Cask sprite geometry. The liquid pane is the rectangle the GUI and JEI draw into.
CASK_SIZE = (64, 80)
PANE = (18, 29, 45, 52)            # inclusive bounds of the liquid pane (28x24, centred in the ring)
STONE_INNER = (9, 17, 55, 61)      # inclusive bounds of the stone ring's inner face

# The opening reads as a pane of glass set into the cask, not a hole cut straight through the
# staves, only while it keeps its cast-metal frame: one pixel of shadow inside, a lit bevel above
# and left, a shaded bevel below and right. Those rings are what separate drink from stave.
# Bevel tones stay inside the stone ring's own family (it sits around 0x7F7F75): the frame is read
# by the step between the four bands, not by contrast against the ring. Anything brighter turns
# the window into a white strip taped onto the barrel.
FRAME_SEAM = (0x24, 0x26, 0x23, 0xFF)
FRAME_LIT_OUTER = (0x86, 0x83, 0x7A, 0xFF)
FRAME_LIT_INNER = (0x5E, 0x5A, 0x4C, 0xFF)
FRAME_DARK_INNER = (0x62, 0x5F, 0x55, 0xFF)
FRAME_DARK_OUTER = (0x48, 0x45, 0x3C, 0xFF)
# The window is a two-pixel bronze ring sunk into the staves. An earlier plan kept a 38x35 stepped
# bezel; at 4x GUI scale that band dominated the whole barrel and read as a framed picture rather
# than a barrel with a window in it, so the frame is now thin and the stave wood flows around it.
FACE = (13, 23, 50, 57)            # repainted face area, filled with stave wood first
STAVE = (0x33, 0x1E, 0x0E, 0xFF)
STAVE_SEAM = (0x1A, 0x10, 0x06, 0xFF)
RING = (16, 27, 47, 54)            # inclusive bounds of the bronze ring
BRONZE_HI = (0xC9, 0xA0, 0x55, 0xFF)
BRONZE_MID = (0x8A, 0x6A, 0x3C, 0xFF)
BRONZE_LO = (0x42, 0x2E, 0x1A, 0xFF)

# The authored cask shell is a cold grey stone frame (0x7F7F76) eight pixels deep on every side.
# Next to the orange plank backdrop it read as a picture frame, so the neutral greys are mapped onto
# one warm bronze ramp by luminance; chroma is ignored, so shading direction and detail survive.
STONE_STOPS = (
    (0x00, (0x1E, 0x10, 0x07)),
    (0x40, (0x33, 0x1C, 0x0D)),
    (0x80, (0x4F, 0x2C, 0x14)),
    (0xC0, (0x6B, 0x3B, 0x1A)),
    (0xFF, (0x8A, 0x4F, 0x24)),
)
# The authored sprite also carries a broken cold-grey highlight line across the waist (xy 10..54
# at y=12, chroma 15..18). At 14 those pixels slipped past the remap and stayed pale grey on
# walnut, which reads as white noise at GUI scale 4. 20 catches them while real stave grain
# (chroma 26..48) keeps its colour.
STONE_MAX_CHROMA = 20
# Dark seams are left alone even when they are neutral: remapping them brightens the wood.
STONE_MIN_LEVEL = 0x30
# The cask body sits on a plank backdrop of almost the same walnut, so the dark staves are lifted
# a little; the bronze ring, the rivets and the lit highlights stay where the pixel plan put them.
STAVE_LIFT = 1.14
STAVE_LIFT_CEILING = 0x8A


def px(image: Image.Image, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if 0 <= x < image.width and 0 <= y < image.height:
        image.putpixel((x, y), color)


def box(image: Image.Image, bounds: tuple[int, int, int, int], color: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = bounds
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            px(image, x, y, color)


def hline(image: Image.Image, x0: int, x1: int, y: int, color: tuple[int, int, int, int]) -> None:
    for x in range(x0, x1 + 1):
        px(image, x, y, color)


def vline(image: Image.Image, x: int, y0: int, y1: int, color: tuple[int, int, int, int]) -> None:
    for y in range(y0, y1 + 1):
        px(image, x, y, color)


def blit_map(image: Image.Image, plan: list[str], origin: tuple[int, int],
             colors: dict[str, tuple[int, int, int, int]]) -> None:
    ox, oy = origin
    for row, line in enumerate(plan):
        for column, symbol in enumerate(line):
            color = colors.get(symbol)
            if color is not None:
                px(image, ox + column, oy + row, color)


# --- cask window -------------------------------------------------------------------------

def warm_stone_frame(image: Image.Image) -> int:
    """Map the neutral grey shell onto the bronze ramp; returns the number of pixels changed."""
    changed = 0
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha < 40 or max(red, green, blue) - min(red, green, blue) > STONE_MAX_CHROMA:
                continue
            level = (red + green + blue) / 3.0
            if level < STONE_MIN_LEVEL:
                continue
            warm = STONE_STOPS[-1][1]
            for index in range(len(STONE_STOPS) - 1):
                low, low_color = STONE_STOPS[index]
                high, high_color = STONE_STOPS[index + 1]
                if low <= level <= high:
                    ratio = (level - low) / (high - low)
                    warm = tuple(
                        int(low_color[channel] + (high_color[channel] - low_color[channel]) * ratio)
                        for channel in range(3)
                    )
                    break
            image.putpixel((x, y), (*warm, alpha))
            changed += 1
    return changed


def rivet_ring(image: Image.Image) -> None:
    """Four rivets at the ring corners so the band reads as fitted metal, not painted trim."""
    left, top, right, bottom = RING
    for x, y in ((left + 1, top + 1), (right - 1, top + 1), (left + 1, bottom - 1), (right - 1, bottom - 1)):
        px(image, x, y, (0xC6, 0xA5, 0x74, 0xFF))
        px(image, x, y + 1, (0x4A, 0x33, 0x1C, 0xFF))


SHELL_SEAM = (0x1B, 0x0F, 0x07, 0xFF)
SHELL_SHADOW = (0x0C, 0x06, 0x03, 0x70)



def lift_staves(image: Image.Image) -> None:
    """Brightens the dark wood just enough to separate the body from the matching backdrop.

    Values above STAVE_LIFT_CEILING are left alone: the bronze ring and the rivets are already the
    brightest thing in the sprite and lifting them too would flatten the ring into the staves.
    """
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha < 40 or max(red, green, blue) > STAVE_LIFT_CEILING:
                continue
            image.putpixel(
                (x, y),
                (
                    min(255, round(red * STAVE_LIFT)),
                    min(255, round(green * STAVE_LIFT)),
                    min(255, round(blue * STAVE_LIFT)),
                    alpha,
                ),
            )

def outline_shell(image: Image.Image) -> int:
    """One dark pixel around the silhouette plus a short drop shadow under it.

    The GUI backdrop is the same walnut plank as the cask, so the body dissolved into the panel;
    the seam and the shadow are what make the barrel read as an object standing on the board
    rather than a patch of painted wood. Pixels inside the window are skipped so the seam never
    eats into the pane or the bronze ring.
    """
    width, height = image.size
    source = image.copy()
    opaque = lambda point: source.getpixel(point)[3] > 40
    seam = 0
    for y in range(height):
        for x in range(width):
            if opaque((x, y)):
                continue
            if PANE[0] - 1 <= x <= PANE[2] + 1 and PANE[1] - 1 <= y <= PANE[3] + 1:
                continue
            touching = any(
                opaque((nx, ny))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                if 0 <= nx < width and 0 <= ny < height
            )
            if touching:
                image.putpixel((x, y), SHELL_SEAM)
                seam += 1

    # Three rows of shadow under the body, fading, so the cask sits above the plank instead of
    # being pasted onto it. Only the lowest rows are touched: a full silhouette offset would
    # darken the whole panel.
    floor = max(y for y in range(height) for x in range(width) if opaque((x, y)))
    for depth, alpha in ((1, 0x70), (2, 0x45), (3, 0x22)):
        y = floor + depth
        if y >= height:
            break
        for x in range(1, width - 1):
            if opaque((x, y)):
                continue
            if any(opaque((x + dx, y - 1)) for dx in (-1, 0, 1)):
                image.putpixel((x, y), (0x0C, 0x06, 0x03, alpha))
    return seam

def frame_cask_window(image: Image.Image) -> None:
    left, top, right, bottom = PANE
    # One pixel of seam, then two rings that do opposite jobs. The outer ring is convex (lit above
    # and left, dark below and right) — that is the frame standing proud of the staves. The inner
    # ring is concave, with the polarity reversed: the glass sits in a recess, so its upper and left
    # inner faces fall into shadow and its lower and right faces catch the light. A bevel that is
    # convex all the way in reads as a plate with a picture stuck on the front, which is exactly the
    # "the liquid looks outside the cask" note this answers.
    hline(image, left - 1, right + 1, top - 1, FRAME_SEAM)
    hline(image, left - 1, right + 1, bottom + 1, FRAME_SEAM)
    vline(image, left - 1, top - 1, bottom + 1, FRAME_SEAM)
    vline(image, right + 1, top - 1, bottom + 1, FRAME_SEAM)
    for band, top_color, left_color, bottom_color, right_color in (
            (2, FRAME_LIT_OUTER, FRAME_LIT_OUTER, FRAME_DARK_OUTER, FRAME_DARK_OUTER),
            (1, FRAME_DARK_INNER, FRAME_DARK_INNER, FRAME_LIT_INNER, FRAME_LIT_INNER)):
        inset = band
        hline(image, left - inset, right + inset, top - inset, top_color)
        hline(image, left - inset, right + inset, bottom + inset, bottom_color)
        vline(image, left - inset, top - inset, bottom + inset, left_color)
        vline(image, right + inset, top - inset, bottom + inset, right_color)


def repaint_cask_window() -> None:
    # The window is exactly the pane rect the GUI paints into, cut straight out of the authored
    # sprite. Nothing is filled around it: a seam, bezel or lip drawn between the pane and the
    # staves shows up as a dark band between the drink and the barrel, so the staves meet the glass
    # directly and the liquid is the only thing inside the opening.
    image = Image.open(CASK_SOURCE).convert("RGBA")
    if image.size != CASK_SIZE:
        raise ValueError(f"expected the authored 64x80 cask sprite, found {image.size}")

    left, top, right, bottom = PANE
    box(image, PANE, (0, 0, 0, 0))
    frame_cask_window(image)
    image.save(CASK)

    check = Image.open(CASK).convert("RGBA")
    if check.size != CASK_SIZE:
        raise ValueError("cask sprite changed size while repainting the window")
    if check.getpixel(((left + right) // 2, (top + bottom) // 2))[3] != 0:
        raise ValueError("the pane centre must stay fully transparent for the liquid layer")
    if check.getpixel((left - 1, top - 1))[3] == 0:
        raise ValueError("the frame must stay opaque around the pane")
    print(f"Cut the cask opening at {right - left + 1}x{bottom - top + 1} transparent; "
          f"authored shell, stave grain and footing untouched.")



def write_glass_sheen() -> None:
    width = PANE[2] - PANE[0] + 1
    height = PANE[3] - PANE[1] + 1
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # The pane is a sheet of glass in front of the drink, not a hole with a border: a cold cast
    # over the whole opening is what puts a surface between the eye and the liquid. Without it the
    # window reads as an opening in the staves and the liquid looks painted on the barrel wall.
    # Seven percent: enough that a full cask looks seen-through and not like a flat swatch, faint
    # enough that it never washes the drink colour out.
    # Four percent of warm neutral, not seven of cold blue: the cast is there to sit a sheet between
    # the eye and the drink, and anything stronger desaturates the batch towards the grey of the
    # stone band around it.
    cast = Image.new("RGBA", (width, height), (0xE0, 0xE6, 0xE4, 0x0A))
    image = Image.alpha_composite(image, cast)

    # Thickness: a lit top edge and a shadowed bottom edge, plus the two jambs. A full-height lit
    # Thickness is a lit lip at the top and nothing else. A shadowed foot and a shadowed right
    # jamb each draw one dark line straight through the drink, and three lines on three sides of
    # the opening is a border: the eye reads the drink as a plate set inside a frame instead of
    # a body of liquid sitting behind a sheet of glass, so both were dropped.
    hline(image, 0, width - 1, 0, (0xFF, 0xF2, 0xD8, 0x2A))
    hline(image, 0, width - 1, 1, (0xFF, 0xF2, 0xD8, 0x0E))
    vline(image, 0, 1, height - 1, (0xFF, 0xF2, 0xD8, 0x0C))

    # One raking reflection that crosses most of the pane: a short streak near the top corner
    # reads as a scratch on the wood, while a band running to the lower half keeps saying "glass"
    # even when a full cask of drink sits behind it. Two pixels wide so the fade survives the
    # downsample, fading as it travels so it never competes with the liquid.
    # No diagonal specular. Against a cask holding one flat colour there is no reflection to
    # catch, so any drawn streak reads as a scratch down the drink rather than as light on glass.
    # The pane is carried by its edges alone: the lit head and shadowed foot above, the shadowed
    # right jamb below, plus the cold thickness lines the renderer lays over the liquid.
    image.save(GUI / "brewing_barrel_glass.png")
    print(f"Wrote glass sheet {width}x{height} (cold cast over the whole opening + edge banding).")


# --- slots -------------------------------------------------------------------------------

SLOT_SIZE = 18


def slot_tile(rim_hi, rim_lo, interior, lid) -> Image.Image:
    image = Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (0, 0, 0, 0))
    box(image, (0, 0, SLOT_SIZE - 1, SLOT_SIZE - 1), RECESS)
    hline(image, 0, SLOT_SIZE - 1, 0, rim_hi)
    vline(image, 0, 0, SLOT_SIZE - 1, rim_hi)
    hline(image, 0, SLOT_SIZE - 1, SLOT_SIZE - 1, rim_lo)
    vline(image, SLOT_SIZE - 1, 0, SLOT_SIZE - 1, rim_lo)
    px(image, SLOT_SIZE - 1, 0, rim_lo)
    px(image, 0, SLOT_SIZE - 1, rim_lo)
    box(image, (1, 1, SLOT_SIZE - 2, SLOT_SIZE - 2), interior)
    hline(image, 1, SLOT_SIZE - 2, 1, RECESS_SHADOW)
    vline(image, 1, 1, SLOT_SIZE - 2, RECESS_SHADOW)
    hline(image, 1, SLOT_SIZE - 2, SLOT_SIZE - 2, lid)
    vline(image, SLOT_SIZE - 2, 1, SLOT_SIZE - 2, lid)
    return image


def write_slots() -> None:
    # Interiors stay dark wood rather than pure void: at 4x GUI scale a near-black well under a
    # gold rim read as four holes punched in the panel.
    storage = slot_tile((0x5C, 0x42, 0x26, 0xFF), (0x24, 0x15, 0x09, 0xFF),
                        (0x23, 0x15, 0x09, 0xFF), (0x33, 0x20, 0x10, 0xFF))
    storage.save(GUI / "brewing_slot_frame.png")
    # Functional cells stay a shade brighter than the 36 storage cells, but well below the old
    # cream rim: four of them sit edge to edge, so a bright rim merged them into one window pane.
    active = slot_tile((0x9A, 0x6C, 0x3C, 0xFF), (0x40, 0x2A, 0x17, 0xFF),
                       (0x2C, 0x1B, 0x0D, 0xFF), (0x45, 0x2B, 0x16, 0xFF))
    active.save(GUI / "brewing_slot_empty.png")
    print("Wrote 18x18 slot rims: storage (quiet brass) and functional (bright brass bevel).")


# --- role glyphs -------------------------------------------------------------------------

# Only the vessel slot carries a glyph: it sits where a cup belongs and says "put one here".
# Water, ingredient and output hints were tried and removed — three more marks in a 224px panel
# turned the grid into signage, and the flow arrows already name those directions.
GLYPHS = {
    # Open mouth, tapering bowl, stem, foot. The first version closed the rim with a full-width
    # row on top, which turned the cup into a funnel: a lid over a shape that narrows downward
    # reads as something you pour through, not something you drink from.
    "brewing_hint_vessel": [
        "........",
        ".X....X.",
        ".X....X.",
        "..X..X..",
        "..XXXX..",
        "...XX...",
        "..XXXX..",
        "........",
    ],
}
STALE_GLYPHS = ("brewing_hint_water", "brewing_hint_ingredient", "brewing_hint_output")


def write_glyphs() -> None:
    for name, plan in GLYPHS.items():
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        blit_map(image, plan, (0, 0), {"X": (0xB8, 0x8A, 0x52, 0xF0)})
        image.save(GUI / f"{name}.png")
    for name in STALE_GLYPHS:
        stale = GUI / f"{name}.png"
        if stale.exists():
            stale.unlink()
    print(f"Wrote {len(GLYPHS)} role glyph 8x8 in a single dim brass tone; "
          f"removed {len(STALE_GLYPHS)} retired hint sprites.")


# --- adapted borrowed sprites ------------------------------------------------------------

def recolour_borrowed() -> None:
    timer_source = ART / "reference" / "fd_timer_gray_16x16.png"
    timer = Image.open(timer_source).convert("RGBA")
    if timer.size != (16, 16):
        raise ValueError(f"expected a 16x16 timer glyph, found {timer.size}")
    for y in range(16):
        for x in range(16):
            red, green, blue, alpha = timer.getpixel((x, y))
            if alpha == 0:
                continue
            if red > 0xC8:
                timer.putpixel((x, y), BONE)
            elif red > 0x90:
                timer.putpixel((x, y), (0xC2, 0xB4, 0x95, alpha))
            else:
                timer.putpixel((x, y), BONE_SHADOW)
    timer.save(GUI / "brewing_time_icon.png")
    print("Recoloured the borrowed timer glyph to bone.")


def main() -> None:
    GUI.mkdir(parents=True, exist_ok=True)
    repaint_cask_window()
    write_glass_sheen()
    write_slots()
    write_glyphs()
    recolour_borrowed()
    print("Brewing GUI art is in sync with the pixel plan.")


if __name__ == "__main__":
    main()
