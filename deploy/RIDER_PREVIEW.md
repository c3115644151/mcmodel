# Rider-position preview

Use this tool to inspect the effective passenger or sleeper position before
launching Minecraft. It draws the imported model and the exact player entity
AABB in four views, marks the eye point in yellow, and draws the camera ray. It
supports seated blocks, beds with multiple sleep spots, and all four facings.
It intentionally does not fabricate a skinned avatar or animation pose.

```powershell
python tools/deploy/preview_rider_placement.py telescope --facing all
python tools/deploy/preview_rider_placement.py oak_high_back_chair --facing north
python tools/deploy/preview_rider_placement.py bed --facing all
```

Profiles live in `tools/deploy/rider_profiles/`. Seat profiles use the exact
Java seat origin and net passenger-foot attachment. `SeatEntity` adds the
passenger's `VEHICLE` attachment to the seat's `PASSENGER` point; vanilla then
subtracts that same attachment when positioning the player. The resulting feet
position is the seat origin plus the 0.01-block top of the seat entity. The
preview draws the vanilla standing player AABB (0.6 × 1.8 blocks) and its 1.62
block eye height. Telescope view also shifts the rendered Camera 0.5 block
forward along the current view ray from the player's eye to the eyepiece; the
preview shows the player eye in yellow and the lens camera origin in cyan.
Sleeping profiles use the vanilla sleeping AABB (0.2 × 0.2 blocks) and 0.2-block
eye height. Each preview also reports the actual model
part dimensions, classic/slim arm widths, the 0.9375 render scale, and the
passenger leg rotation verified in the Minecraft 26.1.2 client classes.

The Python tests run `javap` against the locked 26.1.2 client JAR to compare the
player dimensions, eye height, render scale, model and passenger pose values.
They also compare telescope placement with Java seat code, chair/sofa/stool
heights with `SeatEntity.sit`, and bed height with `BedBlock.SLEEPING_Y`. The
preview is a geometry and camera-position diagnostic, not an in-game screenshot,
texture, lighting render, or fabricated avatar animation.
