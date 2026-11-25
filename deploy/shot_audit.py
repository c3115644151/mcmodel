#!/usr/bin/env python
"""Judge a scene_probe screenshot on its own pixels.

The crop is not a guess and not a hand-tuned rectangle: the probe recorded which block was shot and
what state the world holds, and frame_box.py turns that state into the blockstate variant, the model
and the element boxes, so the pixel box is the box the model really covers. A shot whose box is
mostly sky fails, which is the failure that used to pass as "the model does not render".
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import frame_box  # noqa: E402

SKY = "sky"


def classify(pixel):
    r, g, b = pixel[:3]
    if b > r + 18 and b > g + 8 and b > 90:
        return SKY
    if r > b + 60 and r > 150 and g > 100:
        return "amber" if g < 190 else "cream"
    if abs(r - g) < 26 and abs(g - b) < 26:
        return "grey"
    return "other"


def census(keys):
    total = len(keys) or 1
    counts = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return {key: round(100.0 * value / total, 1)
            for key, value in sorted(counts.items(), key=lambda kv: -kv[1])}


def class_map(image):
    data = image.convert("RGB").tobytes()
    return [classify(data[i:i + 3]) for i in range(0, len(data), 3)]


def subject_box(shot, report):
    """Pixel box of the placed model: state -> variant -> elements -> projection."""
    position = shot.get("subject") or []
    if not position:
        return None, "no-subject"
    position = position[0] if isinstance(position[0], list) else position
    state = ((report.get("blocks") or {}).get(",".join(str(v) for v in position)) or {})
    block = (state.get("value") or state) or {}
    block_id = block.get("id")
    if not block_id:
        return None, "no-world-state"
    try:
        box = frame_box.world_box(block_id, block.get("properties"), position)
    except (KeyError, FileNotFoundError):
        return None, "no-model"
    if box is None:
        return None, "no-variant"
    camera = shot.get("camera") or {}
    return frame_box.project(box[0], box[1], camera), None


def audit(report_path, min_painted=55.0, max_sky=30.0):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    rows, failed = [], 0
    for name, shot in (report.get("shots") or {}).items():
        path = ROOT / shot["out"]
        found, why = subject_box(shot, report)
        if found is None:
            rows.append((name, "-", "skip:" + why, {}, "SKIP"))
            continue
        image = Image.open(path)
        crop = image.crop(tuple(found["bbox"]))
        stem = Path(shot["out"]).with_name(Path(shot["out"]).stem + "_c.png")
        crop.save(ROOT / stem)
        numbers = census(class_map(crop))
        sky = numbers.get(SKY, 0.0)
        painted = 100.0 - sky
        ok = painted >= min_painted and sky <= max_sky
        verdict = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        rows.append((name, str([crop.width, crop.height]), str(stem).replace("\\", "/"),
                     dict(numbers, painted=round(painted, 1)), verdict))
    width = max(len(row[0]) for row in rows) if rows else 4
    for name, size, stem, numbers, verdict in rows:
        print(name.ljust(width), size.rjust(11), verdict.ljust(5), stem, json.dumps(numbers, ensure_ascii=False))
    print(str(len(rows) - failed) + " of " + str(len(rows)) + " shots framed the subject")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: shot_audit.py build/probes/<name>.json")
        raise SystemExit(2)
    raise SystemExit(audit(sys.argv[1]))
