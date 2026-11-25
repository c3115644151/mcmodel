#!/usr/bin/env python3
"""Prove every tool script's imports still resolve.

The tools directory once lost `collision/` and `common/` because a cleanup step grepped
for "from collision" / "import collision" and found nothing. That grep could never have
found the real dependency: those scripts put the directory on sys.path first and then
wrote "from run import deploy_collision". The module name in an import statement is the
*file*, not the directory, so a name-based search reports "nobody uses this" right up
until the build stops with ModuleNotFoundError.

This gate reads the import statements instead of grepping for strings, resolves each one
the way the interpreter would once the sys.path insertions happened, and fails for any
import that points at nothing.

Run with no arguments. Exit code 0 means every import resolves.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
#: Directories a tool script can import from, directly or through a sys.path insert.
LIBRARY_DIRS = ("deploy", "collision", "common", "mcmodel")


def script_paths():
    for name in LIBRARY_DIRS:
        directory = TOOLS / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            yield path


def local_modules():
    """Every module name a tool script may import without the standard library."""
    names = set()
    for name in LIBRARY_DIRS:
        directory = TOOLS / name
        if not directory.is_dir():
            continue
        for path in directory.glob("*.py"):
            names.add(path.stem)
        for path in directory.iterdir():
            if path.is_dir() and (path / "__init__.py").is_file():
                names.add(path.name)
    # mcmodel itself is a package at the tools root: "python -m mcmodel" runs from there.
    for path in TOOLS.iterdir():
        if path.is_dir() and (path / "__init__.py").is_file():
            names.add(path.name)
    return names


def import_targets(tree):
    """Yield (module name, lineno) for every import in the module body."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            yield node.module.split(".")[0], node.lineno


def sys_path_inserts(tree):
    """Yield (literal path or None, lineno) for every sys.path.insert call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = node.func
        if not isinstance(target, ast.Attribute):
            continue
        if target.attr not in ("insert", "append"):
            continue
        if not isinstance(target.value, ast.Attribute) or target.value.attr != "path":
            continue
        value = node.args[-1]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            yield value.value, node.lineno
        else:
            # Path(__file__).resolve().parents[N] / "<name>" carries no literal to check.
            yield None, node.lineno


def main():
    known = local_modules()
    problems = []
    imports = 0
    files = 0
    for path in script_paths():
        files += 1
        where = path.relative_to(TOOLS)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            problems.append(f"{where}:{error.lineno}: cannot parse: {error.msg}")
            continue
        for inserted, lineno in sys_path_inserts(tree):
            if inserted is None:
                continue
            if not (Path(inserted).is_absolute() and Path(inserted).exists()):
                problems.append(f"{where}:{lineno}: sys.path gains a missing directory: {inserted}")
        for module, lineno in import_targets(tree):
            imports += 1
            if module in known or module in sys.builtin_module_names:
                continue
            if importlib.util.find_spec(module) is not None:
                continue
            problems.append(f"{where}:{lineno}: no module named {module!r}")

    if problems:
        print("\n".join(problems))
        print(f"{len(problems)} unresolved import(s) across {files} tool scripts")
        return 1
    joined = ", ".join(LIBRARY_DIRS)
    print(f"imports: {imports} statements across {files} tool scripts all resolve")
    print(f"libraries: {len(known)} local module names in {joined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
