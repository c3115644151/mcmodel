#!/usr/bin/env python3
"""Sweep one generator constant across values and produce a labelled comparison sheet.

Written because the alpha sweep for the party light - 100 / 140 / 180, decide by looking - was done
with an ad-hoc PowerShell loop that took three attempts to get right: the first died on JSON quoting
inside a .ps1 file, the second wrote screenshot paths through a Chinese directory name that
PowerShell 5.1 mangled from UTF-8 into mojibake (ENOENT), and both could hand back a frame of the
loading overlay as if it were the world.

So the rules are baked in here:

* paths never pass through a shell, and no command line carries a non-ASCII literal;
* every shot goes through live_capture, which reloads, waits, measures the frame and refuses an
  overlay instead of silently returning one;
* the source file is restored and regenerated at the end, so a sweep never leaves the tree on the
  last value it happened to try.

  .venv/Scripts/python.exe tools/deploy/param_sweep.py \
      --file tools/deploy/prepare_party_lights_models.py --param SHELL_ALPHA --values 100,140,180 \
      --generator "tools/deploy/prepare_party_lights_models.py|--mirror" \
      --crop 725,372,812,462 --out build/pl/alpha_sweep.png \
      --baseline build/blockbench_source_previews/party_lights.png
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_capture

PYTHON = ROOT / ".venv/Scripts/python.exe"


def regenerate(generator: str) -> None:
    # Arguments are split on '|' rather than on whitespace: the generator needs its own flags
    # (--mirror), and argparse would otherwise swallow them as options of this script.
    result = subprocess.run([str(PYTHON)] + generator.split("|"), cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("generator failed:\n" + (result.stdout + result.stderr)[-900:])


def place_scene(scene: Path) -> None:
    """Run a placement script so every frame in the sheet shows the same subject from the same camera."""
    payload = ROOT / "build/param_sweep_scene.json"
    payload.write_text(json.dumps({"code": scene.read_text(encoding="utf-8")}), encoding="utf-8")
    code, out, err = live_capture.call_tool("run_script", "@build/param_sweep_scene.json", timeout=180)
    if code != 0:
        raise SystemExit("scene script failed:\n" + (out or err)[-900:])
    print("scene placed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="generator source whose constant is swept")
    parser.add_argument("--param", required=True)
    parser.add_argument("--values", required=True, help="comma separated")
    parser.add_argument("--generator", required=True,
                        help="script and flags separated by '|', e.g. tools/deploy/x.py|--mirror")
    parser.add_argument("--crop", required=True, help="x0,y0,x1,y1 window inside each shot")
    parser.add_argument("--out", required=True)
    parser.add_argument("--zoom", type=int, default=6)
    parser.add_argument("--height", type=int, default=520)
    parser.add_argument("--baseline", default=None, help="reference picture placed on the left")
    parser.add_argument("--settle", type=float, default=25.0)
    parser.add_argument("--scene", default=None,
                        help="run_script body that places the subject and the camera before every shot; "
                             "without it the sweep photographs whatever the player last looked at")
    args = parser.parse_args()

    source = Path(args.file)
    original = source.read_text(encoding="utf-8")
    pattern = re.compile(rf"({re.escape(args.param)}\s*=\s*)[^\n#]+")
    if not pattern.search(original):
        raise SystemExit(f"{args.param} not found in {source}")

    box = tuple(int(value) for value in args.crop.split(","))
    shots: list[tuple[str, Image.Image]] = []
    try:
        for value in [item.strip() for item in args.values.split(",") if item.strip()]:
            source.write_text(pattern.sub(rf"\g<1>{value}", original, count=1), encoding="utf-8")
            regenerate(args.generator)
            if args.scene:
                place_scene(Path(args.scene))
            live_capture.wait_in_world(120.0)
            live_capture.reload_resources("pastoral_home_preview reload", args.settle)
            live_capture.wait_in_world(120.0)
            shot = ROOT / f"build/shots/sweep_{args.param}_{value}.png"
            live_capture.shoot(shot)
            report = live_capture.frame_report(Image.open(shot))
            if report["looks_like_loading_overlay"]:
                raise SystemExit(f"{args.param}={value}: frame looked like the loading overlay, refusing to compare")
            crop = Image.open(shot).convert("RGB").crop(box)
            print(f"{args.param}={value}: top colour {report['top'][0][1]}% rgb{tuple(report['top'][0][0])}")
            shots.append((f"{args.param}={value}", crop))
    finally:
        source.write_text(original, encoding="utf-8")
        regenerate(args.generator)
        print(f"restored {source.name} and regenerated")

    parts: list[Image.Image] = []
    labels: list[str] = []
    if args.baseline:
        base = Image.open(args.baseline).convert("RGB")
        base = base.crop((0, 0, base.width // 2, base.height))
        parts.append(base)
        labels.append(Path(args.baseline).stem)
    for label, crop in shots:
        parts.append(crop)
        labels.append(label)

    scaled = [part.resize((max(1, int(part.width * args.height / part.height)), args.height), Image.NEAREST)
              for part in parts]
    gap = 16
    width = sum(part.width for part in scaled) + gap * (len(scaled) - 1)
    sheet = Image.new("RGB", (width, args.height), (18, 18, 20))
    x = 0
    for part in scaled:
        sheet.paste(part, (x, 0))
        x += part.width + gap
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out} {sheet.width}x{sheet.height}: " + " | ".join(labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
