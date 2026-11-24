#!/usr/bin/env python3
"""Take an in-game screenshot that is guaranteed to show the world, then report what is in it.

Why this exists: on 2026-11-25 a reload of the party-lights model was verified four times by
screenshotting straight after pastoral_home_preview reload. Each frame was the loading overlay
(screen-sized brick texture, MOJANG STUDIOS in the middle, leftover HUD), not the world. Read as
"the client did not reload my textures", that cost four wrong hypotheses and one wrong rollback -
while the textures had reloaded correctly every single time.

get_screen alone does not catch it: the overlay is not a Screen object, so the bridge keeps
answering {"inWorld": true, "screen": "none"}. The only reliable signal is the frame itself:

* an overlay is a flat poster - one quantised colour owns >55% of the frame and that colour is
  brick red (R well above G and B);
* a world frame mixes terrain, sky and the model - the top colour rarely passes 45% and row-to-row
  brightness variance stays low.

So this tool shoots, measures, and refuses to hand back a picture it does not believe. It also
prints the colour mix, because a thumbnail cannot be trusted either: this session read two lamps
standing side by side as one lamp, twice, and read a lit core as a texture highlight, three times.

  .venv/Scripts/python.exe tools/deploy/live_capture.py --out build/shots/x.png --reload
  .venv/Scripts/python.exe tools/deploy/live_capture.py --out build/shots/x.png --crop 725,372,812,462 --zoom 7
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CALL_TOOL = ROOT / "tools/mcpfabric/call-tool.mjs"


def call_tool(name: str, arguments: str = "{}", timeout: int = 60) -> tuple[int, str, str]:
    """Run one bridge tool. The bridge prints a handshake JSON on stderr, so stdout must stay alone:
    merging the two streams makes every JSON parse fail and every state read look empty."""
    result = subprocess.run(
        ["node", str(CALL_TOOL), name, arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, (result.stdout or ""), (result.stderr or "")


def json_payload(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def reload_resources(command: str, settle: float) -> None:
    """Run the project's resource reload and let the render thread finish rebuilding."""
    # run_script evals the payload as a function body with mc in scope; it is not a CommonJS
    # module, so a "module.exports = ..." wrapper fails with "ReferenceError: 'module' is not defined".
    script = "await mc.call(\"command.run\", { command: " + json.dumps(command) + " });"
    payload = {"code": script}
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "reload.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        code, out, err = call_tool("run_script", "@" + str(path), timeout=90)
    if code != 0:
        raise SystemExit("reload script failed:\n" + (out + err)[-800:])
    print(f"reload sent; settling {settle:.0f}s")
    time.sleep(settle)


def place_scene(scene: Path) -> None:
    """Run a placement script so the shot frames a known subject instead of where the player happens to be."""
    payload = ROOT / "build/live_capture_scene.json"
    payload.write_text(json.dumps({"code": scene.read_text(encoding="utf-8")}), encoding="utf-8")
    code, out, err = call_tool("run_script", "@build/live_capture_scene.json", timeout=180)
    if code != 0:
        raise SystemExit("scene script failed:\n" + (out or err)[-900:])
    print("scene placed")


def wait_in_world(deadline_seconds: float) -> dict:
    """Poll get_screen until the client reports an unpaused world."""
    deadline = time.time() + deadline_seconds
    last: dict = {}
    closed = False
    while time.time() < deadline:
        code, out, err = call_tool("get_screen")
        data = json_payload(out).get("data") or {}
        if data:
            last = data
            if data.get("inWorld") and data.get("screen") == "none" and not data.get("paused"):
                return data
            # Creative inventory and container screens open by themselves after a teleport or reload;
            # leaving one up puts the shot inside a GUI instead of the world.
            if data.get("screen") not in (None, "none") and not closed:
                call_tool("close_screen")
                closed = True
        time.sleep(1.0)
    raise SystemExit(f"client never reached an unpaused world in {deadline_seconds:.0f}s: {last}")


def shoot(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["MCPFABRIC_IMAGE_OUT"] = str(out)
    result = subprocess.run(
        ["node", str(CALL_TOOL), "screenshot"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, env=env,
    )
    if not out.exists():
        raise SystemExit("screenshot failed:\n" + result.stdout + "\n" + result.stderr)
    return out


def frame_report(image: Image.Image) -> dict:
    array = np.array(image.convert("RGB")).astype(int)
    quantised = ((array // 32) * 32).reshape(-1, 3)
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    order = np.argsort(-counts)
    total = quantised.shape[0]
    top = [(tuple(int(v) for v in colours[i]), 100.0 * counts[i] / total) for i in order[:6]]
    row_variance = float(array.std(axis=(1, 2)).mean())
    cloud_share = top[0][1]
    red, green, blue = top[0][0]
    brick = red > 120 and red > 1.5 * green + 20 and red > 1.5 * blue + 20
    overlay = cloud_share > 55.0 and (brick or row_variance > 45.0)
    return {
        "top_colour_share": round(cloud_share, 1),
        "row_variance": round(row_variance, 1),
        "looks_like_loading_overlay": bool(overlay),
        "top": [(list(colour), round(share, 1)) for colour, share in top],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--reload", action="store_true", help="send the resource reload first")
    parser.add_argument("--reload-command", default="pastoral_home_preview reload")
    parser.add_argument("--settle", type=float, default=25.0, help="seconds to let the render thread rebuild")
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for an unpaused world")
    parser.add_argument("--crop", default=None, help="x0,y0,x1,y1 to crop and save next to the shot")
    parser.add_argument("--zoom", type=int, default=1)
    parser.add_argument("--retry", type=int, default=3, help="reshoots when the frame looks like an overlay")
    parser.add_argument("--scene", default=None,
                        help="run_script body to place the subject and camera before the shot")
    args = parser.parse_args()

    if args.scene:
        place_scene(Path(args.scene))
    wait_in_world(args.wait)
    if args.reload:
        reload_resources(args.reload_command, args.settle)
        wait_in_world(args.wait)

    out = Path(args.out)
    report: dict = {}
    for attempt in range(1, args.retry + 1):
        shoot(out)
        report = frame_report(Image.open(out))
        if not report["looks_like_loading_overlay"]:
            break
        print(f"attempt {attempt}: frame looks like the loading overlay, waiting 15s and reshooting")
        time.sleep(15.0)
    else:
        print(json.dumps(report, indent=2))
        raise SystemExit("gave up: every frame looked like a loading overlay")

    print(f"wrote {out}")
    print(json.dumps(report, indent=2))

    if args.crop:
        left, upper, right, lower = (int(value) for value in args.crop.split(","))
        crop = Image.open(out).convert("RGB").crop((left, upper, right, lower))
        if args.zoom > 1:
            crop = crop.resize((crop.width * args.zoom, crop.height * args.zoom), Image.NEAREST)
        crop_path = out.with_name(out.stem + "_crop.png")
        crop.save(crop_path)
        crop_report = frame_report(crop)
        print(f"\ncrop {crop_path.name} {crop.width}x{crop.height}")
        print("  colour mix: " + ", ".join(
            f"{share}% rgb{tuple(colour)}" for colour, share in crop_report["top"][:4]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
