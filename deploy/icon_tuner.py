#!/usr/bin/env python3
r"""Local GUI-icon tuner: render any item's icon with candidate overrides, exactly
the way the generator would, and serve a tiny HTML editor over http.server.

No third-party deps beyond the project's Pillow/numpy. Start:
  .venv\Scripts\python.exe tools/deploy/icon_tuner.py [--port 8765]
Then open http://127.0.0.1:8765 in a browser.

The preview calls the SAME generator primitives (normalize_to_block ->
fit_gui_projection -> icon_overrides transforms) so what the tuner shows is what
`normalize_item_icons.py --apply` will ship. It is still an offline software
preview, not the game's GPU output; use game screenshots for final acceptance.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from item_ids import official_items
from icon_overrides import (FIELDS, apply_screen_offset, yaw_gui_rotation,
                             effective_params, load_overrides, save_overrides)
from item_icon_proxy import (VANILLA_BLOCK_GUI, geometry_bounds, gui_icon_target_px,
                              normalize_to_block, fit_gui_projection)
from item_icon_preview import (render_projected_icon, shade_profile,
                               visible_projected_measurements)
from normalize_item_icons import (collect_model_sources, resolve_model,
                                   load_model_with_parent, resolve_texture,
                                   collect_model_ids, source_model_id,
                                   resolve_gui_sources)

# 项目根取 tools/deploy 的上两级，而不是 cwd：从计划任务/其它目录启动时 cwd 是
# System32，按 cwd 解析会把 assets 指到不存在的地方，服务起来但每个接口都 500。
ROOT = Path(__file__).resolve().parents[2]
CONFIG = resolve({"root": str(ROOT)})
MOD_ID = CONFIG.get("mod_id", "pastoral_home")
ASSETS = ROOT / "src/main/resources/assets" / MOD_ID
ITEMS_DIR = ASSETS / "items"
ZOOM = 8
ICON_SIZE = 64  # render resolution; editor displays 1x (16px) and zoomed

# Thumbnails render the already-fitted proxy on disk (cheap) and are cached, so the
# grid never runs the full fit pipeline 80+ times at once and starves the server.
# The cache key includes the proxy's mtime+size so a saved override that regenerates
# a proxy immediately shows up in the grid on the next request.
_THUMB_CACHE: dict[str, tuple[tuple[float, int], str]] = {}


VANILLA_SLOT_REL = ("assets/minecraft/textures/gui/sprites/container/slot.png")
SLOT_PIXELS = 18  # vanilla AbstractContainerMenu.SLOT_SIZE: 1px bevel + 16px icon area


def vanilla_slot_png() -> bytes:
    """The vanilla container slot sprite (18x18, bevelled), as PNG bytes.

    The grid draws exactly this sprite so a cell is the game's slot, not a grey
    rectangle that merely looks similar: dark #373737 on the top/left, white on the
    bottom/right, #8b8b8b fill, icon occupying the inner 16x16.

    Read from the NeoForm transformed assets when present (that is the game's own
    copy); otherwise synthesise the same 18 pixels so the tuner still renders the
    correct bevel on a machine without that checkout.
    """
    cached = getattr(vanilla_slot_png, "_cache", None)
    if cached is not None:
        return cached
    for candidate in sorted(ROOT.glob("build/*/neoForm*/steps/transformSource/transformed/"
                                      + VANILLA_SLOT_REL)):
        if candidate.is_file():
            cached = candidate.read_bytes()
            vanilla_slot_png._cache = cached
            return cached
    image = Image.new("RGBA", (SLOT_PIXELS, SLOT_PIXELS), (0x8B, 0x8B, 0x8B, 255))
    pixels = image.load()
    for index in range(SLOT_PIXELS):
        pixels[index, 0] = (0x37, 0x37, 0x37, 255)          # top edge
        pixels[0, index] = (0x37, 0x37, 0x37, 255)          # left edge
        pixels[index, SLOT_PIXELS - 1] = (255, 255, 255, 255)  # bottom edge
        pixels[SLOT_PIXELS - 1, index] = (255, 255, 255, 255)  # right edge
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    cached = buf.getvalue()
    vanilla_slot_png._cache = cached
    return cached


PANEL_REL = "assets/minecraft/textures/gui/container/inventory.png"
PANEL_SPRITE = (176, 166)   # vanilla container panel size
PANEL_FRAME = 4             # 1px black outline + 3px light/shadow edge
PANEL_PAD = 7               # vanilla container: the slot sprite starts 7px inside the panel
PANEL_BODY = (0xC6, 0xC6, 0xC6, 255)


def vanilla_panel_png(rows: int, cols: int) -> bytes:
    """A container panel of rows x cols vanilla slots, as PNG bytes.

    The sidebar shows icons "inside one GUI" instead of as loose cards: the panel is
    the vanilla container frame (the same 1px black outline, 3px light edge, #c6c6c6
    body and #555555 inner shadow as textures/gui/container/inventory.png) and the
    slots are the vanilla slot sprite tiled on the same 18px lattice the game uses.

    Verified against the game: the 3x9 main inventory grid of inventory.png is exactly
    the slot sprite tiled at 18px, so a tiled grid is the game's grid, not an
    approximation of it.
    """
    cache = getattr(vanilla_panel_png, "_cache", None)
    if cache is None:
        cache = {}
        vanilla_panel_png._cache = cache
    rows = max(1, min(64, int(rows)))
    cols = max(1, min(12, int(cols)))
    key = (rows, cols)
    if key in cache:
        return cache[key]
    width = PANEL_PAD * 2 + SLOT_PIXELS * cols
    height = PANEL_PAD * 2 + SLOT_PIXELS * rows
    panel = Image.new("RGBA", (width, height), PANEL_BODY)
    frame = None
    for candidate in sorted(ROOT.glob("build/*/neoForm*/steps/transformSource/transformed/"
                                      + PANEL_REL)):
        if candidate.is_file():
            candidate_image = Image.open(candidate).convert("RGBA")
            if candidate_image.size == (256, 256):
                frame = candidate_image.crop((0, 0, PANEL_SPRITE[0], PANEL_SPRITE[1]))
                break
    if frame is not None:
        pw, ph = PANEL_SPRITE
        edge = PANEL_FRAME
        inner_w, inner_h = width - 2 * edge, height - 2 * edge
        # 四角原样搬，四条边按最近邻拉伸即可（每条边沿自身方向是纯色带，拉伸等于平铺）。
        panel.paste(frame.crop((0, 0, edge, edge)), (0, 0))
        panel.paste(frame.crop((pw - edge, 0, pw, edge)), (width - edge, 0))
        panel.paste(frame.crop((0, ph - edge, edge, ph)), (0, height - edge))
        panel.paste(frame.crop((pw - edge, ph - edge, pw, ph)), (width - edge, height - edge))
        panel.paste(frame.crop((edge, 0, pw - edge, edge)).resize((inner_w, edge), Image.NEAREST),
                    (edge, 0))
        panel.paste(frame.crop((edge, ph - edge, pw - edge, ph)).resize((inner_w, edge), Image.NEAREST),
                    (edge, height - edge))
        panel.paste(frame.crop((0, edge, edge, ph - edge)).resize((edge, inner_h), Image.NEAREST),
                    (0, edge))
        panel.paste(frame.crop((pw - edge, edge, pw, ph - edge)).resize((edge, inner_h), Image.NEAREST),
                    (width - edge, edge))
    slot = Image.open(io.BytesIO(vanilla_slot_png())).convert("RGBA")
    for row in range(rows):
        for col in range(cols):
            panel.alpha_composite(slot, (PANEL_PAD + col * SLOT_PIXELS,
                                         PANEL_PAD + row * SLOT_PIXELS))
    buffer = io.BytesIO()
    panel.save(buffer, format="PNG")
    data = buffer.getvalue()
    cache[key] = data
    return data


def registered_item_ids() -> set[str]:
    """Ids the creative tab offers; internal render parts are excluded.

    ModItems also registers component items (globe_sphere_render, wheelbarrow_wheel,
    weather_vane_base, bulletin_page, ...) that the player can never hold, so the tab
    is the real inventory-item set.
    """
    return set(official_items(ROOT))


def item_ids() -> list[str]:
    """Registered items that have a generated GUI proxy (skip model components)."""
    registered = registered_item_ids()
    ids = []
    for path in sorted(ITEMS_DIR.glob("*.json")):
        if path.stem not in registered:
            continue
        definition = json.loads(path.read_text(encoding="utf-8"))
        model = definition.get("model", {})
        if not isinstance(model, dict) or model.get("type") != "minecraft:select":
            continue
        if model.get("property") != "minecraft:display_context":
            continue
        gui = next((c.get("model") for c in model.get("cases", [])
                    if c.get("when") in ("gui", ["gui"])), None)
        if gui is None:
            continue
        proxies = [m for m in collect_model_ids(gui) if f"{MOD_ID}:item_icons/" in m]
        if proxies:
            ids.append(path.stem)
    return ids


def item_shade_strength(item_id: str, overrides: dict[str, Any] | None = None) -> float:
    """Shading strength for an item: its override, else the game-matching default (1.0)."""
    table = overrides if overrides is not None else load_overrides(ROOT)
    auto = {"target_px": 15.7, "floor_anchor": False}
    return float(effective_params(item_id, auto, table)["shade_strength"])


def item_shade(item_id: str, overrides: dict[str, Any] | None = None) -> str:
    """Coarse label (game/flat) for an item's shading, kept for reports and the UI."""
    return "flat" if item_shade_strength(item_id, overrides) <= 0 else "game"


def render_thumb(item_id: str, shade_strength: float | None = None,
                 size: int = ICON_SIZE) -> str | None:
    """Render the fitted proxy already on disk (no fit pass); base64 PNG or None.

    size is the canvas pixel size (multiples of 16 = 4x per slot pixel). The grid
    can be dragged wide, so a fixed 64px canvas would be upscaled 8x and look soft;
    the page asks for 64 or 128 depending on the cell width.
    """
    path = ASSETS / "models/item_icons" / item_id / "variant_0.json"
    if not path.is_file():
        return None
    strength = item_shade_strength(item_id) if shade_strength is None else float(shade_strength)
    size = max(16, min(128, int(size)))
    stat = path.stat()
    # The shading strength changes the pixels but not the proxy file, so it belongs in
    # the cache key; keying on mtime alone would serve a stale-lit thumbnail.
    stamp = (stat.st_mtime_ns, stat.st_size, round(strength, 3), size)
    cached = _THUMB_CACHE.get(item_id)
    if cached and cached[0] == stamp:
        return cached[1]
    model = json.loads(path.read_text(encoding="utf-8"))
    resolver = lambda ref: resolve_texture(ROOT, ref)
    try:
        # Full 16px slot canvas, icon at its true in-slot proportion. No cropping:
        # each grid cell is one complete vanilla slot, exactly what the player sees.
        rotation = tuple(model.get("display", {}).get("gui", {}).get("rotation",
                                                                    VANILLA_BLOCK_GUI["rotation"]))
        image = render_projected_icon(model, resolver, size=size,
                                      gui_rotation=rotation,
                                      face_shade=shade_profile(None, strength))
    except Exception:
        return None
    data = base64.b64encode(png_response(image)).decode("ascii")
    _THUMB_CACHE[item_id] = (stamp, data)
    return data


def regenerate_item(item_id: str) -> bool:
    """Run the generator for one item so a saved override reaches its proxy."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "normalize_item_icons.py"),
         "--apply", "--items", item_id],
        cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0


def auto_params(item_id: str) -> dict[str, Any]:
    """Recompute the generator's automatic params for an item (no overrides)."""
    definition = json.loads((ITEMS_DIR / f"{item_id}.json").read_text(encoding="utf-8"))
    sources, _status, _ids = resolve_gui_sources(definition.get("model", {}), ASSETS, MOD_ID)
    if not sources:
        return {"target_px": 15.7, "floor_anchor": False, "source": None}
    bounds = geometry_bounds({"elements": [e for _r, _s, m, _p in sources for e in m.get("elements", [])]})
    if bounds is None:
        return {"target_px": 15.7, "floor_anchor": False, "source": None}
    longest = max(bounds[i + 3] - bounds[i] for i in range(3))
    return {"target_px": gui_icon_target_px(longest), "floor_anchor": False, "source": None}


def render_icon(item_id: str, candidate: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:  # noqa: C901
    """Render one item's GUI icon with candidate override fields applied.

    Mirrors normalize_item_icons.main's fit pipeline exactly, then applies the
    override fields in the same order. Returns (image, measurement report).
    """
    definition = json.loads((ITEMS_DIR / f"{item_id}.json").read_text(encoding="utf-8"))
    # 与生成器同一条解析路径（含 fallback 与根变换烘焙）：预览和落盘 proxy 不能有两套几何。
    source_override = candidate.get("source") or None
    sources, status, _ids = resolve_gui_sources(
        definition.get("model", {}), ASSETS, MOD_ID, source_override)
    if not sources:
        raise ValueError(f"{item_id}: {status} (source override {source_override or 'none'})")
    all_elements = [e for _r, _s, m, _p in sources for e in m.get("elements", [])]
    bounds = geometry_bounds({"elements": all_elements})
    if bounds is None:
        raise ValueError(f"{item_id}: no geometry bounds")
    longest = max(bounds[i + 3] - bounds[i] for i in range(3))
    auto = auto_params(item_id)
    params = effective_params(item_id, auto, {item_id: candidate})
    target_px = params["target_px"]
    scale_factor = params["yaw"]

    resolver = lambda ref: resolve_texture(ROOT, ref)

    # First variant is the icon; multi-state items are handled by the generator's
    # own proxy layout, which the tuner shows as its first (fallback) state.
    _ref, _source, source_model, _path = sources[0]
    normalized = normalize_to_block(source_model, target_size=16.0, reference_bounds=bounds)
    if not normalized:
        raise ValueError(f"{item_id}: normalize failed")
    proxy = normalized["model"]
    # 额外朝向 = 相机旋转，几何原样（几何旋转会把轴对齐 box 拆坏）。
    gui_rotation = yaw_gui_rotation(scale_factor, (VANILLA_BLOCK_GUI["rotation"]))
    centred = fit_gui_projection(proxy, resolver, target_px=target_px, floor_anchor=False,
                                 gui_rotation=gui_rotation)
    if not centred:
        raise ValueError(f"{item_id}: fit failed")
    proj_h = centred["fit_projected_size"][1]
    floor_anchor = proj_h < 15.7 * 0.95
    anchor = candidate.get("anchor", "auto")
    if anchor == "floor":
        floor_anchor = True
    elif anchor == "center":
        floor_anchor = False
    fitted = centred
    if floor_anchor:
        f2 = fit_gui_projection(proxy, resolver, target_px=target_px, floor_anchor=True,
                                gui_rotation=gui_rotation)
        if f2:
            fitted = f2
    proxy = fitted["model"]
    ox, oy = params["offset_x"], params["offset_y"]
    if ox or oy:
        shifted = apply_screen_offset(proxy, resolver, ox, oy, VANILLA_BLOCK_GUI["scale"][0],
                                      gui_rotation=gui_rotation)
        if shifted is not None:
            proxy = shifted
    proxy["parent"] = _source

    measured = visible_projected_measurements(proxy, resolver, pixels_per_unit=16)
    strength = params["shade_strength"]
    image = render_projected_icon(proxy, resolver, size=ICON_SIZE,
                                  gui_rotation=tuple(gui_rotation),
                                  face_shade=shade_profile(None, strength))
    report = {"item": item_id, "target_px": target_px, "floor_anchor": floor_anchor,
              "yaw": scale_factor, "gui_rotation": list(gui_rotation),
              "offset_x": ox, "offset_y": oy,
              "shade": params["shade"], "shade_strength": strength,
              "source_override": source_override, "effective": params,
              "bounds": [round(v, 3) for v in measured["bounds"]] if measured else None}
    return image, report


def png_response(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Never cache: this dev tool is edited live and a stale page shows old
        # layout/CSS, which is exactly the kind of false verification to avoid.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                html = (Path(__file__).resolve().parent / "icon_tuner.html").read_text(encoding="utf-8")
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/items":
                overrides = load_overrides(ROOT)
                ids = item_ids()
                self._json({"items": [{"id": i, "overridden": i in overrides} for i in ids],
                            "count": len(ids)})
            elif path == "/api/source-options":
                # candidate GUI source models: every block model with elements
                options = []
                for model_path in sorted((ASSETS / "models/block").glob("*.json")):
                    m = load_model_with_parent(model_path, ASSETS / "models", MOD_ID)
                    if m and m.get("elements"):
                        options.append(f"{MOD_ID}:block/{model_path.stem}")
                self._json({"options": options})
            elif path == "/api/overrides":
                self._json({"version": 1, "items": load_overrides(ROOT)})
            elif path == "/api/panel":
                rows = int((qs.get("rows") or ["1"])[0])
                cols = int((qs.get("cols") or ["6"])[0])
                self._send(200, vanilla_panel_png(rows, cols), "image/png")
            elif path == "/api/slot":
                # The grid cell background: vanilla's own 18x18 slot sprite.
                self._send(200, vanilla_slot_png(), "image/png")
            elif path == "/api/thumb":
                item_id = qs.get("item", [""])[0]
                px = int(qs.get("px", [str(ICON_SIZE)])[0] or ICON_SIZE)
                data = render_thumb(item_id, size=px) if item_id else None
                if data is None:
                    self._send(404, b"not found", "text/plain")
                else:
                    # <img src> needs raw PNG bytes, not a JSON wrapper.
                    self._send(200, base64.b64decode(data), "image/png")
            elif path == "/api/preview":
                item_id = qs.get("item", [""])[0]
                if not item_id:
                    self._json({"error": "missing item"}, 400); return
                overrides = load_overrides(ROOT)
                candidate = {}
                if "candidate" in qs:
                    candidate = json.loads(qs["candidate"][0])
                else:
                    candidate = overrides.get(item_id, {})
                image, report = render_icon(item_id, candidate)
                buf = io.BytesIO(); image.save(buf, format="PNG")
                self._json({"png": base64.b64encode(buf.getvalue()).decode("ascii"), "report": report})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/overrides":
            self._json({"error": "not found"}, 404); return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        overrides = payload.get("items")
        if not isinstance(overrides, dict):
            self._json({"error": "expected {items: {...}}"}, 400); return
        previous = load_overrides(ROOT)
        path = save_overrides(ROOT, overrides)
        # Only geometry overrides need a proxy rebuild: "shade" is a preview-time
        # lighting profile and never lands in the model. Regenerating on a shade
        # toggle would rewrite an unchanged proxy and slow the whole grid.
        geometry_fields = set(FIELDS) - {"shade", "shade_strength", "note"}
        stale = [i for i, fields in overrides.items()
                 if {k: v for k, v in fields.items() if k in geometry_fields}
                 != {k: v for k, v in previous.get(i, {}).items() if k in geometry_fields}]
        regenerated = [i for i in stale if regenerate_item(i)]
        self._json({"saved": str(path), "count": len(load_overrides(ROOT)),
                    "regenerated": regenerated})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    ids = item_ids()
    print(f"GUI icon tuner: {len(ids)} items, http://{args.host}:{args.port}")
    print("Offline software preview; use game screenshots for final acceptance.")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
