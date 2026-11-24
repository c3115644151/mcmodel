# Model implementation contract (read for every model)

Treat every section below as a required implementation decision. Mark each item
`DONE`, `N/A — reason`, or `BLOCKED — reason` before calling a model complete.
Do not infer that a generated collision shape covers selection, or that a model
import alone supplies any of these behaviors.

## 1. Geometry and rendering
- Source groups, variants, pivots, UVs, textures, animation frames, and intended
  world-space offset are accounted for.
- Render state and model geometry match in all four facings and every state.
- Multi-cell geometry has an explicit owner/render strategy. Every occupied
  cell has a documented target policy: a local hit shape for meaningful geometry,
  or intentionally empty selection for thin-sheet-only cells. Whole-structure
  break behavior is tested from each cell intended to be targetable.
- GUI, hand, ground, and placed display contexts have been reviewed separately.
- Audit model lighting against the authored texture: distinguish paint baked into
  the texture from engine-generated ambient occlusion and direction-dependent face
  shading. Disable `ambientocclusion` or element `shade` only for the affected
  model parts when comparison confirms double-darkening; never apply the change
  globally to unrelated furniture. Add an asset regression for every intentional
  lighting override.

## 2. Selection and physical collision (separate decisions)
- Selection/hit outline follows the visible model closely enough to interact
  with every intended part and occupied cell.
- Physical collision is designed independently: omit foliage, thin sheets,
  decorative stands, or other pass-through parts when intended; avoid air-heavy
  envelopes when the model permits tighter boxes.
- Preview both outlines distinctly and compare against the textured model.
- Validate model coverage, air intrusion, cell boundaries, rotations, and the
  actual Java `getShape`/`getCollisionShape` definitions.
- Preserve Blockbench `inflate` during import and audit coplanar overlapping faces;
  intentionally inset/outset layers must not collapse into z-fighting geometry.
- Keep authored canopy geometry unchanged. Selection may cover a full thin canopy
  while physical collision excludes it; document and test both policies separately.

## 3. Placement and lifecycle
- Placement face, orientation, floor/wall support, replaceability, height limits,
  waterlogging, neighbor updates, and survival rules are considered.
- For multi-cell structures, placement reserves all cells; breaking any cell,
  support loss, drops, creative mode, and neighbor updates are tested.
- Connections, inherited state, cleanup, and placement ordering are tested at
  boundaries and beyond the smallest example configuration.

## 4. Interaction and feedback
- Every right-click, sneak action, inventory action, GUI, state change, and
  entity interaction has an explicit behavior or an explicit N/A decision.
- Sound is assessed for placement, use/toggle, opening/closing, break, and other
  user-visible actions. Reuse a related vanilla/mod sound when appropriate;
  explicitly record why passive models need no custom sound.
- Light emission, redstone, fluid behavior, seating/sleeping, storage, and
  animation are each assessed when relevant; do not silently omit a mechanism.
- For seats, mount points, sleepers, and camera anchors, render the player and
  eye/look marker against the imported model with `preview_rider_placement.py`.
  Keep a JSON rider profile and a regression test synchronized with the Java
  placement values; inspect all four facings before client verification.

## 5. Content and verification
- Block/item registration, creative tab, language keys, loot, tags, recipes,
  blockstates, item definitions, model/texture references, and icon proxy are
  checked for applicability and completeness.
- Add GameTests for state transitions, placement/removal, multi-cell behavior,
  collision/selection, drops, sound-triggering actions where observable, and
  edge cases. Run asset/tool audits and the relevant GameTests before delivery.
- Do not start the interactive client unless the user explicitly requests it.

## Completion record
For this model, list each section and its `DONE`, `N/A — reason`, or
`BLOCKED — reason` result in the deployment notes. Unanswered sections mean the
model is not complete.

## Automatic gates

The entryway model batch is wired into the ordinary Gradle path: `prepareEntrywayModels`
runs before resource processing/model validation, and `auditEntrywayModels` runs
after `jar` as part of `check`. The audit fails the build for stale/missing
models, UVs, multiblock state coverage, particle/entity-language/loot resources, icon
proxy bounds, or missing packaged assets. A model with geometry crossing a cell
must also have a runtime structure test that hits the upper/helper cell and
checks that its local outline/collision stays within the owning cell.

These gates currently cover the entryway batch. When another model batch is
added, register its assets and runtime contract in an equivalent audit path;
do not rely on a reminder in chat or on manually running a helper script.
