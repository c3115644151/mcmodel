#!/usr/bin/env python3
"""Fail if any custom block model disables vanilla shading without a mask exception."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "src/main/resources/assets/pastoral_home/models/block"
EXCEPTIONS = ROOT / "tools/deploy/model_lighting_exceptions.json"
models = sorted(MODEL_ROOT.rglob("*.json"))
assert models, f"No block models found at {MODEL_ROOT}"
overrides = json.loads(EXCEPTIONS.read_text(encoding="utf-8")) if EXCEPTIONS.exists() else {}
issues = []
for path in models:
    data = json.loads(path.read_text(encoding="utf-8"))
    relative = path.relative_to(MODEL_ROOT).as_posix()
    override = overrides.get(relative, {})
    expected_ao = override.get("ambientocclusion", True)
    if expected_ao is False and data.get("ambientocclusion") is not False:
        issues.append(f"{relative}: documented mask requires ambientocclusion=false")
    elif expected_ao is not False and data.get("ambientocclusion") is False:
        issues.append(f"{relative}: ambientocclusion=false has no documented mask exception")

    element_overrides = override.get("elements", {})
    whole_model_shade = override.get("shade", True)
    for index, element in enumerate(data.get("elements", [])):
        expected_shade = element_overrides.get(str(index), {}).get("shade", whole_model_shade)
        if expected_shade is False and element.get("shade") is not False:
            issues.append(f"{relative}: mask exception requires element {index} shade=false")
        elif expected_shade is not False and element.get("shade") is False:
            issues.append(f"{relative}: element {index} shade=false has no documented mask exception")

assert not issues, "\n".join(issues)
assert len(models) >= 400, f"Lighting audit unexpectedly covers only {len(models)} block models"
print(f"Block-model lighting verified: {len(models)} models use vanilla AO/face shading or documented mask exceptions.")
