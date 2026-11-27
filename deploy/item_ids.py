#!/usr/bin/env python3
"""Which registered items are real inventory items, and which are internal parts.

ModItems.java registers both player-facing items and internal render parts
(globe_sphere_render, wheelbarrow_wheel, weather_vane_base, ...). A registered id is
not proof that the item belongs in a GUI icon sheet, so the creative tab list is the
source of truth for "official": ModCreativeTabs.java is what the player can actually
pick, and anything registered but absent there is a component.

Usage: python tools/deploy/item_ids.py [--root DIR] [--all]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REGISTRATION = re.compile(
    r"DeferredItem<\w+>\s+(\w+)\s*=\s*ITEMS\.register\w*\(\s*\"([a-z0-9_]+)\"")
TAB_ENTRY = re.compile(r"ModItems\.(\w+)")


def registered_items(root: Path) -> dict[str, str]:
    """constant name -> item id, for every ITEMS.register* call in ModItems.java."""
    source = (root / "src/main/java/com/pastoralhome/registry/ModItems.java").read_text(encoding="utf-8")
    return {name: item_id for name, item_id in REGISTRATION.findall(source)}


def tab_items(root: Path) -> set[str]:
    """Item ids the creative tab offers; variants of one item collapse to that id."""
    source = (root / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java").read_text(encoding="utf-8")
    by_name = registered_items(root)
    return {by_name[name] for name in TAB_ENTRY.findall(source) if name in by_name}


def official_items(root: Path) -> list[str]:
    return sorted(tab_items(root))


def component_items(root: Path) -> list[str]:
    return sorted(set(registered_items(root).values()) - tab_items(root))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--all", action="store_true", help="list registered ids instead of official ones")
    parser.add_argument("--components", action="store_true", help="list registered ids the creative tab hides")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.components:
        ids = component_items(root)
    elif args.all:
        ids = sorted(registered_items(root).values())
    else:
        ids = official_items(root)
    print(" ".join(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
