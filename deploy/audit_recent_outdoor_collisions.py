#!/usr/bin/env python3
"""Audit the seven outdoor models against their declared Java collision shapes.

The profile file records intentional exclusions (planter foliage, zero-thickness
canopy fabric) and multiblock layers so the geometry tool can compare the same
physical parts that the game collision shapes are meant to represent.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collision"))
from audit_java_shapes import read_shape
from parse_model import cube_aabb, filter_collision_cubes, load_cubes
from run import clip_cubes_to_bounds, deploy_collision, measure_collision
from generate import merge_exact_union_boxes, to_java


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "src/main/resources/assets/pastoral_home/models/block"


def parse_indices(profile):
    values = profile.get("include_indices")
    return None if values is None else set(int(value) for value in values)


def filtered_cubes(model_path: Path, profile: dict):
    cubes = load_cubes(str(model_path))
    included = parse_indices(profile)
    if included is not None:
        cubes = [cube for cube in cubes if cube.get("index") in included]
    excluded = set(profile.get("exclude_indices", []))
    cubes = [cube for cube in cubes if cube.get("index") not in excluded]
    cubes, _skipped = filter_collision_cubes(cubes, include_thin=profile.get("include_thin", False))
    if profile.get("clip_bounds"):
        bounds = {"xyz".index(axis): (float(interval[0]), float(interval[1]))
                  for axis, interval in profile["clip_bounds"].items()}
        cubes = clip_cubes_to_bounds(cubes, bounds)
    return cubes


def combined_variant_model(paths: list[Path], destination: Path) -> Path:
    models = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    combined = dict(models[0])
    combined["elements"] = [element for model in models for element in model.get("elements", [])]
    destination.write_text(json.dumps(combined, ensure_ascii=False), encoding="utf-8")
    return destination


def aggregate_metrics(metric_rows):
    totals = Counter()
    for metrics in metric_rows:
        for key in ("render_voxels", "collision_voxels", "air_voxels", "miss_voxels", "coverage_voxels"):
            if key in metrics:
                totals[key] += metrics[key]
    rendered = totals["render_voxels"]
    collided = totals["collision_voxels"]
    overlap = rendered - totals["miss_voxels"]
    return {
        **totals,
        "air_percent": 100.0 * totals["air_voxels"] / rendered if rendered else 0.0,
        "miss_percent": 100.0 * totals["miss_voxels"] / rendered if rendered else 0.0,
        "coverage_percent": 100.0 * overlap / rendered if rendered else 0.0,
        "precision_percent": 100.0 * overlap / collided if collided else 0.0,
    }


def clipped_layer(cubes, interval, y_offset):
    low, high = interval
    clipped = clip_cubes_to_bounds(cubes, {1: (float(low), float(high))})
    for cube in clipped:
        cube["from"][1] -= y_offset
        cube["to"][1] -= y_offset
    return clipped


def current_shapes(profile, java_path):
    if profile["mode"] == "single_block":
        return [(profile["shape"], read_shape(java_path, profile["shape"]))]
    if profile["mode"] == "layers":
        return [(layer["shape"], read_shape(java_path, layer["shape"])) for layer in profile["layers"]]
    return []


def probe_shape(boxes, point):
    return any(box[0] <= point[0] <= box[3] and box[1] <= point[1] <= box[4]
               and box[2] <= point[2] <= box[5] for box in boxes)


def audit_profile(profile, resolution: int, temp_dir: Path):
    model_paths = [MODEL_DIR / name for name in profile["models"]]
    java_path = ROOT / profile["java"]
    mode = profile["mode"]
    if mode == "manual_probes":
        boxes = read_shape(java_path, profile["shape"])
        probes = []
        for probe in profile.get("probes", []):
            actual = probe_shape(boxes, tuple(float(value) for value in probe["point"]))
            probes.append({**probe, "actual_collides": actual,
                           "pass": actual == bool(probe["collides"])})
        max_boxes = int(profile.get("max_shape_boxes", len(boxes)))
        return {"id": profile["id"], "mode": mode,
                "pass": len(boxes) <= max_boxes and all(row["pass"] for row in probes),
                "shape_boxes": len(boxes), "max_shape_boxes": max_boxes,
                "probes": probes,
                "detail": "Manual probes verify intentional hollow or selectively collidable geometry."}
    if mode == "no_collision":
        source = java_path.read_text(encoding="utf-8")
        ok = "return Shapes.empty();" in source
        result = {"id": profile["id"], "mode": mode, "pass": ok,
                  "detail": "collision intentionally empty" if ok else "collision is not Shapes.empty()"}
        if profile.get("selection_shape"):
            selection = read_shape(java_path, profile["selection_shape"])
            selection_rows = []
            for model_path in model_paths:
                cubes = load_cubes(str(model_path))
                cubes, _skipped = filter_collision_cubes(cubes, include_thin=profile.get("include_thin", False))
                selection_rows.append(measure_collision(cubes, selection, resolution))
            selection_metrics = aggregate_metrics(selection_rows)
            miss_limit = float(profile.get("max_selection_miss_percent", 0.0))
            result["selection"] = {
                "shape_boxes": len(selection), "metrics": selection_metrics,
                "max_miss_percent": miss_limit,
            }
            result["pass"] = result["pass"] and selection_metrics["miss_percent"] <= miss_limit
        return result

    selected_by_model = [filtered_cubes(path, profile) for path in model_paths]
    current_rows = []
    candidate_rows = []
    candidate_boxes_by_shape = {}

    if mode == "single_block":
        current_boxes = read_shape(java_path, profile["shape"])
        for cubes in selected_by_model:
            current_rows.append(measure_collision(cubes, current_boxes, resolution))

        collision_groups = profile.get("collision_groups")
        if len(model_paths) == 1 or collision_groups:
            candidate_paths = model_paths
        else:
            candidate_path = combined_variant_model(model_paths, temp_dir / f"{profile['id']}_states.json")
            candidate_paths = [candidate_path]
        generated = []
        for candidate_path in candidate_paths:
            candidate = deploy_collision(
                str(candidate_path), res=resolution,
                include_indices=profile.get("include_indices") if candidate_path in model_paths else None,
                collision_groups=collision_groups,
                clip_bounds=({"xyz".index(axis): tuple(interval)
                              for axis, interval in profile["clip_bounds"].items()}
                             if profile.get("clip_bounds") else None),
                single_block=True,
            )
            generated.extend(candidate["boxes"])
        candidate_boxes = merge_exact_union_boxes(generated)
        candidate_boxes_by_shape[profile["shape"]] = candidate_boxes
        for cubes in selected_by_model:
            candidate_rows.append(measure_collision(cubes, candidate_boxes, resolution))
    else:
        for layer in profile["layers"]:
            interval = tuple(layer["model_y"])
            offset = float(layer["offset_y"])
            local_model_layers = [clipped_layer(cubes, interval, offset) for cubes in selected_by_model]
            current_boxes = read_shape(java_path, layer["shape"])
            current_rows.extend(measure_collision(cubes, current_boxes, resolution)
                                for cubes in local_model_layers)

            clip_bounds = {1: interval}
            layer_groups = layer.get("collision_groups", profile.get("collision_groups"))
            if layer_groups:
                candidate_models = [deploy_collision(
                    str(path), res=resolution,
                    include_indices=profile.get("include_indices"),
                    collision_groups=layer_groups,
                    clip_bounds=clip_bounds, single_block=True,
                )["boxes"] for path in model_paths]
                candidate_boxes = merge_exact_union_boxes(
                    [box for boxes in candidate_models for box in boxes])
            else:
                candidate_models = []
                for model_index, path in enumerate(model_paths):
                    candidate_path = path
                    indices = profile.get("include_indices")
                    if len(model_paths) > 1:
                        if model_index == 0:
                            combined_path = combined_variant_model(
                                model_paths, temp_dir / f"{profile['id']}_states.json")
                        candidate_path = combined_path
                        indices = None
                        break
                    candidate_models.append(deploy_collision(
                        str(candidate_path), res=resolution, include_indices=indices,
                        clip_bounds=clip_bounds, single_block=True,
                    )["boxes"])
                if len(model_paths) > 1:
                    candidate_models = [deploy_collision(
                        str(combined_path), res=resolution, clip_bounds=clip_bounds,
                        single_block=True,
                    )["boxes"]]
                candidate_boxes = candidate_models[0] if candidate_models else []
            local_candidate = [
                (box[0], box[1] - offset, box[2], box[3], box[4] - offset, box[5])
                for box in candidate_boxes
            ]
            candidate_boxes_by_shape[layer["shape"]] = local_candidate
            for cubes in local_model_layers:
                candidate_rows.append(measure_collision(cubes, local_candidate, resolution))

    current = aggregate_metrics(current_rows)
    candidate = aggregate_metrics(candidate_rows)
    miss_limit = float(profile.get("max_miss_percent", 0.1))
    air_limit = float(profile.get("max_air_percent", 10.0))
    current_counts = {name: len(boxes) for name, boxes in current_shapes(profile, java_path)}
    max_boxes = profile.get("max_shape_boxes")
    box_count_ok = True
    if isinstance(max_boxes, dict):
        box_count_ok = all(current_counts.get(name, 0) <= int(limit) for name, limit in max_boxes.items())
    elif max_boxes is not None:
        box_count_ok = all(count <= int(max_boxes) for count in current_counts.values())
    passed = (current["miss_percent"] <= miss_limit and current["air_percent"] <= air_limit
              and box_count_ok)
    report = {
        "id": profile["id"], "mode": mode, "pass": passed,
        "limits": {"max_air_percent": air_limit, "max_miss_percent": miss_limit},
        "current": current, "tool_candidate": candidate,
        "current_shape_box_counts": current_counts,
        "max_shape_boxes": max_boxes,
        "candidate_box_counts": {name: len(boxes) for name, boxes in candidate_boxes_by_shape.items()},
        "candidate_java": {name: to_java(boxes) for name, boxes in candidate_boxes_by_shape.items()},
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path,
                        default=Path("tools/deploy/collision_profiles/recent_outdoor.json"))
    parser.add_argument("--report", type=Path, default=Path("build/recent_outdoor_collision_audit.json"))
    parser.add_argument("--res", type=int, default=None)
    args = parser.parse_args()
    profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    resolution = args.res or int(profile_data.get("resolution", 8))
    reports = []
    with tempfile.TemporaryDirectory(prefix="pastoral_collision_") as temp:
        temp_dir = Path(temp)
        for profile in profile_data["profiles"]:
            reports.append(audit_profile(profile, resolution, temp_dir))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = False
    for report in reports:
        if report["mode"] in ("no_collision", "manual_probes"):
            status = "PASS" if report["pass"] else "FAIL"
            summary = report["detail"]
            if report["mode"] == "manual_probes":
                summary += f" boxes={report['shape_boxes']}; probes=" + ", ".join(
                    f"{probe['label']}:{'hit' if probe['actual_collides'] else 'open'}"
                    for probe in report["probes"])
            print(f"{status} {report['id']}: {summary}")
            failed |= not report["pass"]
            continue
        cur, cand = report["current"], report["tool_candidate"]
        status = "PASS" if report["pass"] else "NEEDS_REPAIR"
        print(f"{status} {report['id']}: current={report['current_shape_box_counts']}, "
              f"air={cur['air_percent']:.2f}%, miss={cur['miss_percent']:.2f}%; "
              f"tool={report['candidate_box_counts']}, "
              f"air={cand['air_percent']:.2f}%, miss={cand['miss_percent']:.2f}%")
        failed |= not report["pass"]
    print(f"Detailed current/candidate boxes: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
