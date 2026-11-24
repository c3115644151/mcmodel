#!/usr/bin/env python3
"""Build exact visible book-count models and the complete camp-book blockstate.

The art source contains four physical books in each stacked model. This tool
selects those groups into 1/2/3/4-book variants instead of showing the final
four-book mesh after the first stacking interaction.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collision"))
from parse_model import load_cubes


def translate(element: dict, dx: float = 0, dy: float = 0, dz: float = 0) -> None:
    for coordinate in ("from", "to"):
        if coordinate in element:
            element[coordinate] = [element[coordinate][0] + dx,
                                    element[coordinate][1] + dy,
                                    element[coordinate][2] + dz]
    rotation = element.get("rotation")
    if isinstance(rotation, dict) and "origin" in rotation:
        rotation["origin"] = [rotation["origin"][0] + dx,
                              rotation["origin"][1] + dy,
                              rotation["origin"][2] + dz]


def model_subset(source: dict, indices: list[int], offsets: dict[int, tuple[float, float, float]]) -> dict:
    result = copy.deepcopy(source)
    remap = {old: new for new, old in enumerate(indices)}
    result["elements"] = []
    for index in indices:
        element = copy.deepcopy(source["elements"][index])
        translate(element, *offsets.get(index, (0, 0, 0)))
        result["elements"].append(element)
    group_children = {}
    for old_index in indices:
        group_children.setdefault(old_index // 4, []).append(remap[old_index])
    result["groups"] = [
        {"name": f"book_{group_index}", "children": children}
        for group_index, children in sorted(group_children.items())
    ]
    return result


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_blockstate() -> dict:
    rotations = {"north": 0, "east": 90, "south": 180, "west": 270}
    variants = {}
    for facing, turn in rotations.items():
        for count in (1, 2, 3, 4):
            for pose in ("ground_single", "ground_stack", "open", "upright_single", "upright_stack",
                         "upright_open", "wall_single", "wall_stack", "wall_open"):
                if pose in ("ground_single", "open"):
                    model, xturn, yturn = ("book_ground_stack_single" if pose == "ground_single" else "book_open", 0, turn)
                elif pose == "upright_single":
                    model, xturn, yturn = "book_upright_stack_single", 0, turn + 270
                elif pose == "upright_open":
                    model, xturn, yturn = "book_open", 90, turn + 180
                elif pose == "wall_single":
                    model, xturn, yturn = "book_wall_stack_single", 0, turn + 270
                elif pose == "wall_open":
                    # FACING is the outward face clicked by the player. X=90 gives
                    # the page a south-facing normal, so rotate it 180 degrees from support yaw.
                    model, xturn, yturn = "book_open", 90, turn + 180
                else:
                    stage = max(2, count)
                    if pose == "upright_stack":
                        model = "book_upright_stack" if stage == 4 else f"book_upright_stack_{stage}"
                    elif stage == 4:
                        model = "book_ground_stack" if pose == "ground_stack" else "book_wall_stack"
                    else:
                        model = ("book_ground_stack_" if pose == "ground_stack" else "book_wall_stack_") + str(stage)
                    xturn, yturn = 0, turn if pose == "ground_stack" else turn + 270

                value = {"model": f"pastoral_home:block/{model}"}
                if xturn:
                    value["x"] = xturn
                if yturn:
                    value["y"] = yturn % 360
                variants[f"facing={facing},pose={pose},count={count}"] = value
    return {"variants": variants}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ground_model", type=Path, help="Exported book_ground_stack.json")
    parser.add_argument("wall_model", type=Path, help="Exported book_wall_stack.json")
    parser.add_argument("output_dir", type=Path, help="Destination models/block directory")
    parser.add_argument("blockstate", type=Path, help="Destination blockstates/camp_book.json")
    args = parser.parse_args()

    ground = json.loads(args.ground_model.read_text(encoding="utf-8"))
    wall = json.loads(args.wall_model.read_text(encoding="utf-8"))
    if len(ground.get("elements", [])) != 16 or len(wall.get("elements", [])) != 16:
        raise SystemExit("expected four books (four elements each) in both stacked sources")
    output_wall = (args.output_dir / "book_wall_stack.json").resolve()
    if args.wall_model.resolve() == output_wall:
        raise SystemExit("use the original exported wall-stack JSON as input, not the generated output file")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.blockstate.parent.mkdir(parents=True, exist_ok=True)

    # Ground source group order: raised flat book (0), tilted top (1), bottom book (2), upright book (3).
    group0 = list(range(0, 4))
    group1 = list(range(4, 8))
    group2 = list(range(8, 12))
    group3 = list(range(12, 16))
    # Keep a 0.05-model-unit clearance over the support face to prevent coplanar flicker.
    single_offsets = {i: (2.5, -3.35, 0) for i in group0}
    write(args.output_dir / "book_ground_stack_single.json",
          model_subset(ground, group0, single_offsets))

    ground_pair_groups = group0 + group2
    pair_offsets = {i: (2.5, 0, 0) for i in group0}
    pair_offsets.update({i: (2.5, -0.25, 0) for i in group2})
    write(args.output_dir / "book_ground_stack_2.json",
          model_subset(ground, ground_pair_groups, pair_offsets))

    ground_triple_groups = group0 + group1 + group2
    triple_offsets = {i: (2.5, 0, 0) for i in group0 + group1}
    triple_offsets.update({i: (2.5, -0.25, 0) for i in group2})
    write(args.output_dir / "book_ground_stack_3.json",
          model_subset(ground, ground_triple_groups, triple_offsets))

    # Wall source books are laid along local X, with group3 nearest the eventual
    # mounting wall. A +90 degree blockstate yaw turns their covers outward.
    wall_group0 = list(range(0, 4))
    wall_group1 = list(range(4, 8))
    wall_group2 = list(range(8, 12))
    wall_group3 = list(range(12, 16))
    # X becomes world depth after the base quarter-turn. Keep a 0.05px gap from the wall face.
    wall_offsets = {i: (-0.5, 0, -1.25) for i in range(16)}
    write(args.output_dir / "book_wall_stack_single.json",
          model_subset(wall, wall_group3, wall_offsets))
    write(args.output_dir / "book_wall_stack_2.json",
          model_subset(wall, wall_group3 + wall_group2, wall_offsets))
    write(args.output_dir / "book_wall_stack_3.json",
          model_subset(wall, wall_group3 + wall_group2 + wall_group0, wall_offsets))
    write(args.output_dir / "book_wall_stack.json",
          model_subset(wall, wall_group3 + wall_group2 + wall_group0 + wall_group1, wall_offsets))

    # A floor-standing upright pile uses the same authored books as the wall pile,
    # but recenters each count-stage in its cell instead of anchoring to the wall.
    wall_names = {
        "single": "book_wall_stack_single",
        "2": "book_wall_stack_2",
        "3": "book_wall_stack_3",
        "4": "book_wall_stack",
    }
    for stage, source_name in wall_names.items():
        source_path = args.output_dir / f"{source_name}.json"
        upright = json.loads(source_path.read_text(encoding="utf-8"))
        cubes = load_cubes(str(source_path))
        x_values = [point[0] for cube in cubes for point in cube.get("corners", [])]
        offset_x = 8.0 - (min(x_values) + max(x_values)) / 2.0
        for element in upright.get("elements", []):
            translate(element, dx=offset_x)
        upright_name = ("book_upright_stack_single" if stage == "single"
                        else "book_upright_stack" if stage == "4"
                        else f"book_upright_stack_{stage}")
        write(args.output_dir / f"{upright_name}.json", upright)

    write(args.blockstate, make_blockstate())
    print("Generated ground, upright, legacy-wall book stages, and all facing/pose/count blockstates.")


if __name__ == "__main__":
    main()
