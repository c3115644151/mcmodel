#!/usr/bin/env python3
"""Guards the model bounds check that keeps every shipped model bakeable."""
from __future__ import annotations

import unittest

from check_model_bounds import MODEL_HIGH, MODEL_LOW, oversized_points, referenced_models, scan


class OversizedPointTest(unittest.TestCase):
    def test_accepts_a_cube_inside_the_bounds(self):
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16]}]}
        self.assertEqual(oversized_points(model), [])

    def test_flags_a_to_point_past_the_high_bound(self):
        model = {"elements": [{"from": [0, 0, 0], "to": [43, 32, 16]}]}
        self.assertEqual(oversized_points(model), [("elements[0].to", [43.0, 32.0, 16.0])])

    def test_flags_a_from_point_below_the_low_bound(self):
        model = {"elements": [{"from": [-17, 0, 0], "to": [16, 16, 16]}]}
        self.assertEqual(oversized_points(model), [("elements[0].from", [-17.0, 0.0, 0.0])])

    def test_a_rotation_origin_may_sit_outside_the_block(self):
        # getRotation reads the pivot with a plain vector parse, so arch and the
        # cabinets legitimately pivot around points well outside [-16, 32].
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16],
                              "rotation": {"angle": 22.5, "axis": "x", "origin": [0, 0, 40]}}]}
        self.assertEqual(oversized_points(model), [])

    def test_reads_the_three_point_keys_only(self):
        model = {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "size": [99, 99, 99]}]}
        self.assertEqual(oversized_points(model), [])


class ReferencedModelTest(unittest.TestCase):
    def test_collects_a_plain_model_reference(self):
        definition = {"model": {"type": "minecraft:model", "model": "pastoral_home:block/piano_item"}}
        self.assertEqual(referenced_models(definition, []), ["pastoral_home:block/piano_item"])

    def test_collects_every_select_case_and_the_fallback(self):
        definition = {"model": {"type": "minecraft:select", "property": "minecraft:display_context",
                                "cases": [{"when": "gui", "model": {"type": "minecraft:model",
                                           "model": "pastoral_home:item_icons/piano/variant_0"}}],
                                "fallback": {"type": "minecraft:model",
                                             "model": "pastoral_home:block/piano_item"}}}
        self.assertEqual(referenced_models(definition, []),
                         ["pastoral_home:item_icons/piano/variant_0",
                          "pastoral_home:block/piano_item"])


class ShippedModelsTest(unittest.TestCase):
    def test_every_shipped_model_stays_inside_the_element_bounds(self):
        self.assertEqual(scan(), [])

    def test_bounds_match_the_vanilla_cuboid_deserializer(self):
        self.assertEqual((MODEL_LOW, MODEL_HIGH), (-16.0, 32.0))


if __name__ == "__main__":
    unittest.main()
