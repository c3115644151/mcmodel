import json
import tempfile
import unittest
from pathlib import Path

from audit_recent_outdoor_collisions import ROOT, audit_profile


class RecentOutdoorCollisionProfilesTests(unittest.TestCase):
    def test_current_collision_shapes_meet_tool_profiles(self):
        profile_path = ROOT / "tools/deploy/collision_profiles/recent_outdoor.json"
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            for profile in profile_data["profiles"]:
                with self.subTest(model=profile["id"]):
                    report = audit_profile(profile, 4, Path(temp))
                    self.assertTrue(report["pass"], json.dumps(report, ensure_ascii=False, indent=2))
                    if "current" in report:
                        self.assertLessEqual(report["current"]["miss_percent"],
                                             report["limits"]["max_miss_percent"])


if __name__ == "__main__":
    unittest.main()
