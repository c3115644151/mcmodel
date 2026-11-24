#!/usr/bin/env python3
"""Build one-block GUI-only proxy models for every local mod item.

World/hand models are never edited. Each item definition selects its normalized
proxy only in GUI display context and falls back to its original model elsewhere.
Run without --apply to audit the planned resource changes first.

Every proxy carries exactly the display minecraft:block/block gives a vanilla
block item: rotation [30, 225, 0], no translation, scale 0.625. Icon placement is
therefore inherited from Minecraft instead of solved per item; the earlier
per-item fitter produced 108 distinct translations (one y offset reached 5.1, a
third of a slot) and 67 icons turned to their back face, which is what made icons
look crooked, oversized and occasionally invisible.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
import tempfile
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from item_icon_proxy import (
    ITEM_ICON_MANIFEST,
    TRANSFORM_CARRIER_MODELS,
    VANILLA_BLOCK_GUI,
    collect_model_ids,
    geometry_bounds,
    normalize_to_block,
    replace_gui_case_model_ids,
    replace_model_ids,
    unwrap_generated_gui_select,
    wrap_gui_only,
)
from item_icon_preview import visible_projected_measurements


def write_json_atomic(path: Path, payload: object) -> None:
    """Write JSON so a concurrent reader never sees a half-written manifest.

    Two Gradle invocations can run the same producer task at once; a plain write_text truncates the
    file in place, so the loser of that race can leave a duplicated tail behind. Write beside the
    target and rename over it, then re-read to prove the bytes parse.
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        for attempt in range(5):
            try:
                os.replace(temp_name, path)
                break
            except PermissionError:
                # Windows refuses the rename while a scanner or a sibling build still holds the
                # destination open; retry briefly, then fall back to an in-place write.
                if attempt == 4:
                    path.write_text(text, encoding="utf-8")
                    Path(temp_name).unlink(missing_ok=True)
                else:
                    time.sleep(0.2)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    json.loads(path.read_text(encoding="utf-8"))


def resolve_model(model_id: str, assets_root: Path, mod_id: str) -> Path | None:
    namespace, separator, relative = model_id.partition(":")
    if not separator:
        namespace, relative = mod_id, model_id
    if namespace != mod_id:
        return None
    return assets_root / "models" / f"{relative}.json"


def resolve_texture(root: Path, texture_id: str) -> Path | None:
    namespace, separator, relative = texture_id.partition(":")
    if not separator:
        namespace, relative = "minecraft", texture_id
    if "/" not in relative:
        return None
    texture_type, name = relative.split("/", 1)
    return root / "src/main/resources/assets" / namespace / "textures" / texture_type / f"{name}.png"


def load_model_with_parent(path: Path, assets_root: Path, mod_id: str, visited=None) -> dict | None:
    visited = visited or set()
    path = path.resolve()
    if path in visited or not path.is_file():
        return None
    visited.add(path)
    model = json.loads(path.read_text(encoding="utf-8"))
    if model.get("elements"):
        return model
    parent = model.get("parent")
    if parent:
        parent_path = resolve_model(parent, assets_root, mod_id)
        if parent_path:
            inherited = load_model_with_parent(parent_path, assets_root, mod_id, visited)
            if inherited:
                merged = deepcopy(inherited)
                merged.update(model)
                merged["elements"] = inherited.get("elements", [])
                merged["textures"] = {**inherited.get("textures", {}), **model.get("textures", {})}
                return merged
    return model


def source_model_id(model_id: str, assets_root: Path, mod_id: str) -> str:
    """Unwrap a prior proxy so repeated normalization remains deterministic."""
    if not model_id.startswith(f"{mod_id}:item_icons/"):
        return model_id
    proxy_path = resolve_model(model_id, assets_root, mod_id)
    if proxy_path and proxy_path.is_file():
        proxy = json.loads(proxy_path.read_text(encoding="utf-8"))
        parent = proxy.get("parent")
        if isinstance(parent, str) and parent:
            return parent
    return model_id


def generated_gui_owned(model_node, mod_id: str) -> list[str]:
    """Return the proxy ids a rebuilt item definition actually shows in the GUI.

    An authored GUI case (art-directed front/back composite) keeps its own models,
    so the generator never owns that item and must not claim its proxies.
    """
    if not isinstance(model_node, dict) or model_node.get("type") != "minecraft:select" \
            or model_node.get("property") != "minecraft:display_context":
        return []
    gui_case = next((case for case in model_node.get("cases", [])
                     if case.get("when") in ("gui", ["gui"])), None)
    if gui_case is None:
        return []
    proxy_ids = [model_id for model_id in collect_model_ids(gui_case.get("model", {}))
                 if model_id not in TRANSFORM_CARRIER_MODELS]
    if not proxy_ids or not all(model_id.startswith(f"{mod_id}:item_icons/") for model_id in proxy_ids):
        return []
    return proxy_ids


def collect_model_sources(model_ids, assets_root: Path, mod_id: str) -> list:
    sources = []
    for referenced_id in model_ids:
        source_id = source_model_id(referenced_id, assets_root, mod_id)
        model_path = resolve_model(source_id, assets_root, mod_id)
        model = load_model_with_parent(model_path, assets_root, mod_id) if model_path else None
        if model and model.get("elements"):
            sources.append((referenced_id, source_id, model, model_path))
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="mod project root (default: detected project)")
    parser.add_argument("--apply", action="store_true", help="write GUI proxy models and item definitions")
    parser.add_argument("--items", default="", help="comma-separated item ids; default is all")
    parser.add_argument("--target-size", type=float, default=16.0,
                        help="maximum 3D model-space edge of each icon proxy (default: one vanilla block)")
    parser.add_argument("--report", type=Path, default=None, help="optional JSON audit report output")
    args = parser.parse_args()

    root = (args.root or Path.cwd()).resolve()
    config = resolve({"root": str(root)})
    mod_id = config.get("mod_id")
    if not mod_id:
        parser.error(f"could not detect mod id under {root}")
    assets_root = root / "src/main/resources/assets" / mod_id
    items_dir = assets_root / "items"
    requested = {part.strip() for part in args.items.split(",") if part.strip()}
    if not items_dir.is_dir():
        parser.error(f"item definition directory not found: {items_dir}")

    item_updates: dict[Path, dict] = {}
    proxy_updates: dict[Path, dict] = {}
    report = []
    # The generated proxies embed an art decision (facing-aware default, an
    # authored .bbmodel transform, or the vanilla default). Record it next to the
    # project so validators read one expectation instead of recomputing their own.
    manifest: dict[str, dict] = {}
    dropped_items: set[str] = set()
    for item_path in sorted(items_dir.glob("*.json")):
        item_id = item_path.stem
        if requested and item_id not in requested:
            continue
        definition = json.loads(item_path.read_text(encoding="utf-8"))
        existing_tree = definition.get("model", {})
        original_tree = unwrap_generated_gui_select(existing_tree, mod_id)
        if (isinstance(original_tree, dict) and original_tree.get("type") == "minecraft:select"
                and original_tree.get("property") == "minecraft:display_context"):
            gui_tree = next((case.get("model", {}) for case in original_tree.get("cases", [])
                             if case.get("when") in ("gui", ["gui"])), {})
        else:
            gui_tree = original_tree
        # A hand-authored flat GUI icon (models/item/gui/*) is already the final
        # 16px picture; projecting it through the proxy pipeline would replace it
        # with a squashed 3D thumbnail and rewrite the item definition each build.
        if isinstance(gui_tree, dict) and gui_tree.get("type") == "minecraft:model":
            hand_authored = gui_tree.get("model", "")
            if isinstance(hand_authored, str) and hand_authored.startswith(f"{mod_id}:item/gui/"):
                report.append({"item": item_id, "status": "skipped_hand_authored_gui", "models": [hand_authored]})
                dropped_items.add(item_id)
                continue
        # Only models the GUI branch actually shows get a proxy; collecting ids from
        # the fallback as well produced proxies nobody references (a rug whose
        # fallback model is a child of its GUI model left a dead variant behind).
        model_ids = collect_model_ids(gui_tree)
        model_sources = collect_model_sources(model_ids, assets_root, mod_id)
        if not model_sources:
            # A GUI case that only wraps a transform carrier has nothing to normalize;
            # borrow the held/world model so the slot is not left empty.
            model_ids = list(dict.fromkeys(
                model_ids + collect_model_ids(original_tree.get("fallback", {}))))
            model_sources = collect_model_sources(model_ids, assets_root, mod_id)
        if not model_sources:
            report.append({"item": item_id, "status": "skipped_no_local_geometry", "models": model_ids})
            continue

        all_elements = [deepcopy(element) for _ref, _source, model, _path in model_sources
                        for element in model.get("elements", [])]
        shared_bounds = geometry_bounds({"elements": all_elements})
        if shared_bounds is None:
            report.append({"item": item_id, "status": "skipped_no_geometry", "models": model_ids})
            continue

        source_gui, gui_is_explicit, gui_source = (
            deepcopy(VANILLA_BLOCK_GUI), False, "vanilla_block_gui")
        replacements = {}
        variant_results = []
        normalized_variants = []
        for variant_index, (referenced_id, source_id, model, _model_path) in enumerate(model_sources):
            proxy_model_id = f"{mod_id}:item_icons/{item_id}/variant_{variant_index}"
            normalized = normalize_to_block(model, target_size=args.target_size,
                                            reference_bounds=shared_bounds)
            if not normalized:
                continue
            proxy = normalized["model"]
            proxy["parent"] = source_id
            proxy_path = assets_root / "models" / "item_icons" / item_id / f"variant_{variant_index}.json"
            replacements[referenced_id] = proxy_model_id
            normalized_variants.append((proxy_path, proxy, normalized, source_id, proxy_model_id))

        # Measure the visible, textured projection for every GUI state as one
        # item family. Variants can normalize to different scales, since a
        # composite model (a barrel whose water layer grows) changes the union
        # bounds. Take the smallest scale the family agrees on and center each
        # variant at that scale: every state stays inside the slot, and cycling
        # states cannot make the icon jump.
        projected = [
            visible_projected_measurements(proxy, lambda ref: resolve_texture(root, ref), pixels_per_unit=8)
            for _path, proxy, _normalized, _source_id, _proxy_id in normalized_variants
        ]
        if all(measured is None for measured in projected):
            raise ValueError(f"{item_id}: GUI icon preview could not measure visible model alpha")
        # One scale for the whole item family so cycling states cannot make the icon
        # jump, and it is vanilla's own scale: the proxy geometry already fits one
        # block, exactly like a vanilla block model, so nothing needs re-centering.
        shared_scale = list(VANILLA_BLOCK_GUI["scale"])
        gui_translations = [(0.0, 0.0, 0.0)] * len(normalized_variants)
        for (_path, proxy, normalized, _source_id, _proxy_id) in normalized_variants:
            proxy["display"]["gui"]["scale"] = list(shared_scale)
            normalized["gui_scale"] = shared_scale

        for variant_index, (proxy_path, proxy, normalized, source_id, proxy_model_id) in enumerate(
                normalized_variants):
            gui_translation = gui_translations[variant_index]
            proxy["display"]["gui"]["translation"] = list(gui_translation)
            proxy_updates[proxy_path] = proxy
            variant_results.append({
                "source": source_id,
                "proxy": proxy_model_id,
                "scale": round(normalized["scale"], 6),
                "gui_scale": [round(value, 6) for value in normalized["gui_scale"]],
                "gui_translation": list(gui_translation),
                "authored_gui_transform": gui_is_explicit,
                "gui_source": gui_source,
                "source_bounds": [round(v, 4) for v in normalized["source_bounds"]],
                "normalized_bounds": [round(v, 4) for v in normalized["final_bounds"]],
            })

        if not replacements:
            report.append({"item": item_id, "status": "skipped_no_proxy", "models": model_ids})
            continue
        item_update = deepcopy(definition)
        if (isinstance(original_tree, dict) and original_tree.get("type") == "minecraft:select"
                and original_tree.get("property") == "minecraft:display_context"):
            carrier_replacement = next(
                ({"type": "minecraft:model", "model": replacements[fallback_id]}
                 for fallback_id in collect_model_ids(original_tree.get("fallback", {}))
                 if fallback_id in replacements),
                None,
            )
            item_update["model"] = replace_gui_case_model_ids(
                original_tree, replacements, carrier_replacement)
        else:
            gui_tree = replace_model_ids(original_tree, replacements)
            item_update["model"] = wrap_gui_only(gui_tree, original_tree)
        item_updates[item_path] = item_update
        gui_transform = deepcopy(
            proxy_updates[assets_root / "models" / "item_icons" / item_id / "variant_0.json"]["display"]["gui"])
        report.append({"item": item_id, "status": "ready" if args.apply else "dry_run",
                       "variants": variant_results,
                       "non_gui_fallback_preserved": True,
                       "gui_transform": gui_transform})
        owned_ids = generated_gui_owned(item_update["model"], mod_id)
        if not owned_ids:
            # Another pipeline authored this item's GUI model; the proxies built here
            # are unreachable, so drop them instead of leaving dead models behind.
            for proxy_path in (assets_root / "models" / "item_icons" / item_id).glob("variant_*.json"):
                proxy_updates.pop(proxy_path, None)
            item_updates.pop(item_path, None)
            dropped_items.add(item_id)
            report.append({"item": item_id, "status": "skipped_authored_gui", "models": model_ids})
            continue
        manifest[item_id] = {
            "gui": gui_transform,
            "gui_source": gui_source,
            "authored_gui_transform": gui_is_explicit,
            "proxies": owned_ids,
        }

    if args.apply:
        for path, model in proxy_updates.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for path, definition in item_updates.items():
            path.write_text(json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = {path.resolve() for path in proxy_updates}
        # Only prune the item directories this run regenerated: per-item builds
        # (build.gradle --items X) must not delete every other item's proxies.
        touched_dirs = sorted({path.parent for path in proxy_updates})
        for item_id in sorted(dropped_items):
            item_dir = assets_root / "models" / "item_icons" / item_id
            if item_dir.is_dir():
                for stale in item_dir.glob("variant_*.json"):
                    stale.unlink()
                if not any(item_dir.iterdir()):
                    item_dir.rmdir()
        for item_dir in touched_dirs:
            if not item_dir.is_dir():
                continue
            for stale in sorted(item_dir.glob("variant_*.json")):
                if stale.resolve() in written:
                    continue
                stale.unlink()
            if not any(item_dir.iterdir()):
                item_dir.rmdir()
        manifest_path = root / ITEM_ICON_MANIFEST
        merged: dict[str, dict] = {}
        if manifest_path.is_file():
            try:
                merged = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", {})
            except (OSError, json.JSONDecodeError):
                merged = {}
        for item_id in dropped_items:
            merged.pop(item_id, None)
        merged.update(manifest)
        write_json_atomic(
            manifest_path,
            {"version": 1, "items": dict(sorted(merged.items()))},
        )

    for entry in report:
        if entry.get("variants"):
            scales = [variant["scale"] for variant in entry["variants"]]
            gui_scales = [variant["gui_scale"][0] for variant in entry["variants"]]
            print(f"{entry['item']}: {entry['status']} {len(scales)} GUI proxy/proxies, "
                  f"geometry scale={min(scales):.3f}..{max(scales):.3f}, "
                  f"GUI scale={min(gui_scales):.3f}..{max(gui_scales):.3f}; non-GUI fallback preserved")
        else:
            print(f"{entry['item']}: {entry['status']}")
    if args.report:
        path = args.report if args.report.is_absolute() else root / args.report
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Audited {len(report)} items; {len(proxy_updates)} GUI-only proxy models; "
          f"mode={'apply' if args.apply else 'dry_run'}. "
          "Every proxy uses minecraft:block/block's GUI display: rotation [30, 225, 0], no translation, scale 0.625.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
