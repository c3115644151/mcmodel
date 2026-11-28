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
from icon_overrides import (FIELDS, apply_screen_offset, apply_yaw_rotation,
                             effective_params, load_overrides, save_overrides)
from item_icon_proxy import (VANILLA_BLOCK_GUI, geometry_bounds, gui_icon_target_px,
                              normalize_to_block, fit_gui_projection)
from item_icon_preview import (render_projected_icon, shade_profile,
                               visible_projected_measurements)
from normalize_item_icons import (collect_model_sources, resolve_model,
                                   load_model_with_parent, resolve_texture,
                                   collect_model_ids, source_model_id)

ROOT = Path.cwd().resolve()
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


def item_shade(item_id: str, overrides: dict[str, Any] | None = None) -> str:
    """Shading profile for an item: its override, else the game-matching default."""
    table = overrides if overrides is not None else load_overrides(ROOT)
    return str(table.get(item_id, {}).get("shade", "game"))


def render_thumb(item_id: str, shade: str | None = None) -> str | None:
    """Render the fitted proxy already on disk (no fit pass); base64 PNG or None."""
    path = ASSETS / "models/item_icons" / item_id / "variant_0.json"
    if not path.is_file():
        return None
    shade = shade or item_shade(item_id)
    stat = path.stat()
    # The shade profile changes the pixels but not the proxy file, so it belongs in
    # the cache key; keying on mtime alone would serve a stale-lit thumbnail.
    stamp = (stat.st_mtime_ns, stat.st_size, shade)
    cached = _THUMB_CACHE.get(item_id)
    if cached and cached[0] == stamp:
        return cached[1]
    model = json.loads(path.read_text(encoding="utf-8"))
    resolver = lambda ref: resolve_texture(ROOT, ref)
    try:
        # Full 16px slot canvas, icon at its true in-slot proportion. No cropping:
        # each grid cell is one complete vanilla slot, exactly what the player sees.
        image = render_projected_icon(model, resolver, size=ICON_SIZE,
                                      face_shade=shade_profile(shade))
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
    model = definition.get("model", {})
    gui = next((c.get("model") for c in model.get("cases", [])
                if c.get("when") in ("gui", ["gui"])), {})
    model_ids = collect_model_ids(gui)
    sources = collect_model_sources(model_ids, ASSETS, MOD_ID)
    if not sources:
        gui2 = next((c.get("model") for c in model.get("cases", [])
                     if c.get("when") in ("gui", ["gui"])), {})
        all_ids = list(dict.fromkeys(model_ids + collect_model_ids(definition.get("model", {}).get("fallback", {}))))
        sources = collect_model_sources(all_ids, ASSETS, MOD_ID)
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
    model = definition.get("model", {})
    gui = next((c.get("model") for c in model.get("cases", [])
                if c.get("when") in ("gui", ["gui"])), {})
    model_ids = collect_model_ids(gui)
    sources = collect_model_sources(model_ids, ASSETS, MOD_ID)
    if not sources:
        raise ValueError(f"{item_id}: no GUI source geometry")
    # Source override swaps the model before anything else.
    source_override = candidate.get("source")
    if source_override:
        sources = collect_model_sources([source_override], ASSETS, MOD_ID)
        if not sources:
            raise ValueError(f"{item_id}: source override {source_override} has no geometry")
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
    if scale_factor:
        proxy = apply_yaw_rotation(proxy, scale_factor)
    centred = fit_gui_projection(proxy, resolver, target_px=target_px, floor_anchor=False)
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
        f2 = fit_gui_projection(proxy, resolver, target_px=target_px, floor_anchor=True)
        if f2:
            fitted = f2
    proxy = fitted["model"]
    ox, oy = params["offset_x"], params["offset_y"]
    if ox or oy:
        shifted = apply_screen_offset(proxy, resolver, ox, oy, VANILLA_BLOCK_GUI["scale"][0])
        if shifted is not None:
            proxy = shifted
    proxy["parent"] = _source

    measured = visible_projected_measurements(proxy, resolver, pixels_per_unit=16)
    image = render_projected_icon(proxy, resolver, size=ICON_SIZE,
                                  face_shade=shade_profile(str(candidate.get("shade") or "game")))
    report = {"item": item_id, "target_px": target_px, "floor_anchor": floor_anchor,
              "yaw": scale_factor, "offset_x": ox, "offset_y": oy,
              "shade": str(candidate.get("shade") or "game"),
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
            elif path == "/api/thumb":
                item_id = qs.get("item", [""])[0]
                data = render_thumb(item_id) if item_id else None
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
        geometry_fields = set(FIELDS) - {"shade", "note"}
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
