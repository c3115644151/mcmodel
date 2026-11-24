"""Render a shipped block model offline so key geometry can be tuned before a client restart.

The game is the only ground truth, but a full restart costs minutes and a resource reload still
needs a running client. This script draws the same model json with the same uv mapping the client
bakes, so geometry can be iterated in about a second and the client is only touched once the shape
is right.

Camera: orthographic, viewer on the -Z side looking toward +Z, which is how a player standing in
front of a south-facing piece sees it.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
MODELS = ASSETS / "models/block"
TEXTURES = ASSETS / "textures"

FACE_VERTICES = {
    "north": ((1, 1, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0)),
    "south": ((0, 1, 1), (0, 0, 1), (1, 0, 1), (1, 1, 1)),
    "east": ((1, 1, 1), (1, 0, 1), (1, 0, 0), (1, 1, 0)),
    "west": ((0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)),
    "up": ((1, 1, 1), (1, 1, 0), (0, 1, 0), (0, 1, 1)),
    "down": ((0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 0, 1)),
}
FACE_ORDER = ("north", "south", "east", "west", "up", "down")

# Which element axes run right and down on each face as seen from outside, matching the uv box
# authoring convention the client uses.
FACE_SCREEN = {
    "north": (lambda o, z: 1 - o[0], lambda o, z: 1 - o[1]),
    "south": (lambda o, z: o[0], lambda o, z: 1 - o[1]),
    "east": (lambda o, z: 1 - o[2], lambda o, z: 1 - o[1]),
    "west": (lambda o, z: o[2], lambda o, z: 1 - o[1]),
    "up": (lambda o, z: o[0], lambda o, z: 1 - o[2]),
    "down": (lambda o, z: o[0], lambda o, z: o[2]),
}
# Vanilla's directional shading, which is most of what makes a flat model read as a box.
FACE_SHADE = {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8, "east": 0.6, "west": 0.6}

UV_SCALE = 16.0  # block model uv space is 0..16 whatever the texture resolution


def rotate(point, rotation: dict):
    origin = rotation.get("origin", (8.0, 8.0, 8.0))
    axis = rotation["axis"]
    angle = math.radians(rotation["angle"])
    index = "xyz".index(axis)
    local = [point[i] - origin[i] for i in range(3)]
    c, s = math.cos(angle), math.sin(angle)
    a, b = [i for i in range(3) if i != index]
    ra = c * local[a] - s * local[b]
    rb = s * local[a] + c * local[b]
    local[a], local[b] = ra, rb
    return tuple(local[i] + origin[i] for i in range(3))


def face_points(element: dict, face: str):
    low, high = element["from"], element["to"]
    points = []
    for xbit, ybit, zbit in FACE_VERTICES[face]:
        point = (high[0] if xbit else low[0], high[1] if ybit else low[1], high[2] if zbit else low[2])
        if element.get("rotation"):
            point = rotate(point, element["rotation"])
        points.append(point)
    return points


def face_uvs(element: dict, face: str):
    uv = element["faces"][face].get("uv")
    if uv is None:
        return None
    u1, v1, u2, v2 = (float(value) for value in uv)
    if abs(u2 - u1) < 1e-6 or abs(v2 - v1) < 1e-6:
        return None
    right, down = FACE_SCREEN[face]
    out = []
    for bits in FACE_VERTICES[face]:
        s, t = right(bits, None), down(bits, None)
        out.append(((u1 + s * (u2 - u1)) / UV_SCALE, (v1 + t * (v2 - v1)) / UV_SCALE))
    return out


def texture_ref(model: dict, name: str) -> str:
    textures = model.get("textures", {})
    seen = set()
    while name.startswith("#") and name[1:] in textures and name[1:] not in seen:
        seen.add(name[1:])
        name = textures[name[1:]]
    if name.startswith("#"):
        return "pastoral_home:block/piano"
    return name


def load_texture(ref: str) -> Image.Image:
    path = TEXTURES / (ref.split(":", 1)[1] + ".png")
    return Image.open(path).convert("RGBA")


def load_model(name: str) -> dict:
    path = MODELS / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"missing model {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def face_coverage(alpha, uvs) -> float:
    """How much of a face is actually painted: a fully transparent face hides nothing in game.

    Clay passes used to draw those faces anyway, so a key bed seen through the artist's open front
    looked like a closed lid. Coverage lets the preview drop what the game would drop.
    """
    height, width = alpha.shape[:2]
    us = [uv[0] for uv in uvs]
    vs = [uv[1] for uv in uvs]
    x0 = max(0, min(width - 1, int(min(us) * width)))
    x1 = max(x0 + 1, min(width, int(math.ceil(max(us) * width))))
    y0 = max(0, min(height - 1, int(min(vs) * height)))
    y1 = max(y0 + 1, min(height, int(math.ceil(max(vs) * height))))
    region = alpha[y0:y1, x0:x1]
    return float((region >= 0.5).mean()) if region.size else 0.0


def collect_model(model: dict, shift, offset_scale: float, texture_cache=None):
    quads = []
    texture_cache = {} if texture_cache is None else texture_cache
    for index, element in enumerate(model["elements"]):
        for face in FACE_ORDER:
            if face not in element["faces"]:
                continue
            uvs = face_uvs(element, face)
            if uvs is None:
                continue
            ref = texture_ref(model, element["faces"][face].get("texture", "#missing"))
            if ref not in texture_cache:
                image = load_texture(ref)
                texture_cache[ref] = image
                texture_cache[(ref, "alpha")] = np.asarray(image, dtype=np.float64)[..., 3] / 255.0
            points = [((p[0] + shift[0]) * offset_scale, (p[1] + shift[1]) * offset_scale,
                       p[2] * offset_scale)
                      for p in face_points(element, face)]
            quads.append({
                "points": points,
                "uvs": uvs,
                "texture": texture_cache[ref],
                "coverage": face_coverage(texture_cache[(ref, "alpha")], uvs),
                "shade": FACE_SHADE[face],
                "face": face,
                "element": index,
                "name": element.get("name", ""),
            })
    return quads


def collect(cells, offset_scale: float):
    quads = []
    texture_cache = {}
    for name, shift in cells:
        quads.extend(collect_model(load_model(name), shift, offset_scale, texture_cache))
    return quads


def project(point, yaw: float, pitch: float):
    x, y, z = point
    ca, sa = math.cos(yaw), math.sin(yaw)
    x1 = x * ca + z * sa
    z1 = -x * sa + z * ca
    cp, sp = math.cos(pitch), math.sin(pitch)
    y1 = y * cp - z1 * sp
    z2 = y * sp + z1 * cp
    return x1, -y1, z2


def fit_scale(quads, yaw_deg: float, pitch_deg: float, width: int, height: int,
              margin: float = 0.96) -> float:
    """Pixels per model unit that make every quad fit the frame in this view."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    xs, ys = [], []
    for quad in quads:
        for point in quad["points"]:
            x, y, _ = project(point, yaw, pitch)
            xs.append(x)
            ys.append(y)
    dx = max(max(xs) - min(xs), 1e-6)
    dy = max(max(ys) - min(ys), 1e-6)
    return min(width * margin / dx, height * margin / dy)


def render(quads, out: Path, scale: float, yaw_deg: float, pitch_deg: float,
           width: int, height: int, background=(0, 0, 0, 0), pan=(0.0, 0.0), clay=None,
           focus=None, tints=None):
    # Draws every quad, but centres the frame on `focus` (default: all quads).
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    projected = []
    for quad in quads:
        screen = [project(point, yaw, pitch) for point in quad["points"]]
        projected.append((quad, screen))

    # Centre the drawing on the projected bounds of the focus set.
    framed = projected if focus is None else [
        (quad, [project(point, yaw, pitch) for point in quad["points"]]) for quad in focus]
    xs = [p[0] for _, screen in framed for p in screen]
    ys = [p[1] for _, screen in framed for p in screen]
    # pan is in projected model units, positive = right / up in the drawing.
    cx = (min(xs) + max(xs)) * 0.5 + pan[0]
    cy = (min(ys) + max(ys)) * 0.5 + pan[1]

    buffer = np.zeros((height, width, 4), dtype=np.float64)
    buffer[..., 0] = background[0] / 255.0
    buffer[..., 1] = background[1] / 255.0
    buffer[..., 2] = background[2] / 255.0
    buffer[..., 3] = background[3] / 255.0
    depth = np.full((height, width), np.inf)

    def to_pixels(screen):
        return [(width * 0.5 + (p[0] - cx) * scale, height * 0.5 + (p[1] - cy) * scale, p[2])
                for p in screen]

    floor = 0.2 if clay is not None else 0.02
    dropped = 0
    for quad, screen in projected:
        if quad.get("coverage", 1.0) < floor:
            dropped += 1
            continue
        pixels = to_pixels(screen)
        texture = np.asarray(quad["texture"], dtype=np.float64)
        tex_h, tex_w = texture.shape[:2]
        for tri in ((0, 1, 2), (0, 2, 3)):
            (ax, ay, az), (bx, by, bz), (cx2, cy2, cz) = [pixels[i] for i in tri]
            (ua, va), (ub, vb), (uc, vc) = [quad["uvs"][i] for i in tri]
            area = (bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)
            if abs(area) < 1e-9:
                continue
            x0 = max(int(math.floor(min(ax, bx, cx2))), 0)
            x1 = min(int(math.ceil(max(ax, bx, cx2))), width - 1)
            y0 = max(int(math.floor(min(ay, by, cy2))), 0)
            y1 = min(int(math.ceil(max(ay, by, cy2))), height - 1)
            if x1 < x0 or y1 < y0:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((bx - px) * (cy2 - py) - (by - py) * (cx2 - px)) / area
            w1 = ((cx2 - px) * (ay - py) - (cy2 - py) * (ax - px)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            interpolated_u = w0 * ua + w1 * ub + w2 * uc
            interpolated_v = w0 * va + w1 * vb + w2 * vc
            interpolated_z = w0 * az + w1 * bz + w2 * cz
            sub_depth = depth[y0:y1 + 1, x0:x1 + 1]
            closer = inside & (interpolated_z < sub_depth - 1e-6)
            if not closer.any():
                continue
            sub = buffer[y0:y1 + 1, x0:x1 + 1]
            shade = quad["shade"]
            if clay is None:
                tu = np.clip((interpolated_u * tex_w).astype(int) % tex_w, 0, tex_w - 1)
                tv = np.clip((interpolated_v * tex_h).astype(int) % tex_h, 0, tex_h - 1)
                texel = texture[tv, tu]
                paint = closer & (texel[..., 3] >= 0.5)
                rgb = texel[..., :3] / 255.0 * shade
            else:
                # Clay pass: geometry only. Neighbouring elements get a 6% tint difference so two
                # coplanar faces that share a shade still read as separate boxes; vanilla's
                # directional shade stays for the big form.
                paint = closer
                rgb = np.empty(sub.shape[:2] + (3,), dtype=np.float64)
                body = clay
                if tints:
                    body = tints.get((quad.get("name", ""), quad.get("element", 0)),
                                     tints.get(quad.get("name", ""), clay))
                tint = 1.0 + ((quad.get("element", 0) * 37) % 7 - 3) * 0.02
                rgb[...] = np.array(body, dtype=np.float64) * shade * tint
            if not paint.any():
                continue
            sub[paint, 0] = rgb[paint, 0]
            sub[paint, 1] = rgb[paint, 1]
            sub[paint, 2] = rgb[paint, 2]
            sub[paint, 3] = 1.0
            sub_depth[paint] = interpolated_z[paint]

    finite = np.isfinite(depth)
    edge = np.zeros_like(finite)
    for dy, dx in ((0, 1), (1, 0)):
        a = depth[: depth.shape[0] - dy or None, : depth.shape[1] - dx or None]
        b = depth[dy:, dx:]
        jump = np.zeros_like(finite)
        pair = np.isfinite(a) & np.isfinite(b)
        jump[: a.shape[0], : a.shape[1]] = pair & (np.abs(a - b) > 0.35)
        edge |= jump
    buffer[edge, :3] *= 0.55
    image = Image.fromarray((np.clip(buffer, 0, 1) * 255).astype(np.uint8), "RGBA")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print(f"wrote {out.relative_to(ROOT)}"
          + (f" (dropped {dropped} see-through faces)" if dropped else ""))
    return image


def parse_cells(spec: str):
    """name:dx,dy -- the shift is in model pixels, so a second storey is name:0,16."""
    cells = []
    for part in spec.split(";"):
        name, _, shift = part.partition(":")
        values = [float(value) for value in shift.split(",")] if shift else []
        dx = values[0] if values else 0.0
        dy = values[1] if len(values) > 1 else 0.0
        cells.append((name, (dx, dy)))
    return cells


CLAY = (0.86, 0.85, 0.82)
# Model space is the facing=north variant, so the playable side of a piece sits at low z and yaw 0
# (camera on -Z) is the front view a player standing at the block's north side gets.
VIEWS = {"front": (0.0, 0.0), "quarter": (35.0, 18.0), "iso": (45.0, 30.0), "top": (0.0, 70.0)}


def contact_sheet(quads, out: Path, view_names, scale, width: int, height: int,
                  background=(0, 0, 0, 0), clay=None, pan=(0.0, 0.0), focus=None):
    """Renders each named view and tiles them side by side in one image.

    scale None means auto-fit: one scale shared by every tile, taken from the tightest view, so
    the tiles stay comparable in size while nothing is clipped.
    """
    from PIL import ImageDraw

    framed = quads if focus is None else focus
    if scale is None:
        scale = min(fit_scale(framed, *VIEWS[name], width, height) for name in view_names)
    tiles = []
    for name in view_names:
        if name not in VIEWS:
            raise SystemExit(f"unknown view {name}; pick from {sorted(VIEWS)}")
        yaw, pitch = VIEWS[name]
        tile_path = out.parent / f".tile_{name}.png"
        tiles.append((name, render(quads, tile_path, scale, yaw, pitch, width, height,
                                   background=background, pan=pan, clay=clay, focus=framed)))
    sheet = Image.new("RGBA", (width * len(tiles), height), background)
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(tiles):
        sheet.paste(image, (index * width, 0))
        draw.text((index * width + 8, 6), name, fill=(255, 255, 255, 255))
        (out.parent / f".tile_{name}.png").unlink(missing_ok=True)
    sheet.save(out)
    print(f"wrote {out.relative_to(ROOT)}")
    return sheet


USAGE = ("usage: preview_block_model.py [MODEL[:SHIFT][,MODEL[:SHIFT]] | --raw PATH] "
         "--out PATH [--yaw DEG] [--pitch DEG] [--scale N | --fit] [--size WxH] [--pan X,Y] "
         "[--clay [R,G,B]] [--bg R,G,B] [--views front,quarter,top] [--textured]")


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(USAGE)
    out = ROOT / "build/preview_keybed/preview.png"
    yaw, pitch, scale = 0.0, 0.0, 16.0
    width, height = 900, 520
    pan = [0.0, 0.0]
    background = (0, 0, 0, 0)
    clay = None
    views = []
    cells = None
    raw_model = None
    fit = False
    only = None
    args = list(argv)
    if not args[0].startswith("--"):
        cells = parse_cells(args[0])
        args = args[1:]
    index = 0
    while index < len(args):
        flag = args[index]
        raw = args[index + 1] if index + 1 < len(args) else None
        has_value = raw is not None and not raw.startswith("--")
        value = raw if has_value else None
        consumed = 2 if has_value else 1
        if flag == "--out" and value:
            out = ROOT / value
        elif flag == "--yaw" and value:
            yaw = float(value)
        elif flag == "--pitch" and value:
            pitch = float(value)
        elif flag == "--scale" and value:
            scale = float(value)
        elif flag == "--size" and value:
            width, height = (int(v) for v in value.lower().split("x"))
        elif flag == "--pan" and value:
            pan[0], pan[1] = (float(v) for v in value.split(","))
        elif flag == "--clay":
            clay = tuple(float(v) / 255.0 for v in value.split(",")) if value else CLAY
        elif flag == "--bg" and value:
            background = tuple(int(v) for v in value.split(",")) + (255,)
        elif flag == "--views" and value:
            views = [part.strip() for part in value.split(",") if part.strip()]
        elif flag == "--raw" and value:
            raw_model = json.loads((ROOT / value).read_text(encoding="utf-8"))
        elif flag == "--fit":
            fit = True
        elif flag == "--only" and value:
            only = value
        elif flag == "--textured":
            clay = None
        else:
            raise SystemExit(f"unknown flag {flag}")
        index += consumed
    if raw_model is not None:
        quads = collect_model(raw_model, (0.0, 0.0), 1.0)
    elif cells is not None:
        quads = collect(cells, 1.0)
    else:
        raise SystemExit(USAGE)
    # --only narrows the framing target, not the drawing: fit and centre on the named elements but
    # still draw everything, which is how a keyboard close-up is taken without guessing pan values.
    focus = [quad for quad in quads if quad["name"].startswith(only)] if only else None
    if only and not focus:
        raise SystemExit(f"--only {only}: no element name starts with that")
    if fit and not views:
        scale = fit_scale(focus or quads, yaw, pitch, width, height)
    if views:
        contact_sheet(quads, out, views, None if fit else scale, width, height,
                      background=background, clay=clay, pan=(pan[0], pan[1]), focus=focus)
    else:
        render(quads, out, scale, yaw, pitch, width, height, background=background,
               pan=(pan[0], pan[1]), clay=clay)


if __name__ == "__main__":
    main(sys.argv[1:])
