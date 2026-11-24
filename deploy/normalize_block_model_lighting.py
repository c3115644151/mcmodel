#!/usr/bin/env python3
"""Restore vanilla block shading unless a model has an explicit masking exception."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "src/main/resources/assets/pastoral_home/models/block"
REPORT = ROOT / "build/model_lighting_audit.json"
EXCEPTIONS = ROOT / "tools/deploy/model_lighting_exceptions.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if models diverge from vanilla shading")
    args = parser.parse_args()

    models = sorted(MODEL_ROOT.rglob("*.json"))
    if not models:
        raise SystemExit(f"No block models found under {MODEL_ROOT}")

    overrides = json.loads(EXCEPTIONS.read_text(encoding="utf-8")) if EXCEPTIONS.exists() else {}
    changes: list[str] = []
    remaining: list[str] = []
    for path in models:
        data = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(MODEL_ROOT).as_posix()
        override = overrides.get(relative, {})
        changed = False

        # Vanilla defaults are AO=true and face shade=true. Only an explicit
        # false in the exception manifest may disable either for a mask issue.
        requested_ao = override.get("ambientocclusion", True)
        if requested_ao is False:
            if data.get("ambientocclusion") is not False:
                if args.check:
                    remaining.append(f"{relative}: this documented mask exception requires ambientocclusion=false")
                else:
                    data["ambientocclusion"] = False
                    changed = True
        elif data.get("ambientocclusion") is False:
            if args.check:
                remaining.append(f"{relative}: ambientocclusion=false has no documented mask exception")
            else:
                data.pop("ambientocclusion")
                changed = True

        element_overrides = override.get("elements", {})
        whole_model_shade = override.get("shade", True)
        for index, element in enumerate(data.get("elements", [])):
            expected_shade = element_overrides.get(str(index), {}).get("shade", whole_model_shade)
            if expected_shade is False:
                if element.get("shade") is not False:
                    if args.check:
                        remaining.append(f"{relative}: mask exception requires element {index} shade=false")
                    else:
                        element["shade"] = False
                        changed = True
            elif element.get("shade") is False:
                if args.check:
                    remaining.append(f"{relative}: element {index} shade=false has no documented mask exception")
                else:
                    element.pop("shade")
                    changed = True
            elif element.get("shade") is True:
                # Omit redundant true values so the asset uses Minecraft's default.
                if not args.check:
                    element.pop("shade")
                    changed = True

        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changes.append(relative)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "models_scanned": len(models),
        "models_changed": len(changes),
        "changed_models": changes,
        "remaining_shading_issues": remaining,
        "policy": {"vanilla_ambientocclusion": True, "vanilla_element_shade": True},
        "mask_exceptions": overrides,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if remaining:
        print("Block-model shading differs from vanilla without a matching mask exception:")
        print("\n".join(remaining))
        return 1
    if args.check:
        print(f"Block-model lighting check passed: {len(models)} models use vanilla shading or explicit mask exceptions.")
    else:
        print(f"Block-model lighting restored: {len(models)} scanned, {len(changes)} updated; only explicit mask exceptions remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
