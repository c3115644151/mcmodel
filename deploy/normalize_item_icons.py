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
import shutil
import sys
import subprocess
import tempfile
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import resolve
from icon_overrides import (apply_screen_offset, effective_params, yaw_gui_rotation,
                             load_overrides)
from item_icon_proxy import (
    GUI_ICON_TARGET_PX,
    ITEM_ICON_MANIFEST,
    TRANSFORM_CARRIER_MODELS,
    VANILLA_BLOCK_GUI,
    bake_root_transform,
    collect_model_ids,
    fit_gui_projection,
    geometry_bounds,
    gui_icon_target_px,
    normalize_to_block,
    replace_gui_case_model_ids,
    replace_model_ids,
    unwrap_generated_gui_select,
    wrap_gui_only,
)
from item_icon_preview import visible_projected_measurements


def bake_root_sources(model_sources):
    """Bake translation-only root transforms before sizing and fitting.

    A root transform shifts the geometry when the model is baked, so the source box,
    the fit and the written proxy must all be measured after that shift; leaving the
    key in place also pushed element coordinates past Minecraft's [-16, 32] limit.
    """
    return [(referenced_id, source_id, bake_root_transform(model), path)
            for referenced_id, source_id, model, path in model_sources]


def mirror_path(root: Path, path: Path) -> None:
    """Copy one written resource into build/resources/main, keeping its path under assets/."""
    try:
        relative = path.resolve().relative_to((root / "src" / "main" / "resources").resolve())
    except ValueError:
        return
    target = root / "build" / "resources" / "main" / relative
    if target.is_file() and target.read_bytes() == path.read_bytes():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)


def write_json_atomic(path: Path, payload: object) -> None:
    """Write JSON so a concurrent reader never sees a half-written manifest.

    Two Gradle invocations can run the same producer task at once; a plain write_text truncates the
    file in place, so the loser of that race can leave a duplicated tail behind. Write beside the
    target and rename over it, then re-read to prove the bytes parse.
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        # 显式 newline="\n"：Windows 的 text 模式会把 \n 翻成 \r\n，而仓库存的是 LF，
        # 于是每次生成后 138 个 proxy 全部假脏（core.autocrlf=true 也不会替你消掉）。
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        for attempt in range(5):
            try:
                os.replace(temp_name, path)
                break
            except PermissionError:
                # Windows refuses the rename while a scanner or a sibling build still holds the
                # destination open; retry briefly, then fall back to an in-place write.
                if attempt == 4:
                    path.write_text(text, encoding="utf-8", newline="\n")
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
    direct = root / "src/main/resources/assets" / namespace / "textures" / texture_type / f"{name}.png"
    if direct.is_file():
        return direct
    # Vanilla textures are NOT copied into src/main/resources; NeoGradle unpacks
    # them into build/neoForm/<step>/steps/transformSource/transformed/assets.
    # Without this fallback a composite GUI layer that references e.g.
    # minecraft:block/water_still (water in a barrel) has no texture and renders
    # as a flat grey block in the offline preview.
    if namespace == "minecraft":
        transformed_root = root / "build" / "neoForm"
        if transformed_root.is_dir():
            for step in sorted(transformed_root.iterdir()):
                candidate = (step / "steps" / "transformSource" / "transformed"
                             / "assets" / "minecraft" / "textures"
                             / texture_type / f"{name}.png")
                if candidate.is_file():
                    return candidate
    return None


def load_model_with_parent(path: Path, assets_root: Path, mod_id: str, visited=None) -> dict | None:
    """Resolve a model the way the game does, including what a parent still supplies.

    A child that declares elements is NOT self-contained: Minecraft keeps inheriting
    the parent's display transforms and, on NeoForge, its root "transform". Returning
    such a child early made the offline preview ignore a parent root transform that
    the game applies, so proxy icons carrying a block parent were drawn 16 units away
    from what the player actually sees.
    """
    visited = visited or set()
    path = path.resolve()
    if path in visited or not path.is_file():
        return None
    visited.add(path)
    model = json.loads(path.read_text(encoding="utf-8"))
    parent = model.get("parent")
    inherited = None
    if parent:
        parent_path = resolve_model(parent, assets_root, mod_id)
        if parent_path:
            inherited = load_model_with_parent(parent_path, assets_root, mod_id, visited)

    if inherited is None:
        return model if model.get("elements") else None

    merged = deepcopy(inherited)
    merged.update({key: value for key, value in model.items() if key not in ("textures", "display")})
    merged["elements"] = model.get("elements") or inherited.get("elements", [])
    merged["textures"] = {**inherited.get("textures", {}), **model.get("textures", {})}
    # ItemTransforms merge per context: the child's gui wins, the rest come from the parent.
    merged["display"] = {**inherited.get("display", {}), **model.get("display", {})}
    # A root transform is inherited whole; the child only overrides it by declaring one.
    if "transform" not in model and "transform" in inherited:
        merged["transform"] = inherited["transform"]
    return merged

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


def resolve_gui_sources(model_tree: dict, assets_root: Path, mod_id: str,
                        source_override: str | None = None) -> tuple[list, str, list[str]]:
    """Sources the GUI icon is built from: (sources, status, model_ids used).

    One resolution order for both the generator and the tuner preview, so the
    preview cannot drift from the shipped proxy:

    1. the models the GUI case actually references;
    2. the item's fallback model, because a GUI case can point at this item's own
       proxy and unwrapping that proxy lands on a geometry-less template such as
       minecraft:block/block (arch is one);
    3. an explicit source override;
    4. bake_root_sources applies the model's root transform, which the icon must
       show (three items were mismatching because this step was skipped).

    status is "ok" or the reason there is nothing to bake.
    """
    model = model_tree if isinstance(model_tree, dict) else {}
    if model.get("type") == "minecraft:select" and model.get("property") == "minecraft:display_context":
        gui_tree = next((case.get("model", {}) for case in model.get("cases", [])
                         if case.get("when") in ("gui", ["gui"])), {})
    else:
        gui_tree = model
    model_ids = collect_model_ids(gui_tree)
    sources = bake_root_sources(collect_model_sources(model_ids, assets_root, mod_id))
    if not sources:
        model_ids = list(dict.fromkeys(
            model_ids + collect_model_ids(model.get("fallback", {}))))
        sources = bake_root_sources(collect_model_sources(model_ids, assets_root, mod_id))
    if not sources:
        return [], "skipped_no_local_geometry", model_ids
    if source_override:
        model_ids = [source_override]
        sources = bake_root_sources(collect_model_sources(model_ids, assets_root, mod_id))
        if not sources:
            return [], "skipped_source_override", model_ids
    return sources, "ok", model_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="mod project root (default: detected project)")
    parser.add_argument("--apply", action="store_true", help="write GUI proxy models and item definitions")
    parser.add_argument("--items", default="", help="comma-separated item ids; default is all")
    parser.add_argument("--target-size", type=float, default=16.0,
                        help="maximum 3D model-space edge of each icon proxy (default: one vanilla block)")
    parser.add_argument("--report", type=Path, default=None, help="optional JSON audit report output")
    parser.add_argument("--mirror", action="store_true",
                        help="copy what this run rewrote into build/resources/main, where the preview client reads it")
    args = parser.parse_args()

    root = (args.root or Path.cwd()).resolve()
    config = resolve({"root": str(root)})
    mod_id = config.get("mod_id")
    if not mod_id:
        parser.error(f"could not detect mod id under {root}")
    assets_root = root / "src/main/resources/assets" / mod_id
    items_dir = assets_root / "items"
    requested = {part.strip() for part in args.items.split(",") if part.strip()}
    overrides = load_overrides(root)
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
        # Resolution order lives in resolve_gui_sources so the tuner preview walks the
        # exact same path (it used to raise "no GUI source geometry" on arch, whose
        # GUI proxy unwraps to the geometry-less minecraft:block/block template).
        source_override = overrides.get(item_id, {}).get("source")
        model_sources, source_status, model_ids = resolve_gui_sources(
            original_tree, assets_root, mod_id, source_override)
        if not model_sources:
            report.append({"item": item_id, "status": source_status, "models": model_ids})
            continue

        all_elements = [deepcopy(element) for _ref, _source, model, _path in model_sources
                        for element in model.get("elements", [])]
        shared_bounds = geometry_bounds({"elements": all_elements})
        if shared_bounds is None:
            report.append({"item": item_id, "status": "skipped_no_geometry", "models": model_ids})
            continue
        # 该 item 的原始最长 AABB 边(游戏单位)决定它的真实尺寸档位：
        # >=1 格贴满原版边缘，<1 格按真实比例缩小，不被 inflate 到满格。
        source_longest = max(shared_bounds[i + 3] - shared_bounds[i] for i in range(3))
        item_target_px = gui_icon_target_px(source_longest)
        # Art-direction overrides: size, anchor, yaw and screen offset. Inferred
        # from the override file (empty for items nobody tuned), so the automatic
        # pipeline is unchanged for every other item.
        params = effective_params(item_id, {"target_px": item_target_px}, overrides)
        item_target_px = params["target_px"]
        anchor_override = overrides.get(item_id, {}).get("anchor", "auto")
        yaw_override, offset_x, offset_y = params["yaw"], params["offset_x"], params["offset_y"]
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
            # 额外朝向是**相机旋转**，不是几何旋转：轴对齐 box 只能靠 from/to 表达，
            # 把角点各自绕 Y 转任意角度就不再是那个 box——模型被压扁/翻倒/解体正是这么来的。
            # 所以把 yaw 写进 proxy 的 display.gui.rotation，几何只缩放+平移，游戏看到的就是这一视角。
            gui_rotation = yaw_gui_rotation(yaw_override, VANILLA_BLOCK_GUI["rotation"])
            # normalize_to_block puts every source into the same 3D one-block
            # space; fit_gui_projection then corrects for what the 30-degree GUI
            # camera actually shows (flat, tall and asymmetric shapes all differ
            # from their AABB). A shape that cannot be fitted is skipped instead
            # of shipping a known-bad icon.
            # 先居中 fit 一次，量出图标在槽里真正占的可见高度。没占满上下边缘的
            # 模型(矮物件、宽扁伞面、床头等)悬在槽中会显得突兀，按原版地毯的
            # 做法把可见下边缘贴到槽底。判据用渲染后的投影高度，不用源模型尺寸
            # ——遮阳伞源高18u但投影只有8.8px，正是后一种判据才抓得住。
            centred = fit_gui_projection(proxy, lambda ref: resolve_texture(root, ref),
                                         target_px=item_target_px, floor_anchor=False,
                                         gui_rotation=gui_rotation)
            if not centred:
                report.append({"item": item_id, "status": "skipped_gui_fit", "models": [source_id]})
                continue
            # 关心的是屏幕竖直方向占槽多少(fit_projected_size[1]), 不是长边——
            # 遮阳伞的宽度被 fit 到 15.7px, 但投影高度只有 8.8px。
            proj_h = centred["fit_projected_size"][1]
            floor_anchor = proj_h < GUI_ICON_TARGET_PX * 0.95
            if anchor_override == "floor":
                floor_anchor = True
            elif anchor_override == "center":
                floor_anchor = False
            if floor_anchor:
                fitted = fit_gui_projection(proxy, lambda ref: resolve_texture(root, ref),
                                            target_px=item_target_px, floor_anchor=True,
                                            gui_rotation=gui_rotation)
                if not fitted:
                    fitted = centred
            else:
                fitted = centred
            proxy = fitted["model"]
            # Screen-pixel offset is the last step: convert it back into a geometry
            # translation so display.gui keeps the vanilla camera. The tuner and the
            # generator use the same icon_overrides.apply_screen_offset helper.
            if offset_x or offset_y:
                shifted = apply_screen_offset(proxy, lambda ref: resolve_texture(root, ref),
                                              offset_x, offset_y, VANILLA_BLOCK_GUI["scale"][0],
                                              gui_rotation=gui_rotation)
                if shifted is not None:
                    proxy = shifted
                else:
                    report.append({"item": item_id, "status": "skipped_offset", "models": [source_id]})
            normalized["gui_fit"] = fitted
            # A baked root transform must not be inherited again from the source model.
            if proxy.pop("__root_baked__", None):
                proxy["parent"] = "minecraft:block/block"
            else:
                proxy["parent"] = source_id
            proxy_path = assets_root / "models" / "item_icons" / item_id / f"variant_{variant_index}.json"
            replacements[referenced_id] = proxy_model_id
            normalized_variants.append((proxy_path, proxy, normalized, source_id, proxy_model_id))

        if not normalized_variants:
            report.append({"item": item_id, "status": "skipped_gui_fit_all", "models": model_ids})
            continue

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
                "source_longest": round(source_longest, 4),
                "source_height": round(shared_bounds[4] - shared_bounds[1], 4),
                "gui_target_px": item_target_px,
                "floor_anchor": floor_anchor,
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
            "source_longest": round(source_longest, 4),
            "source_height": round(shared_bounds[4] - shared_bounds[1], 4),
            "gui_target_px": item_target_px,
            "floor_anchor": floor_anchor,
            # Effective art-direction params, so the validator checks against
            # what the tuner actually asked for instead of assuming slot centre.
            "offset_x": offset_x,
            "offset_y": offset_y,
            "yaw": yaw_override,
            "source_override": source_override or None,
            "overridden": params["overridden"],
        }

    if args.apply:
        for path, model in proxy_updates.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        for path, definition in item_updates.items():
            path.write_text(json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
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
        if args.mirror:
            # The preview client runs from build/resources/main, so a proxy that only exists under
            # src keeps rendering the previous sheet until something else writes the mirror. That
            # is exactly how an item icon kept an old lamp_shell while the hand copy moved on.
            for path in list(proxy_updates) + list(item_updates):
                mirror_path(root, path)

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
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Audited {len(report)} items; {len(proxy_updates)} GUI-only proxy models; "
          f"mode={'apply' if args.apply else 'dry_run'}. "
          "Every proxy uses minecraft:block/block's GUI display: rotation [30, 225, 0], no translation, scale 0.625.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())