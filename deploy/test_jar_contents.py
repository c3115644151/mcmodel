"""Gate: what the built jar actually ships.

The resource gates read src/. That is the right place to catch a modelling mistake, but it is not
what a player installs: a resource that never reaches the jar, or a class the jar forgot to pack,
passes every src-side assertion. This gate opens the jar and counts.

It is deliberately separate from test_entryway_models.py. That gate answers "is the entryway set
correct"; this one answers "did the build package it". Mixing them made the resource gate fail on a
missing jar, which reads like a modelling bug and is not one.

Usage:
    python tools/deploy/test_jar_contents.py [--jar build/libs/pastoral_home-1.0.0.jar]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JAR = ROOT / "build/libs/pastoral_home-1.0.0.jar"

BLOCK_STATES = ("bulletin_board", "coat_rack", "parasol", "rug")
ITEM_DEFINITIONS = BLOCK_STATES
FONT_FILES = ("notebook.json", "notebook_title.json", "lxgw_wenkai_lite_regular.ttf", "ofl.txt")
REQUIRED_CLASSES = (
    "com/pastoralhome/item/BulletinPageItem.class",
    "com/pastoralhome/blockentity/BulletinNoticeData.class",
    "com/pastoralhome/client/BulletinBoardBlockEntityRenderer.class",
    "com/pastoralhome/block/BulletinBoardCollisionShapes.class",
    "com/pastoralhome/block/BulletinPageTemplates.class",
    "com/pastoralhome/entity/RugSurfaceEntity.class",
    "com/pastoralhome/item/RugSurfaceItem.class",
    "com/pastoralhome/block/CoatRackCollisionShapes.class",
    "com/pastoralhome/block/ParasolCollisionShapes.class",
    "com/pastoralhome/client/renderer/RugSurfaceRenderer.class",
    "com/pastoralhome/client/PaperNoticeScreen.class",
    "com/pastoralhome/network/SaveBulletinNoticePayload.class",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=DEFAULT_JAR,
                        help="jar to inspect (default: build/libs/pastoral_home-1.0.0.jar)")
    args = parser.parse_args()
    if not args.jar.is_file():
        print(f"missing jar: {args.jar}\nrun: python -m mcmodel jar", file=sys.stderr)
        return 2

    with zipfile.ZipFile(args.jar) as archive:
        names = set(archive.namelist())
    problems: list[str] = []

    def need(name: str, why: str) -> None:
        if name not in names:
            problems.append(f"{name}: {why}")

    need("META-INF/neoforge.mods.toml", "the loader cannot see the mod without it")
    for name in BLOCK_STATES:
        need(f"assets/pastoral_home/blockstates/{name}.json", "blockstate missing from the jar")
        need(f"assets/pastoral_home/items/{name}.json", "item definition missing from the jar")
        need(f"data/pastoral_home/loot_table/blocks/{name}.json", "loot table missing from the jar")
    for layer in range(3):
        for column in range(3):
            for row in range(3):
                need(f"assets/pastoral_home/models/block/bulletin_board_l{layer}_c{column}_r{row}.json",
                     "a sliced cell model is missing, so that cell would draw nothing")
    for name in FONT_FILES:
        need(f"assets/pastoral_home/font/{name}", "the notice UI cannot render its font")
    need("assets/pastoral_home/models/item/bulletin_page.json", "page model missing")
    need("assets/pastoral_home/items/bulletin_page.json", "page item definition missing")
    for variant in range(16):
        need(f"assets/pastoral_home/items/rug_surface_{variant:02x}.json",
             "a rug surface state has no item definition")
    need("assets/pastoral_home/textures/gui/paper_notebook.png", "notice screen texture missing")
    need("assets/pastoral_home/textures/block/bulletin_board_particle.png", "particle texture missing")
    for texture in ("parasol_tex1.png", "parasol_tex2.png"):
        need(f"assets/pastoral_home/textures/block/{texture}", "parasol texture missing")
    for name in REQUIRED_CLASSES:
        need(name, "class not packaged; the feature would fail at runtime")

    if problems:
        print(f"{len(problems)} problem(s) in {args.jar.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{args.jar.name}: {len(names)} entries; resources, fonts and classes all packaged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
