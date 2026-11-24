#!/usr/bin/env python3
"""Fail the build when registered furniture, items, or UI strings lack either locale.

<p>Two separate holes ship as raw keys on screen: a registered item with no name, and a
{@code Component.translatable("...")} call whose key the provider never emitted. The gramophone
shipped complete but unlisted in the creative tab for the same reason: a hand-written catalog that
nobody compared against the registry. This gate compares every catalog against its source.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLOCKS = ROOT / "src/main/java/com/pastoralhome/registry/ModBlocks.java"
ITEMS = ROOT / "src/main/java/com/pastoralhome/registry/ModItems.java"
PROVIDER = ROOT / "src/main/java/com/pastoralhome/data/ModLanguageProvider.java"
LANG = ROOT / "src/generated/resources/assets/pastoral_home/lang"

block_source = BLOCKS.read_text(encoding="utf-8")
item_source = ITEMS.read_text(encoding="utf-8")
provider = PROVIDER.read_text(encoding="utf-8")
blocks = re.findall(
    r"DeferredBlock<[^>]+>\s+(\w+)\s*=\s*BLOCKS\.registerBlock\(\"([a-z0-9_]+)\"",
    block_source,
)
items = re.findall(r"DeferredItem<[^>]+>\s+(\w+)\s*=\s*ITEMS\.register(?:Simple)?(?:Block)?Item\(\"([a-z0-9_]+)\"", item_source)
items += re.findall(r"DeferredItem<[^>]+>\s+(\w+)\s*=\s*ITEMS\.register(?:Simple)?Item\(\"([a-z0-9_]+)\"", item_source)

for constant, name in blocks:
    assert f"addBlock(ModBlocks.{constant}," in provider, f"No bilingual block entry in provider: {name}"

for locale in ("en_us", "zh_cn"):
    translations = json.loads((LANG / f"{locale}.json").read_text(encoding="utf-8"))
    missing_blocks = [name for _, name in blocks if f"block.pastoral_home.{name}" not in translations]
    if missing_blocks:
        raise AssertionError(f"{locale} is missing registered block names: {', '.join(missing_blocks)}")
    missing_items = [name for _, name in items
                     if f"item.pastoral_home.{name}" not in translations
                     and f"block.pastoral_home.{name}" not in translations]
    if missing_items:
        raise AssertionError(f"{locale} is missing registered item names: {', '.join(missing_items)}")

# The language provider is the catalog for every non-name string (gui labels, hints, messages).
# A key declared here but never generated means datagen has not been rerun since it was added.
declared = set(re.findall(r'add\("([^"]+)"', provider))
# Every key a chat, action-bar, tooltip or screen actually asks for.
requested = set()
for source in (ROOT / "src/main/java/com/pastoralhome").rglob("*.java"):
    for key in re.findall(r'translatable\(\s*"([^"]+)"', source.read_text(encoding="utf-8")):
        # Keys ending in a separator are assembled at runtime from an id; they cannot be checked.
        if key.endswith((".", "_")):
            continue
        if ".pastoral_home." in key or key.startswith("itemGroup.pastoral_home"):
            requested.add(key)

for locale in ("en_us", "zh_cn"):
    translations = json.loads((LANG / f"{locale}.json").read_text(encoding="utf-8"))
    missing_declared = sorted(declared - translations.keys())
    if missing_declared:
        raise AssertionError(
            f"{locale} has no generated text for provider keys: {', '.join(missing_declared)}"
            " (run runData after editing ModLanguageProvider)")
    missing_requested = sorted(requested - translations.keys())
    if missing_requested:
        raise AssertionError(
            f"{locale} is missing keys that code asks for: {', '.join(missing_requested)}")

print(f"Localization catalog complete: {len(blocks)} blocks and {len(items)} items, "
      f"{len(declared)} provider keys and {len(requested)} requested keys in en_us and zh_cn.")
