#!/usr/bin/env python3
"""Split exported Java block model elements into reusable multipart assets.

Example: split a table into its common body and four hideable edge strips.
  python tools/deploy/split_model_parts.py table.json out_dir \
      --part base=0,1,2,3,4 --part edge_east=5 --part edge_west=6 \
      --part edge_south=7 --part edge_north=8
"""
import argparse
import copy
import json
from pathlib import Path


def parse_part(value: str, element_count: int) -> tuple[str, list[int]]:
    name, separator, indices_text = value.partition("=")
    if not separator or not name or not indices_text:
        raise argparse.ArgumentTypeError("expected NAME=INDEX[,INDEX...]")
    try:
        indices = [int(part) for part in indices_text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid element index in {value!r}") from exc
    if len(indices) != len(set(indices)) or any(i < 0 or i >= element_count for i in indices):
        raise argparse.ArgumentTypeError(f"indices in {value!r} must be unique and within 0..{element_count - 1}")
    return name, indices


def parse_offset(value: str) -> tuple[str, tuple[float, float, float]]:
    name, separator, vector = value.partition("=")
    if not separator or not name:
        raise argparse.ArgumentTypeError("expected NAME=X,Y,Z")
    try:
        values = tuple(float(part) for part in vector.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid offset in {value!r}") from exc
    if len(values) != 3:
        raise argparse.ArgumentTypeError("offset must contain three numbers: X,Y,Z")
    return name, values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="exported Java block model JSON")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--part", action="append", required=True, metavar="NAME=INDICES")
    parser.add_argument("--translate", action="append", default=[], metavar="NAME=X,Y,Z",
                        help="translate the selected elements and their rotation origins")
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    elements = model.get("elements")
    if not isinstance(elements, list) or not elements:
        raise SystemExit("input model has no elements")
    parts = [parse_part(value, len(elements)) for value in args.part]
    if len({name for name, _ in parts}) != len(parts):
        raise SystemExit("part names must be unique")
    offsets = dict(parse_offset(value) for value in args.translate)
    unknown_offsets = set(offsets) - {name for name, _ in parts}
    if unknown_offsets:
        raise SystemExit(f"translations reference unknown part(s): {', '.join(sorted(unknown_offsets))}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, indices in parts:
        output = copy.deepcopy(model)
        output["elements"] = [copy.deepcopy(elements[index]) for index in indices]
        dx, dy, dz = offsets.get(name, (0.0, 0.0, 0.0))
        for element in output["elements"]:
            for coordinate in ("from", "to"):
                if coordinate in element:
                    element[coordinate] = [element[coordinate][0] + dx,
                                           element[coordinate][1] + dy,
                                           element[coordinate][2] + dz]
            rotation = element.get("rotation")
            if isinstance(rotation, dict) and "origin" in rotation:
                rotation["origin"] = [rotation["origin"][0] + dx,
                                      rotation["origin"][1] + dy,
                                      rotation["origin"][2] + dz]
        target = args.output_dir / f"{args.model.stem}_{name}.json"
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{target}: {len(indices)} elements")


if __name__ == "__main__":
    main()
