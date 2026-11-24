from pathlib import Path


CONTRACT = Path(__file__).with_name("IMPLEMENTATION_CONTRACT.md")
CLI = Path(__file__).with_name("cli.py")
LAMP = Path(__file__).parents[2] / "src/main/java/com/pastoralhome/block/FloorLampBlock.java"


def main():
    text = CONTRACT.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    lamp = LAMP.read_text(encoding="utf-8")
    for required in (
        "Selection and physical collision",
        "Selection/hit outline follows the visible model",
        "Sound is assessed",
        "Multi-cell geometry",
        "GameTests",
        "DONE",
        "N/A",
        "BLOCKED",
    ):
        assert required in text, f"implementation contract omits {required!r}"
    assert "print_implementation_contract()" in cli
    assert "CONTRACT_PATH" in cli
    assert "SoundEvents.LEVER_CLICK" in lamp and "SoundSource.BLOCKS" in lamp
    print("Deployment contract covers rendering, separate collision/selection, lifecycle, interactions/sound, content, and tests.")


if __name__ == "__main__":
    main()
