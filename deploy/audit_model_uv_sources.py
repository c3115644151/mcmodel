#!/usr/bin/env python3
"""Run the uv audit over every authoring source in tools/deploy/model_sources.

A block model reads uv on a 0..16 grid; the artist authored uv on the project's 16x16 resolution, so
for most sources the numbers pass through unchanged and this pass is silent. It is not decoration: a
32x128 animation strip makes one v unit eight texels tall, and copying such a uv verbatim stretches
every face across four frames, which renders the model as stripes. Sources whose project resolution
differs from 16x16 are reported with the scale their importer has to apply.

Fails when a face window runs off its sheet, comes out empty, or is cut in half by a fully clear row
or column - the three ways a face ends up invisible or split in game.
"""
from __future__ import annotations

import io
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_uv_audit

# Relative to this file, so the audit works both inside a mod checkout (<mod>/tools/deploy/)
# and in the standalone tool repository (<repo>/deploy/).
SOURCES = Path(__file__).resolve().parent / "model_sources"


def main() -> int:
    paths = sorted(SOURCES.rglob("*.bbmodel"))
    if not paths:
        print(f"no .bbmodel under {SOURCES}")
        return 1
    failures = 0
    for path in paths:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status = model_uv_audit.audit(path)
        text = buffer.getvalue().splitlines()
        head = next((line for line in text if line.startswith(path.name)), path.name)
        if status:
            failures += 1
            print("FAIL " + head)
            for line in text:
                if line.startswith("PROBLEM "):
                    print("     " + line)
        else:
            print("ok   " + head)
    print(f"{len(paths) - failures} of {len(paths)} sources clean")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
