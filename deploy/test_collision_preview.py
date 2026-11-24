import unittest

from preview_collision_profiles import cell_grid_edges, union_boundary_edges


class CollisionUnionPreviewTests(unittest.TestCase):
    def test_touching_boxes_render_as_one_outline_without_a_shared_seam(self):
        left = (0, 0, 0, 1, 1, 1)
        right = (1, 0, 0, 2, 1, 1)
        merged = (0, 0, 0, 2, 1, 1)
        self.assertEqual(union_boundary_edges([left, right]), union_boundary_edges([merged]))

    def test_overlapping_boxes_do_not_draw_their_internal_edges(self):
        first = (0, 0, 0, 1.5, 1, 1)
        second = (0.5, 0, 0, 2, 1, 1)
        merged = (0, 0, 0, 2, 1, 1)
        self.assertEqual(union_boundary_edges([first, second]), union_boundary_edges([merged]))

    def test_two_cell_preview_marks_the_cell_seam(self):
        edges = cell_grid_edges(lambda point: point, 32.0)
        self.assertTrue(any(16.0 in (a[1], b[1]) for a, b in edges))
        self.assertTrue(any(32.0 in (a[1], b[1]) for a, b in edges))


if __name__ == "__main__":
    unittest.main()
