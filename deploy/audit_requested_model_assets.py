#!/usr/bin/env python3
"""Run static art/variant checks and the Java-shape collision audit for this batch."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    scripts = ROOT / "tools/deploy"
    run([str(scripts / "test_requested_model_assets.py")])
    run([str(scripts / "audit_recent_outdoor_collisions.py"),
         "--profile", "tools/deploy/collision_profiles/spruce_planter.json",
         "--report", "build/requested_models/spruce_planter_collision_audit.json"])
    run([str(scripts / "validate_item_icon_proxies.py"), "--items", "wall_painting,spruce_planter"])
    print("Requested painting and spruce model audits passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
