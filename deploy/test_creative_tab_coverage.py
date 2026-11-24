#!/usr/bin/env python3
"""Every item the mod declares must be reachable somewhere, and furniture must be in the tab.

The gramophone shipped as a working block, a working item, a loot table and a model, and still
could not be found by the artist: `ModCreativeTabs` is a hand-written list, and nobody added
`ModItems.RECORD_PLAYER` to it, so the item existed but never appeared in the creative
inventory. Nothing offline catches that, because every asset is present and valid.

This gate compares the item declarations with the creative tab's `output.accept` calls. Items
that are intentionally hidden (internal render parts consumed by their owning block, and the
bulletin page that is handed out by the board itself) are listed below with the reason.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ITEMS = ROOT / "src/main/java/com/pastoralhome/registry/ModItems.java"
TABS = ROOT / "src/main/java/com/pastoralhome/registry/ModCreativeTabs.java"

DECLARATION = re.compile(r"public static final Deferred\w+<[^>]+>\s+(\w+)\s*=")
ACCEPTED = re.compile(r"output\.accept\(ModItems\.(\w+)\.get\(\)")

# Declared as items, deliberately absent from the creative tab.
HIDDEN = {
    "GLOBE_SPHERE_RENDER": "render part, drawn by GlobeBlockEntityRenderer",
    "GLOBE_STAND_RENDER": "render part, drawn by GlobeBlockEntityRenderer",
    "TELESCOPE_HEAD_RENDER": "render part, drawn by TelescopeBlockEntityRenderer",
    "TELESCOPE_STAND_RENDER": "render part, drawn by TelescopeBlockEntityRenderer",
    "WEATHER_VANE_BASE": "render part, drawn by WeatherVaneBlockEntityRenderer",
    "WEATHER_VANE_ROOSTER": "render part, drawn by WeatherVaneBlockEntityRenderer",
    "WHEELBARROW_BODY": "render part, placed by WheelbarrowBlock",
    "WHEELBARROW_FULL": "render part, placed by WheelbarrowBlock",
    "WHEELBARROW_FULL_NO_WHEEL": "render part, placed by WheelbarrowBlock",
    "WHEELBARROW_WHEEL": "render part, placed by WheelbarrowBlock",
    "BULLETIN_PAGE": "handed out by the bulletin board, not a build material",
}


def declared_items() -> set[str]:
    return set(DECLARATION.findall(ITEMS.read_text(encoding="utf-8")))


def tab_items() -> set[str]:
    return set(ACCEPTED.findall(TABS.read_text(encoding="utf-8")))


class CreativeTabCoverageTest(unittest.TestCase):
    def test_every_placeable_item_is_in_the_creative_tab(self) -> None:
        missing = sorted(declared_items() - tab_items() - set(HIDDEN))
        self.assertEqual([], missing, "items declared but not offered in the creative tab")

    def test_hidden_list_only_names_real_items(self) -> None:
        stale = sorted(set(HIDDEN) - declared_items())
        self.assertEqual([], stale, "hidden list mentions items that no longer exist")

    def test_tab_only_offers_declared_items(self) -> None:
        unknown = sorted(tab_items() - declared_items())
        self.assertEqual([], unknown, "creative tab offers items that are not declared")


if __name__ == "__main__":
    unittest.main()
