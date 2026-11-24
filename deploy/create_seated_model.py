#!/usr/bin/env python3
"""Create a half-block-lowered model variant without touching UVs or geometry."""

import argparse
import copy
import json
from pathlib import Path


def lower_model(source: dict, shift: float) -> dict:
    seated = copy.deepcopy(source)
    for element in seated.get("elements", []):
        element["from"][1] += shift
        element["to"][1] += shift
        if rotation := element.get("rotation"):
            rotation["origin"][1] += shift
    return seated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shift", type=float, default=-8.0)
    parser.add_argument("--verify", action="store_true", help="verify an existing output instead of writing it")
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    expected = lower_model(source, args.shift)
    if args.verify:
        actual = json.loads(args.output.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit(f"FAIL: {args.output} does not match {args.source} with y shift {args.shift:g}")
        print(f"PASS: {args.output} matches {args.source} with y shift {args.shift:g}")
        return
    args.output.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {args.output} from {args.source} with y shift {args.shift:g}")


if __name__ == "__main__":
    main()
