#!/usr/bin/env python3
"""Build the notebook editor background; notice paper models come from BBModel."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src/main/resources/assets/pastoral_home"
SOURCE = ROOT / "tools/deploy/model_sources/entryway/paper_notebook_base.png"


def make_gui():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"missing authored parchment base {SOURCE}")
    image = Image.open(SOURCE).convert("RGBA").resize((256, 224), Image.Resampling.LANCZOS)
    output = ASSETS / "textures/gui/paper_notebook.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    make_gui()
    print("Generated notebook editor background; notice paper geometry is imported from its BBModel source.")
