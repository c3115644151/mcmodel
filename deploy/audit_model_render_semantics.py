#!/usr/bin/env python3
"""Catch the three render-semantics mistakes that cost this project the most time.

Every rule here is a failure that actually shipped and had to be diagnosed from screenshots:

1. A core hidden behind an opaque shell. The party-lights model has a 3x3x3 lit core inside a
   4x4x4 paper shell. Two things can open that hull, and the audit has to accept both:
   * the artist's negative size. A shell whose from is greater than its to on one axis puts two of
     its quads on the far planes facing away, and FaceBakery only re-winds a quad when
     elementRotation is null - the rotation object Blockbench writes on every element keeps the
     repair off, so backface culling drops those two quads and the core shows through. Inside-out
     shells are therefore a note, not a fault.
   * alpha. Without either trick the same geometry renders as a solid orange cube, and the fix is
     then art: shrink the shell texture's alpha and draw the core first.

   A plain ascending box with six opaque faces and no rotation really does bury what it holds.
2. Draw order. Inside one block model all quads share a render type, so a translucent shell and an
   opaque core are submitted in the order the elements are listed. Shell first buries the core and
   the lamp reads as a cream brick (build/shots/pl_v8.png).
3. "render_type" in the model JSON. It does not exist in 26.1.2 - the decompiled sources have zero
   hits - and the render type is chosen from the texture's alpha at bake time
   (BlockModelRenderState.java:57-59). Writing the field looks authoritative and does nothing.

  .venv/Scripts/python.exe tools/deploy/audit_model_render_semantics.py
  .venv/Scripts/python.exe tools/deploy/audit_model_render_semantics.py --explain party_lights
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
BLOCK_MODELS = ASSETS / "models/block"
EPSILON = 0.01
# Elements narrower than this in any axis are decals and slices; they cannot hide anything.
MIN_SOLID = 0.5


def texture_path(reference: str, assets: Path = ASSETS) -> Path | None:
    """Resolve a texture name to a file. Model textures live under namespaced ids
    ("pastoral_home:block/x") or bare stems ("x"); anything else is a vanilla texture this audit has
    no business reading."""
    if not isinstance(reference, str) or not reference or reference.startswith("#"):
        return None
    if ":" in reference:
        namespace, _, relative = reference.partition(":")
        if namespace != "pastoral_home":
            return None
        return assets / "textures" / (relative + ".png")
    return assets / "textures" / (reference + ".png")


def texture_map(data: dict) -> dict[str, str]:
    """Face references are keys into the model's own textures table; resolve them first, or every
    lookup misses and the whole audit silently reports nothing."""
    table = data.get("textures") or {}
    resolved: dict[str, str] = {}
    for key, value in table.items():
        reference = value if isinstance(value, str) else None
        while isinstance(reference, str) and reference.startswith("#"):
            reference = table.get(reference[1:])
        if isinstance(reference, str):
            resolved["#" + key] = reference
    return resolved


def alpha_profile(path: Path) -> dict | None:
    if not path.exists():
        return None
    image = Image.open(path).convert("RGBA")
    alphas = image.getchannel("A").tobytes()
    total = len(alphas) or 1
    clear = alphas.count(0)
    partial = sum(1 for value in alphas if 0 < value < 255)
    return {
        "clear": 100.0 * clear / total,
        "partial": 100.0 * partial / total,
        "sheet": image.size,
    }


def bounds(element: dict) -> tuple[float, float, float, float, float, float] | None:
    try:
        low = [float(v) for v in element["from"]]
        high = [float(v) for v in element["to"]]
    except (KeyError, TypeError, ValueError):
        return None
    return (min(low[0], high[0]), min(low[1], high[1]), min(low[2], high[2]),
            max(low[0], high[0]), max(low[1], high[1]), max(low[2], high[2]))


def contains(outer, inner) -> bool:
    return all(outer[i] - EPSILON <= inner[i] for i in range(3)) and \
           all(inner[i + 3] <= outer[i + 3] + EPSILON for i in range(3))


def inside_out(element: dict) -> bool:
    """True when the element is authored with a negative size and keeps a rotation object.

    That pair is what stops Minecraft's winding repair, so the reversed axis leaves two quads
    back-facing and culled - the hull is open on those two sides."""
    if "rotation" not in element:
        return False
    try:
        low = [float(v) for v in element["from"]]
        high = [float(v) for v in element["to"]]
    except (KeyError, TypeError, ValueError):
        return False
    return any(low[i] > high[i] + EPSILON for i in range(3))


def volume(box) -> float:
    return max(0.0, box[3] - box[0]) * max(0.0, box[4] - box[1]) * max(0.0, box[5] - box[2])


def element_textures(element: dict) -> set[str]:
    faces = element.get("faces") or {}
    return {face.get("texture") for face in faces.values() if isinstance(face, dict)}


def audit(path: Path, assets: Path = ASSETS, notes: list[str] | None = None) -> list[str]:
    problems: list[str] = []
    notes = notes if notes is not None else []
    data = json.loads(path.read_text(encoding="utf-8"))
    name = path.stem

    if "render_type" in data:
        problems.append(f"{name}: declares render_type, which 26.1.2 ignores; the pass is chosen from "
                        f"texture alpha at bake time")

    elements = [element for element in data.get("elements") or [] if bounds(element)]
    if not elements:
        return problems

    resolved = texture_map(data)
    sheets: dict[str, dict] = {}
    for element in elements:
        for reference in element_textures(element):
            target = texture_path(resolved.get(reference, reference), assets)
            if target is None or reference in sheets:
                continue
            profile = alpha_profile(target)
            if profile:
                sheets[reference] = profile

    solid = {reference for reference, profile in sheets.items() if profile["partial"] < 0.5}
    translucent = {reference for reference, profile in sheets.items() if profile["partial"] >= 0.5}

    # Rule 1: an element fully swallowed by a bigger one, with every texture of the shell opaque.
    #
    # Nesting alone proves nothing: imported furniture parks a thin liner inside a body box all the
    # time and it renders fine, because a box bounding another box is not a closed hull. So the
    # strict verdict is only for elements the generators name (our own models, where the inner
    # element really is a concealed core). Unnamed nesting is reported as a note for a human.
    for index, inner in enumerate(elements):
        inner_box = bounds(inner)
        if volume(inner_box) <= MIN_SOLID ** 3:
            continue
        for outer_index, outer in enumerate(elements):
            if outer_index == index:
                continue
            outer_box = bounds(outer)
            if not contains(outer_box, inner_box) or volume(outer_box) <= volume(inner_box) * 1.15:
                continue
            shell = {reference for reference in element_textures(outer) if reference in sheets}
            if not shell or not shell <= solid:
                continue
            # A hull with a missing face is open on that side; the piano casing boxes its key bed and
            # still shows the keys because its front face was never drawn. Only a full six-face box
            # in opaque material actually buries what it contains.
            if inside_out(outer):
                notes.append(f"{name}: element {index} is inside element {outer_index}, which is "
                             f"authored inside out (negative size plus rotation), so its reversed-axis "
                             f"quads are culled and the inner element shows through")
                continue
            if len(outer.get("faces") or {}) < 6:
                notes.append(f"{name}: element {index} is inside element {outer_index}, which has only "
                             f"{len(outer.get('faces') or {})} faces, so it is open and can still show it")
                continue
            if not inner.get("name"):
                notes.append(f"{name}: unnamed element {index} is enclosed by element {outer_index} "
                             f"and the shell is opaque; fine unless it was meant to be visible")
                continue
            problems.append(
                f"{name}: element {index} ({inner['name']}) sits inside element {outer_index} "
                f"({outer.get('name') or outer_box}) and every shell texture is fully opaque; the inner "
                f"element can never be seen in game - lower the shell alpha and list the inner element "
                f"first")

    # Rule 2: with a translucent material in the model, opaque geometry has to be submitted first.
    if translucent:
        order = [(index, element_textures(element) & translucent, element_textures(element) & solid)
                 for index, element in enumerate(elements)]
        first_solid = min((index for index, _, opaque in order if opaque), default=None)
        last_translucent = max((index for index, trans, _ in order if trans), default=None)
        if first_solid is not None and last_translucent is not None and first_solid > last_translucent:
            problems.append(
                f"{name}: translucent elements are listed before opaque ones (last translucent at "
                f"{last_translucent}, first opaque at {first_solid}); within a model the list order is "
                f"the draw order, so the opaque geometry buries the translucent shell")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", default=None, help="print every texture profile for one model")
    args = parser.parse_args()

    models = sorted(BLOCK_MODELS.rglob("*.json"))
    if not models:
        print(f"no block models under {BLOCK_MODELS}")
        return 1

    problems: list[str] = []
    notes: list[str] = []
    for path in models:
        problems.extend(audit(path, ASSETS, notes))
        if args.explain and path.stem == args.explain:
            data = json.loads(path.read_text(encoding="utf-8"))
            print(f"{path.stem}:")
            for element in data.get("elements") or []:
                references = element_textures(element)
                print(f"  element {element.get('name') or bounds(element)} textures={sorted(map(str, references))}")
                resolved = texture_map(data)
                for reference in references:
                    target = texture_path(resolved.get(reference, reference))
                    if target is None:
                        continue
                    print(f"    {reference}: {alpha_profile(target)}")

    for note in notes:
        print("NOTE " + note)
    for problem in problems:
        print("FAIL " + problem)
    print(f"{len(models) - len({p.split(':')[0] for p in problems})} of {len(models)} block models clean")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
