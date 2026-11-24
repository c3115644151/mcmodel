
"""Bake the cask-liquid flow sheet: 32 frames of a seamless two-layer drift.

Vanilla water_still is not an animated shader, it is a 32-frame sheet of a soft, drifting
pattern. Doing the same here keeps the eye away from anything a sine can produce: there is
no lattice, no hatch, and the loop closes exactly because both layers travel a closed path
(sin/cos) instead of scrolling.

Two sheets are written: one that lightens the drink and one that darkens it, because a GUI
blit cannot tint and the drink colour has to come from the fill underneath.
"""

from pathlib import Path
import math

from PIL import Image, ImageDraw

W, H = 28, 24
FRAMES = 32

OUT = Path(r"C:/Users/32800/Desktop/家具mod/src/main/resources/assets/pastoral_home/textures/gui")


def lattice(ix, iy):
    h = (ix * 0x27D4EB2D) ^ (iy * 0x9E3779B1)
    h &= 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    return (h & 0xFFFF) / 65535.0


def value_noise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi
    u = fx * fx * (3 - 2 * fx)
    v = fy * fy * (3 - 2 * fy)
    c00 = lattice(xi, yi)
    c10 = lattice(xi + 1, yi)
    c01 = lattice(xi, yi + 1)
    c11 = lattice(xi + 1, yi + 1)
    x0 = c00 + (c10 - c00) * u
    x1 = c01 + (c11 - c01) * u
    return x0 + (x1 - x0) * v


def fbm(x, y):
    # Low frequencies only. A 28x24 pane is drawn one texture pixel per GUI pixel, so any octave
    # finely enough to matter here lands as speckle - the eye reads it as mould, not water. What
    # sells a liquid at this size is a few broad bands of light drifting, not detail.
    return (0.72 * value_noise(x * 0.26, y * 0.26)
            + 0.28 * value_noise(x * 0.61 + 5.3, y * 0.61 + 2.7))


def frame_field(i):
    t = i / FRAMES
    ang = 2 * math.pi * t
    sx, cx = math.sin(ang), math.cos(ang)
    # Both layers travel a closed loop, so frame 31 lands exactly on frame 0: no seam to hide.
    ax = sx * 6.0
    ay = (1 - cx) * 4.0
    bx = -sx * 4.4 + 3.0
    by = (1 - cx) * 2.9 + 1.7
    w = 0.5 - 0.5 * cx
    return [[fbm(x + ax, y + ay) * (1 - w) + fbm(x + bx, y + by) * w
             for x in range(W)] for y in range(H)]


def bake(name, ink, peak):
    sheet = Image.new("RGBA", (W, H * FRAMES), (0, 0, 0, 0))
    px = sheet.load()
    for i in range(FRAMES):
        f = frame_field(i)
        for y in range(H):
            for x in range(W):
                v = f[y][x] - 0.5
                amount = (v if ink == "light" else -v) * 2.0
                a = int(round(max(0.0, min(1.0, amount)) * peak))
                if a:
                    px[x, i * H + y] = (255 if ink == "light" else 0,
                                        255 if ink == "light" else 0,
                                        255 if ink == "light" else 0, a)
    path = OUT / name
    sheet.save(path)
    print("wrote", name, sheet.size)


# Peak ink stays low: the drift has to be felt as the drink breathing, not seen as a pattern on it.
bake("brewing_liquid_flow_light.png", "light", 26)
bake("brewing_liquid_flow_shade.png", "shade", 26)
