"""One entry for every model question in this project.

usage: python tools/deploy/model.py <verb> [options]

verbs
  doctor      environment and drift check; run it first when a tool behaves oddly
  preview     offline render of shipped models or a raw .bbmodel (numbers first, image second)
  compare     source .bbmodel and shipped model through one camera, plus a difference table
  export      authoritative conversion: Blockbench's own java_block export of a .bbmodel
  viewport    the Blockbench viewport of a .bbmodel, i.e. the only accepted visual baseline
  live        in-game sample: optional reload, stage the scene, shoot, crop, colour census
  gate        source-difference gates (per piece, or every registered piece)
  ship        the whole loop in one command: generate -> gate -> reload -> shoot -> census

Nothing else in tools/deploy is meant to be called by hand. preview_block_model.py stays as the
drawing kernel that this entry and the generators import; every other preview/compare/census
script was folded in here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = Path(__file__).resolve().parent
sys.path.insert(0, str(DEPLOY))
import preview_block_model as pv  # noqa: E402

PY = sys.executable
NODE = "node"

# One registry, ordered by what each piece needs to go from .bbmodel to a verdict. A piece that is
# not here has no pipeline yet: ship and gate refuse instead of guessing.
PIECES = {
    "party_lights": {
        "source": "tools/deploy/model_sources/party_lights/party_lights.bbmodel",
        "generator": "prepare_party_lights_models.py",
        "gate": "party_lights_report.py",
        "job": "build/probes/jobs/lamp_frost2.json",
        "crop": (860, 380, 1060, 700),
        "model": "party_lights_lit",
        "frame": 2,
        # The GUI icon is a separate generated artifact (a proxy under models/item_icons) and it
        # reads the item copy's own sheet, so regenerating the piece has to refresh it too.
        "item": "party_lights",
    },
}

GATES_ALWAYS = ("audit_model_uv_sources.py", "audit_model_render_semantics.py")


def say(tag: str, text: str) -> None:
    print("[" + tag + "] " + text, flush=True)


def run(cmd, cwd=None, quiet=False) -> int:
    proc = subprocess.run([str(part) for part in cmd], cwd=str(cwd or ROOT))
    return proc.returncode


def regenerate(spec: dict) -> int:
    """Rebuild everything a piece ships: the block/item models, then the GUI icon proxy on top."""
    code = run([PY, str(DEPLOY / spec["generator"]), "--mirror"])
    if code != 0:
        return code
    if spec.get("item"):
        return run([PY, str(DEPLOY / "normalize_item_icons.py"), "--apply",
                    "--items", spec["item"], "--mirror"])
    return 0


def piece_or_die(name: str) -> dict:
    if name not in PIECES:
        raise SystemExit("[pieces] " + name + " has no pipeline; registered: "
                         + ", ".join(sorted(PIECES)))
    return PIECES[name]


# ---------------------------------------------------------------- numbers before pictures

def corner_colour(image) -> tuple:
    """The viewport and the world both paint a flat backdrop; it must not enter the census."""
    pixel = image.convert("RGBA").getpixel((0, 0))
    return tuple(pixel)


def census(image, crop=None, background=None) -> dict:
    """Share of the drawn pixels that read amber / cream / grey, plus how much is drawn.

    Amber-dominant means the paper cage covers the bulb; cream-dominant means the cage is too
    transparent. This table, not the picture, is what decides whether a change moved anything.
    """
    import numpy as np

    if crop:
        image = image.crop(crop)
    pixels = np.asarray(image.convert("RGBA"), dtype=np.float64)
    painted = pixels[..., 3] > 127.5
    if background is not None:
        near = np.abs(pixels[..., :3] - np.array(background[:3])).sum(axis=2) < 30
        painted = painted & ~near
    if not painted.any():
        return {"painted": 0.0}
    rgb = pixels[painted][:, :3]
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    amber = (r > g) & (g > b) & (r - b > 60)
    cream = (r > 190) & (g > 180) & (b > 120) & (np.abs(r - g) < 60)
    grey = (np.abs(r - g) < 30) & (np.abs(g - b) < 30)
    total = float(rgb.shape[0])
    return {"painted": 100.0 * painted.sum() / painted.size,
            "amber": 100.0 * amber.sum() / total,
            "cream": 100.0 * cream.sum() / total,
            "grey": 100.0 * grey.sum() / total,
            "other": 100.0 * (~(amber | cream | grey)).sum() / total,
            "mean": tuple(float(v) for v in rgb.mean(axis=0))}


def describe(label: str, numbers: dict) -> str:
    parts = [label]
    for key in ("painted", "amber", "cream", "grey", "other"):
        if key in numbers:
            parts.append(key + "=" + format(numbers[key], ".1f") + "%")
    if "mean" in numbers:
        parts.append("mean=(" + ",".join(format(v, ".0f") for v in numbers["mean"]) + ")")
    return "  ".join(parts)


# ---------------------------------------------------------------- vertex work

def source_quads(path: Path, frame: int, elements) -> list:
    if path.suffix.lower() == ".bbmodel":
        model, cache = pv.from_bbmodel(path, frame)
    else:
        model, cache = json.loads(path.read_text(encoding="utf-8")), None
    quads = pv.collect_model(model, (0.0, 0.0), 1.0, cache)
    if elements:
        quads = [quad for quad in quads if quad["element"] in elements]
    if not quads:
        raise SystemExit("[error] " + str(path) + " produced no drawable faces")
    return quads


def shipped_quads(names) -> list:
    """Names may carry a placement ("piano_l0_c1:16,0") so one picture can show several cells."""
    placements = []
    for entry in names:
        name, _, shift = entry.partition(":")
        dx, dy = (float(value) for value in shift.split(",")) if shift else (0.0, 0.0)
        placements.append((name.strip(), (dx, dy)))
    quads = pv.collect(placements, 1.0)
    if not quads:
        raise SystemExit("[error] shipped model produced no drawable faces")
    return quads


def parse_elements(text: str) -> set:
    return {int(value) for value in text.split(",") if value.strip()}


# ---------------------------------------------------------------- doctor

def alive(pid: int) -> bool:
    """tasklist reports 'no tasks' for a live java process inside this sandbox; ask the kernel."""
    import ctypes

    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def drift() -> None:
    """Assets under src must be mirrored into build/resources, or the client reloads stale files.

    Comparing only the newest mtime of each tree hides the expensive case: one file left behind while
    a sibling was rewritten. That is how the GUI icon kept the placed model's shell sheet after the
    item copy had already moved to its own translucent one, and no doctor line noticed. Compare every
    file instead, and name the first offenders.
    """
    src = ROOT / "src/main/resources/assets/pastoral_home"
    build = ROOT / "build/resources/main/assets/pastoral_home"
    if not src.is_dir() or not build.is_dir():
        say("doctor", "mirror: one side missing (src=" + str(src.is_dir()) + " build=" + str(build.is_dir()) + ")")
        return
    behind = []
    for file in sorted(src.rglob("*")):
        if not file.is_file():
            continue
        twin = build / file.relative_to(src)
        if not twin.is_file():
            behind.append((str(file.relative_to(ROOT)), "missing"))
            continue
        if file.read_bytes() != twin.read_bytes():
            behind.append((str(file.relative_to(ROOT)), "differs"))
    if behind:
        say("doctor", "mirror STALE: " + str(len(behind)) + " files behind, first "
            + ", ".join(name for name, _why in behind[:3]) + " - regenerate with --mirror before reloading")
    else:
        say("doctor", "mirror ok (" + str(sum(1 for f in src.rglob('*') if f.is_file())) + " files byte-identical)")


def cmd_doctor(args) -> None:
    say("doctor", "python " + sys.version.split()[0] + " at " + PY)
    try:
        import PIL
        say("doctor", "Pillow " + PIL.__version__)
    except ImportError:
        say("doctor", "Pillow MISSING: install it into .venv")
    try:
        version = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip()
        say("doctor", "node " + (version or "?"))
    except OSError:
        say("doctor", "node MISSING: MCP bridges cannot run")
    say("doctor", "Blockbench MCP on 127.0.0.1:3000: "
        + ("up" if port_open() else "down (viewport/export need it)"))
    pid_file = ROOT / "run/mcpfabricPreview/mcpfabric-preview.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip() or 0)
        say("doctor", "preview client pid " + str(pid) + ": " + ("alive" if pid and alive(pid) else "gone"))
    else:
        say("doctor", "preview client: no pid file (start it with npm --prefix tools/mcpfabric run start-preview)")
    for name in GATES_ALWAYS:
        say("doctor", "audit " + name + ": " + ("present" if (DEPLOY / name).exists() else "MISSING"))
    for name, spec in PIECES.items():
        missing = [key for key in ("generator", "gate") if not (DEPLOY / spec[key]).exists()]
        missing += [key for key in ("source", "job") if not (ROOT / spec[key]).exists()]
        say("doctor", "piece " + name + ": " + ("ready" if not missing else "missing " + ", ".join(missing)))
    drift()


# ---------------------------------------------------------------- preview

def cmd_preview(args) -> None:
    if args.anim_frame is not None:
        pv.ANIM_FRAME = args.anim_frame
    if args.raw:
        source = Path(args.raw)
        source = source if source.is_absolute() else ROOT / source
        quads = source_quads(source, args.frame, parse_elements(args.elements or ""))
    else:
        if not args.names:
            raise SystemExit("[error] name a shipped model, or pass --raw PATH.bbmodel")
        quads = shipped_quads(args.names)
    width, height = (int(v) for v in args.size.lower().split("x"))
    background = (tuple(int(v) for v in args.bg.split(",")) + (255,)) if args.bg else (0, 0, 0, 0)
    out = Path(args.out) if args.out else ROOT / "build/modelkit/preview.png"
    out = out if out.is_absolute() else ROOT / out
    views = [name for name in (args.views or "front,quarter").split(",") if name.strip()]
    # --only narrows the framing target, not the drawing: fit and centre on the named parts.
    focus = quads
    if args.only:
        focus = [quad for quad in quads if str(quad.get("name", "")).startswith(args.only)]
        if not focus:
            raise SystemExit("[error] --only " + args.only + ": no element name starts with that")
    # One scale for every view, taken from the tightest one, or the wider views overflow.
    scale = min(pv.fit_scale(focus, *pv.VIEWS[name], width, height) for name in views)
    tiles = []
    for name in views:
        yaw, pitch = pv.VIEWS[name]
        tile = out.with_name(out.stem + "_" + name + ".png")
        # clay=None means textured; passing False would be read as a colour and draw the model black.
        image = pv.render(quads, tile, scale, yaw, pitch, width, height, background=background,
                          clay=pv.CLAY if args.clay else None, blend=not args.no_blend, focus=focus)
        print(pv.summarize(quads, image, "clay" if args.clay else "textured"))
        say("preview", describe(name, census(image)))
        tiles.append((name, image))
    from PIL import Image
    sheet = Image.new("RGBA", (width * len(tiles), height), background)
    for index, (name, image) in enumerate(tiles):
        sheet.paste(image, (index * width, 0))
        tile = out.with_name(out.stem + "_" + name + ".png")
        tile.unlink(missing_ok=True)
    sheet.save(out)
    say("preview", "wrote " + str(out.relative_to(ROOT)))


# ---------------------------------------------------------------- compare

def cmd_viewport(args) -> None:
    """Capture what Blockbench itself draws. Every other reference is a guess about this image."""
    source = Path(args.source)
    source = source if source.is_absolute() else (ROOT / source)
    if not source.exists():
        raise SystemExit("[error] no such source: " + str(source))
    out = Path(args.out) if args.out else ROOT / "build/blockbench_source_previews" / (source.stem + ".png")
    out = out if out.is_absolute() else ROOT / out
    if port_open() and not args.reuse:
        raise SystemExit("[error] Blockbench is already running with someone else's project. "
                         "Capture it with --reuse, or close it first: opening our file would "
                         "replace unsaved work.")
    if not port_open():
        exe = Path(os.environ["LOCALAPPDATA"]) / "Programs/Blockbench/Blockbench.exe"
        if not exe.exists():
            raise SystemExit("[error] Blockbench not installed at " + str(exe))
        say("viewport", "launching Blockbench on " + source.name)
        subprocess.Popen([str(exe), str(source)])
        import time
        for _ in range(60):
            if port_open():
                break
            time.sleep(0.5)
        else:
            raise SystemExit("[error] Blockbench MCP did not come up on port 3000")
        if args.settle:
            time.sleep(args.settle)
    bb_call("capture_screenshot", {}, out)
    if not out.exists():
        raise SystemExit("[error] capture_screenshot returned no image")
    from PIL import Image
    image = Image.open(out).convert("RGBA")
    say("viewport", "wrote " + str(out.relative_to(ROOT)) + " " + str(image.size[0]) + "x" + str(image.size[1]))
    say("viewport", describe("body", census(image)))


def port_open() -> bool:
    """Blockbench's MCP plugin binds ::-only here, so probe both loopbacks, IPv6 first."""
    for family, host in ((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")):
        sock = socket.socket(family)
        sock.settimeout(0.4)
        reachable = sock.connect_ex((host, 3000)) == 0
        sock.close()
        if reachable:
            return True
    return False


def trim(image, background=(24, 26, 30)):
    """Crop to the drawn region so two images can be compared at the same scale."""
    import numpy as np
    box = image.convert("RGB").getbbox()
    if not box:
        return image
    return image.crop(box)


def cmd_compare(args) -> None:
    if args.piece:
        spec = piece_or_die(args.piece)
        args.source = args.source or spec["source"]
        args.model = args.model or spec["model"]
        if not args.frame:
            args.frame = spec["frame"]
        if args.anim_frame is None:
            args.anim_frame = spec["frame"]
    if args.viewport or args.live:
        if not (args.viewport and args.live):
            raise SystemExit("[error] image mode needs both --viewport and --live")
        from PIL import Image, ImageDraw
        reference = Image.open(ROOT / args.viewport if not Path(args.viewport).is_absolute() else args.viewport).convert("RGBA")
        actual = Image.open(ROOT / args.live if not Path(args.live).is_absolute() else args.live).convert("RGBA")
        if args.crop:
            actual = actual.crop(tuple(int(v) for v in args.crop.split(",")))
        reference, actual = trim(reference), trim(actual)
        height = args.height or 760
        reference = reference.resize((max(1, int(reference.width * height / reference.height)), height), Image.LANCZOS)
        actual = actual.resize((max(1, int(actual.width * height / actual.height)), height), Image.LANCZOS)
        out = Path(args.out) if args.out else ROOT / "build/modelkit/viewport_vs_live.png"
        out = out if out.is_absolute() else ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet = Image.new("RGBA", (reference.width + actual.width + 16, height), (24, 26, 30, 255))
        sheet.alpha_composite(reference, (0, 0))
        sheet.alpha_composite(actual, (reference.width + 16, 0))
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 6), "Blockbench viewport", fill=(255, 255, 255, 255))
        draw.text((reference.width + 24, 6), "in game", fill=(255, 255, 255, 255))
        sheet.save(out)
        say("compare", describe("viewport", census(reference, background=corner_colour(reference))))
        say("compare", describe("in game ", census(actual, background=corner_colour(actual))))
        say("compare", "wrote " + str(out.relative_to(ROOT)))
        return
    if args.anim_frame is not None:
        pv.ANIM_FRAME = args.anim_frame
    width, height = (int(v) for v in args.size.lower().split("x"))
    background = (tuple(int(v) for v in args.bg.split(",")) + (255,)) if args.bg else (0, 0, 0, 0)
    if not (args.source and args.model):
        raise SystemExit("[error] render mode needs --source and --model")
    source_path = Path(args.source)
    source_path = source_path if source_path.is_absolute() else ROOT / source_path
    yaw, pitch = pv.VIEWS[args.view]
    source = source_quads(source_path, args.frame, parse_elements(args.elements or ""))
    shipped = shipped_quads([args.model])
    union = source + shipped
    out = Path(args.out) if args.out else ROOT / "build/modelkit/compare.png"
    out = out if out.is_absolute() else ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.fit == "each":
        left = pv.render(source, out.parent / ".cmp_left.png",
                         pv.fit_scale(source, yaw, pitch, width, height), yaw, pitch, width, height,
                         background=background)
        right = pv.render(shipped, out.parent / ".cmp_right.png",
                          pv.fit_scale(shipped, yaw, pitch, width, height), yaw, pitch, width, height,
                          background=background)
    else:
        scale = pv.fit_scale(union, yaw, pitch, width, height)
        left = pv.render(source, out.parent / ".cmp_left.png", scale, yaw, pitch, width, height,
                         background=background, focus=union)
        right = pv.render(shipped, out.parent / ".cmp_right.png", scale, yaw, pitch, width, height,
                          background=background, focus=union)
    import numpy as np
    from PIL import Image, ImageDraw
    delta = np.abs(np.asarray(left, dtype=np.int16) - np.asarray(right, dtype=np.int16))
    changed = int((delta.sum(axis=2) > 0).sum())
    say("compare", describe("source ", census(left)))
    say("compare", describe("shipped", census(right)))
    say("compare", "pixels_changed=" + str(changed) + " of " + str(delta.shape[0] * delta.shape[1])
        + " max_channel_delta=" + str(int(delta.max())))
    sheet = Image.new("RGBA", (width * 2, height), (24, 26, 30, 255))
    sheet.alpha_composite(left, (0, 0))
    sheet.alpha_composite(right, (width, 0))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 6), "source", fill=(255, 255, 255, 255))
    draw.text((width + 8, 6), "shipped " + args.model, fill=(255, 255, 255, 255))
    sheet.save(out)
    for leftover in (".cmp_left.png", ".cmp_right.png"):
        (out.parent / leftover).unlink(missing_ok=True)
    say("compare", "wrote " + str(out.relative_to(ROOT)))


# ---------------------------------------------------------------- export

def bb_call(tool: str, payload: dict, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args_path = out_path.parent / (out_path.stem + ".args.json")
    args_path.write_text(json.dumps(payload), encoding="utf-8")
    # Absolute script path: the working directory is the bridge folder so node resolves its own
    # node_modules, and a relative script path would then resolve against that folder, not ROOT.
    code = run([NODE, str(ROOT / "tools/mcpfabric/bb_call.mjs"), tool, str(args_path), str(out_path)],
               cwd=ROOT / "tools/mcpfabric")
    if code != 0:
        raise SystemExit("[error] Blockbench MCP " + tool + " failed (is Blockbench running with the MCP plugin?)")
    return out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""


def first_json(text: str):
    """The export arrives wrapped in prose; take the first balanced object literal."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def model_diff(official: dict, shipped: dict) -> list:
    """What the generator does differently from Blockbench's own export, one line per difference."""
    lines = []
    want, have = official.get("elements", []), shipped.get("elements", [])
    if len(want) != len(have):
        lines.append("element count " + str(len(want)) + " vs " + str(len(have)))
    for index in range(min(len(want), len(have))):
        a, b = want[index], have[index]
        for key in ("from", "to"):
            if [round(v, 4) for v in a.get(key, [])] != [round(v, 4) for v in b.get(key, [])]:
                lines.append("element " + str(index) + " " + key + " " + str(a.get(key))
                             + " vs " + str(b.get(key)))
        for face, spec in (a.get("faces") or {}).items():
            other = (b.get("faces") or {}).get(face)
            if other is None:
                lines.append("element " + str(index) + " face " + face + " missing in shipped")
                continue
            if spec.get("uv") != other.get("uv"):
                lines.append("element " + str(index) + " face " + face + " uv "
                             + str(spec.get("uv")) + " vs " + str(other.get("uv")))
    return lines[:40]


def cmd_export(args) -> None:
    source = Path(args.source)
    source = source if source.is_absolute() else ROOT / source
    out_dir = Path(args.out) if args.out else ROOT / "build/native_export" / source.stem
    out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    text = bb_call("export_model", {"codec_id": "java_block"}, out_dir / "export.txt")
    official = first_json(text)
    if official is None:
        raise SystemExit("[error] no model json in the export; raw text is in "
                         + str((out_dir / "export.txt").relative_to(ROOT)))
    (out_dir / "model.json").write_text(json.dumps(official, indent=2), encoding="utf-8")
    say("export", "codec=java_block elements=" + str(len(official.get("elements", [])))
        + " textures=" + str(len(official.get("textures", {}))))
    say("export", "wrote " + str((out_dir / "model.json").relative_to(ROOT)))
    if args.textures:
        listing = bb_call("list_textures", {}, out_dir / "textures.txt")
        for entry in re.findall(r"\{[^}]*\}", listing):
            try:
                item = json.loads(entry)
            except json.JSONDecodeError:
                continue
            ident, name = str(item.get("id", "")), str(item.get("name", "tex"))
            if not ident:
                continue
            bb_call("get_texture", {"texture": ident}, out_dir / ("tex_" + name + ".png"))
            say("export", "texture " + name + " -> " + str((out_dir / ("tex_" + name + ".png")).relative_to(ROOT)))
    if args.model:
        shipped_path = ROOT / "src/main/resources/assets/pastoral_home/models/block" / (args.model + ".json")
        if not shipped_path.exists():
            shipped_path = ROOT / "build/resources/main/assets/pastoral_home/models/block" / (args.model + ".json")
        differences = model_diff(official, json.loads(shipped_path.read_text(encoding="utf-8")))
        if differences:
            say("export", "generator differs from the native export in " + str(len(differences)) + " places:")
            for line in differences:
                print("    " + line)
            say("export", "each line above must be a stated intent, not a surprise")
        else:
            say("export", args.model + " is byte-identical to the native export")


# ---------------------------------------------------------------- live

def sample(job_path: Path, crop, reload_first: bool) -> list:
    """Stage the scene, shoot every camera in the job, and return cropped images with numbers."""
    from PIL import Image

    if reload_first:
        run([NODE, "tools/mcpfabric/resource_reload.mjs"])
    run([NODE, "tools/mcpfabric/scene_probe.mjs", job_path])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    samples = []
    for shot in job.get("shots", []):
        out = ROOT / shot["out"]
        if not out.exists():
            say("live", "missing shot " + shot["out"])
            continue
        image = Image.open(out).convert("RGBA")
        if crop:
            image = image.crop(tuple(int(v) for v in crop))
            image.save(out.with_name(out.stem + "_c.png"))
        samples.append((Path(shot["out"]).name, image, census(image)))
    return samples


def cmd_live(args) -> None:
    spec = piece_or_die(args.piece) if args.piece else None
    job_path = Path(args.job) if args.job else (ROOT / spec["job"] if spec else None)
    if not job_path or not job_path.exists():
        raise SystemExit("[error] no job file; pass --job build/probes/jobs/<name>.json")
    crop = args.crop or (",".join(str(v) for v in spec["crop"]) if spec else None)
    for label, _image, numbers in sample(job_path, crop.split(",") if crop else None, args.reload):
        say("live", describe(label, numbers))


def cmd_sweep(args) -> None:
    """Vary one constant of a generator, rebuild, reload, shoot, and lay the takes side by side.

    Judging an alpha or an offset by editing the file three times is how a single variable turns
    into three runs with three different cameras. Every take here uses the same job and the same crop.
    """
    from PIL import Image, ImageDraw

    spec = piece_or_die(args.piece)
    generator = DEPLOY / spec["generator"]
    original = generator.read_text(encoding="utf-8")
    pattern = re.compile(r"^(\s*" + re.escape(args.param) + r"\s*=\s*)([0-9.]+)(.*)$", re.M)
    if not pattern.search(original):
        raise SystemExit("[error] " + args.param + " is not a numeric constant in " + spec["generator"])
    values = [value.strip() for value in args.values.split(",") if value.strip()]
    job_path = ROOT / spec["job"]
    takes = []
    try:
        for value in values:
            generator.write_text(pattern.sub(lambda match: match.group(1) + value + match.group(3),
                                             original, count=1), encoding="utf-8")
            say("sweep", args.param + "=" + value + ": rebuild")
            if regenerate(spec) != 0:
                raise SystemExit("[sweep] generator failed at " + value)
            samples = sample(job_path, [str(v) for v in spec["crop"]], reload_first=True)
            if not samples:
                raise SystemExit("[sweep] no shots for " + value)
            label, image, numbers = samples[0]
            say("sweep", describe(args.param + "=" + value, numbers))
            takes.append((value, image))
    finally:
        generator.write_text(original, encoding="utf-8")
        regenerate(spec)
        run([PY, str(generator), "--mirror"])
        run([NODE, "tools/mcpfabric/resource_reload.mjs"])
        say("sweep", "restored " + args.param + " and rebuilt")
    if len(takes) < 2:
        return
    height = max(image.height for _value, image in takes)
    width = sum(int(image.width * height / image.height) for _v, image in takes) + 12 * (len(takes) - 1)
    sheet = Image.new("RGBA", (width, height + 18), (24, 26, 30, 255))
    draw = ImageDraw.Draw(sheet)
    x = 0
    for value, image in takes:
        scaled = image.resize((int(image.width * height / image.height), height), Image.LANCZOS)
        sheet.alpha_composite(scaled, (x, 18))
        draw.text((x + 6, 4), args.param + "=" + value, fill=(255, 255, 255, 255))
        x += scaled.width + 12
    out = ROOT / (args.out or ("build/modelkit/sweep_" + args.param + ".png"))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    say("sweep", "wrote " + str(out.relative_to(ROOT)))


# ---------------------------------------------------------------- gate

def run_gate(script: str) -> bool:
    say("gate", script)
    return run([PY, str(DEPLOY / script)]) == 0


def cmd_gate(args) -> None:
    names = sorted(PIECES) if args.name in (None, "all") else [args.name]
    ok = True
    for name in names:
        ok = run_gate(piece_or_die(name)["gate"]) and ok
    for script in GATES_ALWAYS:
        ok = run_gate(script) and ok
    say("gate", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


# ---------------------------------------------------------------- ship

def cmd_ship(args) -> None:
    spec = piece_or_die(args.name)
    say("ship", "1/5 generate " + spec["generator"] + (" + icon proxy" if spec.get("item") else ""))
    if regenerate(spec) != 0:
        raise SystemExit("[ship] generator failed")
    say("ship", "2/5 gate " + spec["gate"])
    if not run_gate(spec["gate"]):
        raise SystemExit("[ship] gate failed, nothing was reloaded")
    args_live = argparse.Namespace(piece=args.name, job=None, crop=None, reload=True)
    say("ship", "3/5 reload + 4/5 shoot + 5/5 census")
    cmd_live(args_live)
    say("ship", args.name + " pipeline done; numbers above, pictures in build/shots, "
         "source reference in build/blockbench_source_previews")


# ---------------------------------------------------------------- entry

def main(argv) -> None:
    parser = argparse.ArgumentParser(prog="model.py", description="one entry for model work")
    parser.add_argument("--dry", action="store_true", help="print the plan and stop")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("doctor", help="environment and drift check")

    preview = sub.add_parser("preview", help="offline render, numbers first")
    preview.add_argument("names", nargs="*", help="shipped model names, e.g. party_lights_lit")
    preview.add_argument("--raw", help="draw a .bbmodel or model json instead")
    preview.add_argument("--out")
    preview.add_argument("--views", help="front,quarter,iso,top (default front,quarter)")
    preview.add_argument("--size", default="620x620")
    preview.add_argument("--clay", action="store_true", help="flat colour per element, shape only")
    preview.add_argument("--no-blend", action="store_true", help="cutout instead of compositing")
    preview.add_argument("--bg")
    preview.add_argument("--frame", type=int, default=0)
    preview.add_argument("--anim-frame", type=int)
    preview.add_argument("--elements")
    preview.add_argument("--only", help="framing target: element name prefix, geometry still drawn")

    viewport = sub.add_parser("viewport", help="Blockbench viewport of a .bbmodel")
    viewport.add_argument("--source", required=True)
    viewport.add_argument("--out")
    viewport.add_argument("--settle", type=float, default=2.0, help="seconds to wait after launch")
    viewport.add_argument("--reuse", action="store_true", help="capture the Blockbench that is already open")

    compare = sub.add_parser("compare", help="source vs shipped, or viewport vs in-game")
    compare.add_argument("--piece", help="take source/model/frame from a registered piece")
    compare.add_argument("--source")
    compare.add_argument("--model")
    compare.add_argument("--viewport", help="image mode: the Blockbench viewport PNG")
    compare.add_argument("--live", help="image mode: the in-game screenshot")
    compare.add_argument("--crop", help="image mode: crop the in-game shot first, x0,y0,x1,y1")
    compare.add_argument("--height", type=int, default=760)
    compare.add_argument("--out")
    compare.add_argument("--view", default="quarter")
    compare.add_argument("--size", default="520x520")
    compare.add_argument("--fit", default="union", choices=("union", "each"))
    compare.add_argument("--frame", type=int, default=0)
    compare.add_argument("--anim-frame", type=int)
    compare.add_argument("--elements")
    compare.add_argument("--bg")

    export = sub.add_parser("export", help="Blockbench's own java_block export")
    export.add_argument("--source", required=True)
    export.add_argument("--out")
    export.add_argument("--model", help="also diff this shipped model against the export")
    export.add_argument("--textures", action="store_true", help="also dump the source textures")

    live = sub.add_parser("live", help="in-game sample")
    live.add_argument("--piece")
    live.add_argument("--job")
    live.add_argument("--crop", help="x0,y0,x1,y1")
    live.add_argument("--reload", action="store_true")

    gate = sub.add_parser("gate", help="source-difference gates")
    gate.add_argument("name", nargs="?", help="piece name, or all (default)")

    ship = sub.add_parser("ship", help="generate -> gate -> reload -> shoot -> census")
    ship.add_argument("name")

    sweep = sub.add_parser("sweep", help="one constant, several values, same camera, one sheet")
    sweep.add_argument("--piece", required=True)
    sweep.add_argument("--param", required=True)
    sweep.add_argument("--values", required=True)
    sweep.add_argument("--out")

    args = parser.parse_args(argv)
    if args.dry:
        say("dry", json.dumps({k: v for k, v in vars(args).items() if k != "dry"}, default=str))
        return
    {"doctor": cmd_doctor, "preview": cmd_preview, "compare": cmd_compare,
     "viewport": cmd_viewport, "export": cmd_export, "live": cmd_live,
     "gate": cmd_gate, "ship": cmd_ship, "sweep": cmd_sweep}[args.verb](args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main(sys.argv[1:])
