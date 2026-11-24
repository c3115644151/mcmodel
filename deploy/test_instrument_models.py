#!/usr/bin/env python3
"""Contract checks for the parlour instrument batch: piano (3x2), scroll (flat prop) and the
gramophone (2x2)."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

from PIL import Image

# The shape table is derived by piano_shapes.py next to this file; importing it keeps the
# check in one place instead of restating the voxeliser here.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_piano_models import (  # noqa: E402
    BED_TOP_Y, CASING_TOP_Y, FIELD_TOP_Y, SHELF_TOP_Y, load_band_params,
)

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
GENERATED = ROOT / "src/generated/resources"
LANG = GENERATED / "assets/pastoral_home/lang"
LOOT = GENERATED / "data/pastoral_home/loot_table/blocks"
AXE_TAG = GENERATED / "data/minecraft/tags/block/mineable/axe.json"

PIANO_LAYERS = 2
PIANO_COLUMNS = 3
FACE_ANGLES = {"north": 0, "east": 90, "south": 180, "west": 270}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def model_file(ref: str) -> Path:
    """Resolve "pastoral_home:item_icons/piano/variant_0" to its on-disk model file."""
    namespace, _, path = ref.partition(":")
    folder = "" if namespace == "minecraft" else "models/"
    return ASSETS / f"{folder}{path}.json" if namespace == "pastoral_home" else ROOT / f"build/tmp/{path}.json"


class InstrumentAssetTests(unittest.TestCase):
    def test_piano_multipart_covers_every_cell_and_facing(self):
        multipart = read(ASSETS / "blockstates/piano.json")["multipart"]
        self.assertEqual(len(multipart), len(FACE_ANGLES) * PIANO_LAYERS * PIANO_COLUMNS)
        for facing in FACE_ANGLES:
            for layer in range(PIANO_LAYERS):
                for column in range(PIANO_COLUMNS):
                    when = {"facing": facing, "layer": str(layer), "column": str(column)}
                    entry = next((part for part in multipart if part["when"] == when), None)
                    self.assertIsNotNone(entry, when)
                    model = read(model_file(entry['apply']['model']))
                    self.assertTrue(model["elements"], when)

    def test_piano_cell_models_carry_their_own_fragments(self):
        models = sorted((ASSETS / "models/block").glob("piano_l*_c*.json"))
        self.assertEqual(len(models), PIANO_LAYERS * PIANO_COLUMNS)
        signatures = set()
        for path in models:
            model = read(path)
            self.assertTrue(model["elements"], path.name)
            # The keyboard is a shelf assembly (tools/deploy/prepare_piano_models.py), so a cell
            # declares the palette exactly when it holds key pieces, and those pieces live in the
            # lower layer only. The pieces are: a wooden key slip carrying the artist's painted lip
            # on its north face, one continuous ivory field seen from above, ten raised navy blacks
            # and a nameboard behind them. There is deliberately no per-key seam geometry: the white
            # key separations live in the sheet that the field's front face samples, not the top face
            # (a hairline on a grazing top face turns into diagonal mip slivers in game).
            expected = {"pastoral_home:block/piano", "pastoral_home:block/piano_particle"}
            keys = [element for element in model["elements"] if str(element.get("name", "")).startswith("key_")]
            if keys:
                expected.add("pastoral_home:block/piano_palette")
                expected.add("pastoral_home:block/piano_keys")
            self.assertEqual(set(model["textures"].values()), expected, path.name)
            if path.name.startswith("piano_l1_"):
                self.assertFalse(keys, f"{path.name} must not carry key pieces")
            else:
                self.assertTrue(keys, f"{path.name} carries no key pieces")
                named = {element["name"]: element for element in keys}
                field = named.get("key_field")
                self.assertIsNotNone(field, f"{path.name} lost the ivory key field")
                self.assertAlmostEqual(field["from"][1], SHELF_TOP_Y, delta=1e-6)
                self.assertAlmostEqual(field["to"][1], FIELD_TOP_Y, delta=1e-6)
                # Only the two side faces carry the palette, and a cell that ends the keyboard at
                # its own border culls one of them; the sheet faces are checked just below.
                self.assertLessEqual({face["texture"] for name, face in field["faces"].items()
                                      if name not in ("up", "north")}, {"#piano_palette"})
                self.assertEqual(field["faces"]["north"]["texture"], "#piano_keys",
                                 f"{path.name} field fronts must carry the white-key seams")
                self.assertIn("up", field["faces"], f"{path.name}: the player looks down on an ivory surface")
                self.assertNotEqual(field["faces"]["up"]["texture"], "#piano_keys",
                                    f"{path.name} top face must stay a flat ivory tone")
                self.assertIn("north", field["faces"], f"{path.name}: the band of white front edges")
                slip = named.get("key_slip")
                self.assertIsNotNone(slip, f"{path.name} lost the wooden key slip")
                self.assertAlmostEqual(slip["from"][1], BED_TOP_Y, delta=1e-6)
                self.assertEqual(slip["faces"]["north"]["texture"], "#bb_texture_0",
                                 f"{path.name} slip must keep the artist's painted lip")
                raise_px = load_band_params()["black_raise_px"]
                for black in (element for name, element in named.items() if name.startswith("key_black_")):
                    self.assertAlmostEqual(black["from"][1], FIELD_TOP_Y, delta=1e-6,
                                           msg=f"{path.name} black key sits on the field")
                    self.assertAlmostEqual(black["to"][1], FIELD_TOP_Y + raise_px, delta=1e-6,
                                           msg=f"{path.name} black key is raised")
                    self.assertEqual({face["texture"] for face in black["faces"].values()}, {"#piano_palette"})
                nameboard = named.get("key_nameboard")
                self.assertIsNotNone(nameboard, f"{path.name} lost the nameboard")
                self.assertAlmostEqual(nameboard["to"][1], CASING_TOP_Y, delta=1e-6)
                self.assertFalse([name for name in named if name.startswith(("key_white", "key_seam"))],
                                 f"{path.name} still carries retired per-key geometry")
                for element in keys:
                    self.assertLessEqual(element["to"][1], 16.0 + 1e-6,
                                         f"{path.name}: {element['name']} straddles the upper cell")
            signatures.add(json.dumps(model["elements"], sort_keys=True))
        self.assertEqual(len(signatures), len(models), "each cell must hold a distinct fragment set")

    def test_piano_is_centred_on_the_middle_cell(self):
        # The shell is 43px wide inside a 48px footprint. Flush against x = 0 all 5 leftover pixels
        # would land in the last cell and the piano would read as pushed to one side, so the
        # importer has to split the remainder evenly (user m16888).
        def span(column):
            lows, highs = [], []
            for layer in range(PIANO_LAYERS):
                model = read(ASSETS / f"models/block/piano_l{layer}_c{column}.json")
                lows.append(min(element["from"][0] for element in model["elements"]))
                highs.append(max(element["to"][0] for element in model["elements"]))
            return min(lows), max(highs)

        left_margin, _ = span(0)
        _, right_edge = span(PIANO_COLUMNS - 1)
        right_margin = 16.0 - right_edge
        self.assertAlmostEqual(left_margin, right_margin, delta=0.05,
                               msg="the piano must sit equidistant from both outer cell edges")

    def test_piano_hitboxes_follow_the_centred_cells(self):
        """The hand-written VoxelShape table must be re-derived whenever the cells move.

        The exporter recentred the shell by 2.5px (user m16888), so a table voxelised from the
        old flush-left geometry would keep the collision 2.5px off the drawn model. The numbers
        are not typed by hand: piano_shapes.py derives them from the prepared cells, and this
        check fails with the exact snippet to paste back.
        """
        import piano_shapes

        source = (ROOT / "src/main/java/com/pastoralhome/block/PianoBlock.java").read_text(encoding="utf-8")
        body = source.split("static {", 1)[1]
        recorded = {}
        for match in re.finditer(r"SHAPES\[(\d)\]\[(\d)\] = Shapes\.or\((.*?)\);", body, re.DOTALL):
            recorded[(int(match.group(1)), int(match.group(2)))] = [
                tuple(float(value) for value in group.split(","))
                for group in re.findall(r"box\(([^)]*)\)", match.group(3))
            ]
        self.assertEqual(sorted(recorded), [(layer, column)
                                           for layer in range(PIANO_LAYERS)
                                           for column in range(PIANO_COLUMNS)])
        for cell, expected in piano_shapes.table().items():
            actual = recorded[cell]
            message = f"PianoBlock.SHAPES{list(cell)} is stale; paste:\n{piano_shapes.java_source()}"
            self.assertEqual(len(actual), len(expected), message)
            for got, want in zip(actual, expected):
                for got_value, want_value in zip(got, want):
                    self.assertAlmostEqual(got_value, want_value, delta=1e-4, msg=message)

    def test_split_cells_closes_fragments_at_the_seams(self):
        # A cell split creates a face on every plane it cuts. Dropping those faces assumes the
        # neighbouring cell contributes the matching one, and for an element that really does
        # continue into that cell the two halves then meet as two open shells: an oblique view
        # looks straight through the seam into the model, which read in game as the piano being
        # three separate boxes. The piano keeps them, so each fragment stays a closed box.
        from split_model_cells import split_model

        box = {"from": [0, 0, 0], "to": [48, 32, 6],
               "faces": {face: {"texture": "#t"} for face in
                         ("north", "south", "east", "west", "up", "down")}}
        closed, _ = split_model({"elements": [box]}, keep_seam_faces=True)
        for owner, fragments in closed.items():
            for fragment in fragments:
                self.assertEqual(set(fragment["faces"]), set(box["faces"]),
                                 f"cell {owner} lost a face the split created")
        opened, _ = split_model({"elements": [box]})
        culled = [owner for owner, fragments in opened.items()
                  if any(set(fragment["faces"]) != set(box["faces"]) for fragment in fragments)]
        self.assertTrue(culled, "the default split must still cull the faces it creates")

    def test_scroll_covers_all_four_facings(self):
        variants = read(ASSETS / "blockstates/scroll.json")["variants"]
        seen = {}
        for facing, angle in FACE_ANGLES.items():
            entry = variants[f"facing={facing}"]
            self.assertEqual(entry.get("y", 0), angle, facing)
            seen[entry["model"]] = angle
        self.assertEqual(len(seen), 1, "one model, four rotations")
        model = read(model_file(next(iter(seen))))
        self.assertEqual(len(model["elements"]), 9)

    def test_item_definitions_pick_a_gui_icon(self):
        for name in ("piano", "scroll"):
            definition = read(ASSETS / f"items/{name}.json")["model"]
            self.assertEqual(definition["type"], "minecraft:select", name)
            self.assertEqual(definition["property"], "minecraft:display_context")
            self.assertEqual(definition["cases"][0]["when"], "gui")
            icon = read(model_file(definition['cases'][0]['model']['model']))
            self.assertTrue(icon["elements"], name)
            self.assertIn("gui", icon.get("display", {}), name)

    def test_record_player_multipart_rotates_one_model_per_facing(self):
        multipart = read(ASSETS / "blockstates/record_player.json")["multipart"]
        self.assertEqual(len(multipart), len(FACE_ANGLES))
        for facing, angle in FACE_ANGLES.items():
            when = {"facing": facing}
            entry = next((part for part in multipart if part["when"] == when), None)
            self.assertIsNotNone(entry, when)
            self.assertEqual(entry["apply"].get("y", 0), angle, when)
            self.assertEqual(entry["apply"]["model"], "pastoral_home:block/record_player", when)

    def test_record_player_ships_as_one_obj_model_from_the_anchor(self):
        """The horn must stay one model because a cell split shears its tilted leaves apart.

        Its leaves pivot on the cell borders; clipping them per cell and re-pivoting each
        fragment turned the horn into loose plates in game. Native elements cannot hold a
        three-axis tilt either, so the whole 17-element model ships as neoforge:obj and
        only the anchor cell draws it.
        """
        model = read(ASSETS / "models/block/record_player.json")
        self.assertEqual(model["loader"], "neoforge:obj")
        self.assertEqual(model["model"], "pastoral_home:models/block/record_player.obj")
        self.assertIs(model["flip_v"], False, "the vt values are already top-down")
        # processResources rewrites the particle reference to the generated
        # _particle sibling; both must still point at the gramophone's own art.
        self.assertEqual({value.split("/")[-1] for value in model["textures"].values()},
                         {"record_player", "record_player_particle"})
        self.assertTrue(model["display"]["gui"]["scale"])
        obj = (ASSETS / "models/block/record_player.obj").read_text(encoding="utf-8").splitlines()
        vertices = [line for line in obj if line.startswith("v ")]
        quads = [line for line in obj if line.startswith("f ")]
        self.assertEqual(len(quads), 78, "17 elements, minus the faces a flat plate cannot show")
        self.assertEqual(len(vertices), 78 * 4)
        self.assertFalse([path.name for path in
                          (ASSETS / "models/block").glob("record_player_l*_c*.json")],
                         "cell-split gramophone models are gone")


    def test_record_player_horn_keeps_the_authored_three_axis_tilt(self):
        """The horn art is five zero-thickness multi-axis leaves and the OBJ must keep them so.

        A native element rotates on one axis, so flattening the two 25-degree cheeks tore
        the disc into loose plates; the OBJ path carries all three angles untouched.
        """
        source = read(ROOT / "tools/deploy/model_sources/instruments/record_player.bbmodel")
        self.assertEqual(source["meta"]["model_format"], "free")
        leaves = [c for c in source["elements"]
                  if any(abs(c["to"][axis] - c["from"][axis]) < 1e-6 for axis in range(3))]
        self.assertEqual(len(leaves), 6, "five horn leaves plus the turntable disc")
        multi_axis = [c for c in leaves if c.get("rotation")
                      and len([v for v in c["rotation"] if abs(v) > 0.01]) > 1]
        self.assertEqual(len(multi_axis), 2, "two horn cheeks carry all three angles")

        obj = (ASSETS / "models/block/record_player.obj").read_text(encoding="utf-8")
        spread = max(float(line.split()[2]) for line in obj.splitlines()
                     if line.startswith("v ")) - min(float(line.split()[2])
                                                    for line in obj.splitlines()
                                                    if line.startswith("v "))
        self.assertGreater(spread, 0.8, "the cheeks still reach past the cabinet depth")
        flat_vt = [line for line in obj.splitlines() if line.startswith("vt ")]
        self.assertGreater(len({line for line in flat_vt}), 4, "no degenerate uv rows or columns")

    def test_record_player_icon_uses_the_vanilla_block_gui_transform(self):
        """The icon is placed by minecraft:block/block's camera, never a solved offset.

        A solved per-model translation plus a 45 degree yaw showed the model's back
        face and pushed the icon out of its slot, so the descriptor must carry the
        vanilla values verbatim.
        """
        gui = read(ASSETS / "models/block/record_player.json")["display"]["gui"]
        self.assertEqual(gui["rotation"], [30, 225, 0], "vanilla GUI yaw looks at the front face")
        self.assertEqual(gui["translation"], [0, 0, 0], "the vanilla camera already centers the icon")
        self.assertEqual([round(value, 4) for value in gui["scale"]], [0.625, 0.625, 0.625],
                         "vanilla block-item icon scale keeps the piece at block size")

    def test_record_player_drops_only_from_the_anchor_cell(self):
        loot = read(LOOT / "record_player.json")["pools"][0]
        properties = loot["conditions"][0]["properties"]
        self.assertEqual(properties, {"column": "0", "layer": "0", "row": "0"})
        self.assertEqual(loot["entries"][0]["name"], "pastoral_home:record_player")

    def test_textures_are_power_of_two_and_present(self):
        for name in ("piano", "scroll", "record_player"):
            for suffix in ("", "_particle"):
                path = ASSETS / f"textures/block/{name}{suffix}.png"
                self.assertTrue(path.exists(), path)
                with Image.open(path) as image:
                    width, height = image.size
                self.assertEqual(width % 16, 0, path)
                self.assertEqual(height % 16, 0, path)

    def test_piano_drops_only_from_the_anchor_cell(self):
        loot = read(LOOT / "piano.json")["pools"][0]
        properties = loot["conditions"][0]["properties"]
        # PianoBlock.ANCHOR_COLUMN is 1: the click lands on the middle column and the other two
        # grow outwards from it, so a condition naming column 0 would never match a real state.
        self.assertEqual(properties, {"column": "1", "layer": "0", "row": "0"})
        self.assertEqual(loot["entries"][0]["name"], "pastoral_home:piano")

    def test_scroll_drops_itself(self):
        loot = read(LOOT / "scroll.json")["pools"][0]
        self.assertEqual(loot["entries"][0]["name"], "pastoral_home:scroll")
        self.assertNotIn("conditions", loot)

    def test_all_three_blocks_are_axe_mineable(self):
        values = set(read(AXE_TAG)["values"])
        self.assertIn("pastoral_home:piano", values)
        self.assertIn("pastoral_home:scroll", values)
        self.assertIn("pastoral_home:record_player", values)

    def test_gramophone_silhouette_stays_a_coarse_proxy(self):
        """The horn is thin tilted plates: a voxel staircase would outline a cage of little cubes."""
        source = (ROOT / "src/main/java/com/pastoralhome/block/RecordPlayerBlock.java").read_text(encoding="utf-8")
        body = source.split("static {", 1)[1].split("\n    }", 1)[0]
        boxes = [line.strip() for line in body.splitlines() if line.strip().startswith("box(")]
        self.assertLessEqual(len(boxes), 4, "\n".join(boxes))
        # Unused columns and the spare third layer mirror the real ones instead of
        # falling off the table when the registry bakes every state.
        self.assertIn("SHAPES[layer][1] = SHAPES[layer][0];", body)
        self.assertIn("SHAPES[layer][2] = SHAPES[layer][0];", body)
        self.assertIn("SHAPES[2][column] = SHAPES[1][column];", body)

    def test_localized_names(self):
        for language in ("en_us", "zh_cn"):
            entries = read(LANG / f"{language}.json")
            for name in ("piano", "scroll", "record_player"):
                key = f"block.pastoral_home.{name}"
                self.assertIn(key, entries, f"{language} {key}")
                self.assertTrue(entries[key].strip(), f"{language} {key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
