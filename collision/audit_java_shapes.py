#!/usr/bin/env python3
"""Read the collision boxes a Java block class declares, so an audit can compare
them with the geometry the model actually has.

The audit needs the numbers inside `VoxelShape` constants, not a compiled class
file. This module parses the Java source text and only understands the shapes the
project writes by hand:

* `Shapes.or(box(3, 0, 3, 13, 7, 13), ...)` / `Shapes.or(Block.box(...), ...)`
* `Shapes.box(0.0, 0.0, 0.1875, 1.0, 0.5, 0.8125)` - normalised 0..1, scaled by 16
* numeric arguments written as arithmetic, e.g. `4.5 / 16.0`
* references to other constants of the same class, resolved recursively
* `.move(dx, dy, dz)` applied to a shape (arguments in blocks, scaled by 16)
* `Shapes.empty()`

Anything else raises `ShapeParseError` instead of guessing: a silently wrong box
table is worse than a loud failure, because the audit exists to catch wrong boxes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SHAPE_TYPE = r"(?:net\.minecraft\.world\.phys\.shapes\.)?VoxelShape"
FIELD_RE = re.compile(
    rf"(?:private|public|protected)?\s*static\s+final\s+{SHAPE_TYPE}\s+(\w+)\s*=",
    re.MULTILINE,
)
EMPTY_RE = re.compile(r"^Shapes\.empty\(\)$")
OR_CALL = ("Shapes.or", "combine")
BOX_PX_CALLS = ("box", "Block.box")
BOX_NORMALISED_CALLS = ("Shapes.box",)
MOVE_RE = re.compile(r"\.move\(([^()]*)\)\s*$")
QUALIFIED_PREFIXES = (
    ("net.minecraft.world.phys.shapes.Shapes.", "Shapes."),
    ("net.minecraft.world.level.block.Block.", "Block."),
)


class ShapeParseError(Exception):
    """Raised when a VoxelShape expression uses a form this parser cannot read."""


def _split_args(text: str) -> list[str]:
    """Split a call argument list on top-level commas."""
    args, depth, current = [], 0, []
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _number(expression: str) -> float:
    """Evaluate an arithmetic argument such as `4.5 / 16.0`."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as error:
        raise ShapeParseError(f"cannot parse number {expression!r}") from error
    return _eval_node(tree.body, expression)


def _eval_node(node, expression):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, expression)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, expression)
        right = _eval_node(node.right, expression)
        operations = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                      ast.Mult: lambda: left * right}
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ShapeParseError(f"division by zero in {expression!r}")
            return left / right
        for kind, apply in operations.items():
            if isinstance(node.op, kind):
                return apply()
    raise ShapeParseError(f"cannot parse number {expression!r}")


def _call_body(text: str, name: str):
    """Return the argument text of `name(...)` when `text` is exactly that call."""
    if not text.startswith(name + "("):
        return None
    opening = len(name)
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                if text[index + 1:].strip():
                    return None
                return text[opening + 1:index]
    raise ShapeParseError(f"unbalanced parentheses in {text!r}")


class ShapeFieldReader:
    """Resolve `VoxelShape` constants declared in one Java source file."""

    def __init__(self, source: str):
        self.source = source
        self.fields = self._field_bodies()
        self._cache: dict[str, list[tuple[float, ...]]] = {}
        self._resolving: set[str] = set()

    def _field_bodies(self) -> dict[str, str]:
        bodies: dict[str, str] = {}
        for match in FIELD_RE.finditer(self.source):
            name = match.group(1)
            start = match.end()
            depth = 0
            end = start
            while end < len(self.source):
                char = self.source[end]
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                elif char == ";" and depth == 0:
                    break
                end += 1
            bodies[name] = " ".join(self.source[start:end].split())
        return bodies

    def shape(self, name: str) -> list[tuple[float, ...]]:
        if name in self._cache:
            return self._cache[name]
        if name not in self.fields:
            raise ShapeParseError(f"no VoxelShape field named {name!r} in this class")
        if name in self._resolving:
            raise ShapeParseError(f"VoxelShape field {name!r} refers to itself")
        self._resolving.add(name)
        try:
            boxes = self._expression(self.fields[name])
        finally:
            self._resolving.discard(name)
        self._cache[name] = boxes
        return boxes

    def _expression(self, text: str) -> list[tuple[float, ...]]:
        for qualified, short in QUALIFIED_PREFIXES:
            text = text.replace(qualified, short)
        text = text.strip()
        if EMPTY_RE.match(text):
            return []
        move = MOVE_RE.search(text)
        if move:
            axes = [_number(part) for part in _split_args(move.group(1))]
            if len(axes) != 3:
                raise ShapeParseError(f"move() needs three arguments in {text!r}")
            shift = [value * 16.0 for value in axes]
            head = text[:move.start()].strip()
            return [tuple(box[index] + shift[index % 3] for index in range(6))
                    for box in self._expression(head)]
        for name in OR_CALL:
            body = _call_body(text, name)
            if body is None:
                continue
            boxes: list[tuple[float, ...]] = []
            for argument in _split_args(body):
                boxes.extend(self._expression(argument))
            return boxes
        for name, scale in ((*BOX_NORMALISED_CALLS, 16.0), *((call, 1.0) for call in BOX_PX_CALLS)):
            body = _call_body(text, name)
            if body is None:
                continue
            values = [_number(part) * scale for part in _split_args(body)]
            if len(values) != 6:
                raise ShapeParseError(f"{name}() needs six arguments in {text!r}")
            return [tuple(values)]
        if re.fullmatch(r"[A-Za-z_$][\w$]*", text):
            return self.shape(text)
        raise ShapeParseError(f"unsupported VoxelShape expression {text!r}")


def read_shape(java_path: str | Path, shape_field: str) -> list[tuple[float, ...]]:
    """Return the boxes of one `VoxelShape` constant as block-pixel 6-tuples."""
    path = Path(java_path)
    if not path.is_file():
        raise ShapeParseError(f"no Java source at {path}")
    reader = ShapeFieldReader(path.read_text(encoding="utf-8"))
    return reader.shape(shape_field)


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="read one VoxelShape constant out of a Java block class")
    parser.add_argument("java", help="path to the block class")
    parser.add_argument("field", help="name of the VoxelShape constant")
    args = parser.parse_args()
    try:
        boxes = read_shape(args.java, args.field)
    except ShapeParseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"{len(boxes)} boxes in {args.field}")
    for box in boxes:
        print("  box(" + ", ".join(f"{value:.5f}" for value in box) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
