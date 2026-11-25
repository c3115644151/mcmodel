#!/usr/bin/env python
"""Check that a GUI icon still draws the geometry its source model authored.

A GUI proxy is a scaled copy of a block model: the item pipeline may rescale coordinates, but the
things that carry *meaning* in a model must survive the copy -- element order, the direction of every
box (a reversed axis is how the artist makes a shell see-through), the element rotation, and each
face's texture slot and uv. A normalizer that sorts from/to and rotation away turns the artist's
open shell into a closed box, which is invisible in JSON and obvious in the slot.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def model_elements(model_id, seen=None):
    """Elements of a model, following its parent chain until the first model that has any."""
    seen = seen or set()
    if model_id in seen:
        return []
    seen.add(model_id)
    namespace, _, path = model_id.partition(":")
    if namespace != "pastoral_home":
        return []
    file = ASSETS / "models" / (path + ".json")
    if not file.is_file():
        return []
    model = load(file)
    if model.get("elements"):
        return model["elements"]
    parent = model.get("parent")
    return model_elements(parent, seen) if isinstance(parent, str) else []


def signature(element):
    low, high = element.get("from"), element.get("to")
    if low is None or high is None:
        return None
    order = tuple(-1 if low[i] > high[i] else 1 for i in range(3))
    rotation = element.get("rotation") or {}
    spin = (rotation.get("axis"), rotation.get("angle"))
    faces = tuple(sorted((face, spec.get("texture"), tuple(spec.get("uv") or ()))
                         for face, spec in (element.get("faces") or {}).items()))
    return order, spin, faces


def compare(proxy_elements, source_elements):
    problems = []
    if len(proxy_elements) != len(source_elements):
        problems.append("proxy has " + str(len(proxy_elements)) + " elements, source has "
                        + str(len(source_elements)))
    for index, (proxy, source) in enumerate(zip(proxy_elements, source_elements)):
        want, got = signature(source), signature(proxy)
        name = source.get("name") or ("#" + str(index))
        if want is None or got is None:
            problems.append(name + ": element lost its from/to")
            continue
        if got[0] != want[0]:
            problems.append(name + ": box direction " + str(got[0]) + ", source " + str(want[0])
                            + " (a reversed axis is dropped, so the icon closes up)")
        if got[1] != want[1]:
            problems.append(name + ": rotation " + str(got[1]) + ", source " + str(want[1]))
        if got[2] != want[2]:
            missing = [face for face in want[2] if face not in got[2]]
            extra = [face for face in got[2] if face not in want[2]]
            problems.append(name + ": faces differ, missing " + str([f[0] for f in missing])
                            + ", extra " + str([f[0] for f in extra]))
    return problems


def audit(paths=None):
    proxies = sorted((ASSETS / "models/item_icons").glob("*/variant_*.json"))
    if paths:
        wanted = {Path(path).resolve() for path in paths}
        proxies = [proxy for proxy in proxies if proxy.resolve() in wanted]
    failures = 0
    for proxy in proxies:
        model = load(proxy)
        parent = model.get("parent")
        source = model_elements(parent) if isinstance(parent, str) else []
        if not source:
            continue
        problems = compare(model.get("elements") or [], source)
        label = str(proxy.relative_to(ASSETS / "models")).replace("\\", "/")
        if problems:
            failures += 1
            print("FAIL " + label)
            for problem in problems[:6]:
                print("     " + problem)
        else:
            print("ok   " + label + " (" + str(len(source)) + " elements)")
    print(str(len(proxies) - failures) + " of " + str(len(proxies)) + " icons keep their source geometry")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(audit(sys.argv[1:]))
