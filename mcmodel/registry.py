"""The command table: what this toolkit can do, grouped by where it sits in the pipeline.

Every entry names a script that already exists; nothing here re-implements one. The point of the
table is that a person (or an agent) can ask "what can this do" without reading 100 filenames and
guessing which prefix means what. Stage names follow the pipeline, not the author's habits:

    source   read the artist's file and establish the facts a build may rely on
    build    turn those facts into blockstates, models, textures, icons, loot and lang
    gate     assert an invariant; a broken build must fail here, not in a screenshot
    observe  look at the running game, and make that look trustworthy

Anything not listed is legacy: it stays on disk because it documents a dead end, and no gate or
build task runs it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    name: str
    stage: str
    script: str
    summary: str
    ci: bool = False
    needs_game: bool = False
    # Shown by `list` as the shape of the arguments a person has to supply.
    args: tuple[str, ...] = ()
    # Supplied automatically when nobody typed any: a multipart preview script takes different
    # flags per model, and a gate that depends on one must run it the same way every time.
    default_args: tuple[str, ...] = ()
    # False for commands that cannot run without a path or an id, so a batch build skips them
    # instead of failing on a missing argument.
    batch: bool = True
    # Commands that must run first because this one reads their output from build/. Gradle supplies
    # that order through task dependencies; outside Gradle it has to be declared here or the gate
    # fails on a missing intermediate file instead of on the thing it checks.
    requires: tuple[str, ...] = ()
    # Always placed before whatever the person typed. A multi-verb script (model.py) needs its verb
    # first, and prepending it here keeps the command table a table of capabilities rather than a
    # list of shims.
    verb: tuple[str, ...] = ()
    notes: str = ""


COMMANDS: tuple[Command, ...] = (
    # ---------------------------------------------------------------- source
    Command("uv-audit", "source", "audit_model_uv_sources.py",
            "Check every source declares a resolution its uv scaling can be derived from.", ci=True),
    Command("source-view", "source", "model.py",
            "Capture Blockbench's own viewport of a source: the only reference image that counts.",
            verb=("viewport",), args=("--source <bbmodel>", "[--reuse]"), batch=False),
    Command("export-source", "source", "model.py",
            "Blockbench's own java_block export, optionally diffed against the shipped model.",
            verb=("export",), args=("--source <bbmodel>", "[--model <name>]"), batch=False),

    # ----------------------------------------------------------------- build
    # Order matters twice over. Every generator owns its source asset and rewrites src models, so
    # the normalisers have to run after the whole generator set; and prepare-wardrobe-gui draws GUI
    # art from models that are already normalised, which is why it sits past light and particles
    # rather than among the generators. This mirrors the processResources chain in build.gradle.
    Command("prepare-brewing", "build", "prepare_brewing_assets.py",
            "Rebuild brewing barrel and bottle assets."),
    Command("prepare-brewing-gui", "build", "prepare_brewing_gui_art.py",
            "Rebuild brewing GUI art."),
    Command("prepare-entryway", "build", "prepare_entryway_models.py",
            "Rebuild the entryway set: boards, racks, parasol, rug."),
    Command("prepare-paintings", "build", "prepare_wall_painting_variants.py",
            "Rebuild wall painting variants."),
    Command("prepare-planter", "build", "prepare_spruce_planter.py",
            "Rebuild the spruce planter's three layers."),
    Command("prepare-piano", "build", "prepare_piano_models.py",
            "Rebuild the piano's six cell models, key field and palette sheet."),
    Command("prepare-party-lights", "build", "prepare_party_lights_models.py",
            "Rebuild the party light: one shell and one core from the artist's animated sheet."),
    Command("prepare-currency", "build", "prepare_currency_models.py",
            "Rebuild coin piles and their stack states."),
    Command("prepare-rope", "build", "prepare_hanging_rope_models.py",
            "Rebuild hanging rope segments."),
    Command("prepare-basket", "build", "prepare_glow_berry_basket_models.py",
            "Rebuild glow berry basket variants."),
    Command("prepare-wardrobe", "build", "prepare_wardrobe_models.py",
            "Rebuild wardrobe halves and doors."),
    Command("prepare-instruments", "build", "prepare_instrument_models.py",
            "Rebuild the scroll model and the gramophone's OBJ export."),
    Command("norm-light", "build", "normalize_block_model_lighting.py",
            "Remove double darkening where paint and ambient occlusion disagree."),
    Command("norm-particles", "build", "normalize_block_model_particles.py",
            "Point every model's particle texture at an existing file."),
    Command("prepare-wardrobe-gui", "build", "prepare_wardrobe_gui.py",
            "Rebuild the wardrobe GUI art."),
    # normalize_item_icons.py only audits unless it is told --apply, and an audit step that silently
    # writes nothing is worse than no step: the gates then read item definitions no build ever
    # touched. The flag is part of the command, not something to remember.
    Command("norm-icons", "build", "normalize_item_icons.py",
            "Rewrite item definitions so every block item resolves to a real icon.",
            default_args=("--apply",)),

    # Icon previews read generated models, so they sit after the normalisers. Each one writes the
    # silhouette report its gate compares against, which is why the gates name them as requires.
    Command("preview-currency-icons", "build", "preview_currency_item_icons.py",
            "Draw coin pile icons and the silhouette report the currency gate reads."),
    Command("preview-wardrobe-icon", "build", "preview_item_icons.py",
            "Draw the wardrobe item icon and its silhouette report.",
            default_args=("--items", "wardrobe", "--vanilla-reference",
                          "--output", "build/requested_models/wardrobe_item_preview.png",
                          "--report", "build/requested_models/wardrobe_item_preview.json")),
    Command("preview-basket-icon", "build", "preview_item_icons.py",
            "Draw the glow berry basket icon and its silhouette report.",
            default_args=("--items", "glow_berry_basket",
                          "--output", "build/glow_berry_basket_models/item_icon_preview.png",
                          "--report", "build/glow_berry_basket_models/item_icon_preview.json")),

    # One-shot tools: each needs a path or an id, so they run on demand and a batch build skips
    # them. They stay listed because "which tool turns which format" is the question this table
    # exists to answer.
    #
    # Only real entry points are listed. split_model_cells.py, block_item_model.py,
    # item_icon_preview.py and item_icon_proxy.py are modules the generators and the gates import;
    # they have no main(), so listing them as commands sent people to run a file that does nothing
    # on its own. export_free_obj.py has a main() but it hard-codes the record player source, which
    # is why prepare-instruments owns it instead.
    # The packaging step is the one command here that runs Gradle rather than a script, because the
    # artefact under test is the jar itself.
    Command("jar", "build", "gradle:jar",
            "Compile the mod jar so a gate can inspect what actually ships.", batch=False,
            notes="No arguments: it packages whatever src/ currently holds."),
    Command("import-bbmodel", "build", "import_java_block_bbmodel.py",
            "Convert a java_block .bbmodel into a block model on the 0..16 uv grid.", batch=False,
            args=("<source.bbmodel> --block-id <id> --model-out <json>",)),
    Command("import-cube", "build", "import_simple_cube_block.py",
            "Convert a single full-cube .bbmodel into plain block + item assets.", batch=False,
            args=("<source.bbmodel> <block_id>",)),
    Command("split-parts", "build", "split_model_parts.py",
            "Split a model into parts a multipart blockstate can show or hide.", batch=False,
            args=("<model.json> --part <name>=<indices> [--translate <name>=<x,y,z>]",)),
    Command("seated", "build", "create_seated_model.py",
            "Produce a seated variant (flower pot on a stand) from a base model.", batch=False,
            args=("<source.json> <output.json> [--shift <model-px>] [--verify]",)),
    Command("bake-rotation", "build", "bake_rotated_cubes.py",
            "Bake element rotations into explicit geometry where the loader cannot honour them.",
            batch=False, args=("<source.json> --out <json> [--step <degrees>]",)),

    # ------------------------------------------------------------------ gate
    Command("gate-registry", "gate", "test_command_registry.py",
            "The command table still matches the disk, and every gate declares what it needs.",
            ci=True, notes="Reads registry.py and the deploy directory; needs no generated file."),
    Command("gate-imports", "gate", "test_python_imports.py",
            "Every tool script's imports resolve, including the ones that arrive through sys.path.",
            ci=True, notes="Reads the .py files themselves, so it needs nothing built."),
    Command("gate-assets", "gate", "test_requested_model_assets.py",
            "Requested models have blockstates, item models, loot, tags and lang.", ci=True,
            requires=("norm-icons",)),
    Command("gate-bounds", "gate", "test_model_bounds.py",
            "Element bounds stay inside the range the block model format accepts.", ci=True,
            notes="Reads every model in src/, so it is only meaningful after the batch build."),
    Command("gate-slices", "gate", "test_sliced_render_shapes.py",
            "Every sliced blockstate owner renders its model instead of an empty shape.", ci=True,
            notes="Reads every blockstate and its owner class in src/, so it follows the batch build."),
    Command("gate-render-semantics", "gate", "test_render_semantics_gate.py",
            "Opaque shells, draw order and render_type: the three traps that hide a core.", ci=True,
            notes="Reads every model in src/, so it is only meaningful after the batch build."),
    Command("gate-light", "gate", "test_block_model_lighting.py",
            "Ambient occlusion overrides are intentional and local.", ci=True,
            notes="Reads every model in src/, so it is only meaningful after the batch build."),
    Command("gate-particles", "gate", "test_block_model_particles.py",
            "Particle textures resolve.", ci=True, requires=("norm-particles",)),
    Command("gate-lang", "gate", "test_localization_catalog.py",
            "Every registered content name has en_us and zh_cn entries.", ci=True,
            notes="Reads the datagen output in src/generated; rerun gradlew runClientData after adding a name."),
    Command("gate-tab", "gate", "test_creative_tab_coverage.py",
            "Every item lands in a creative tab.", ci=True, requires=("prepare-currency",)),
    Command("gate-party-lights", "gate", "party_lights_report.py",
            "The light still matches its source sheet: geometry, uv, alpha, draw order, states.", ci=True,
            requires=("prepare-party-lights",)),
    Command("gate-piano-keys", "gate", "piano_key_report.py",
            "The keyboard's key widths, gaps, black-key ratio and texture seams.", ci=True,
            requires=("prepare-piano",)),
    Command("gate-instruments", "gate", "test_instrument_models.py",
            "Instrument cell fragments, textures and collision tables.", ci=True,
            requires=("prepare-instruments", "prepare-piano", "norm-icons")),
    Command("gate-entryway", "gate", "test_entryway_models.py",
            "Entryway furniture: geometry, variants, collision, icons.", ci=True,
            requires=("prepare-entryway", "norm-particles", "norm-icons")),
    Command("gate-currency", "gate", "test_currency_assets.py",
            "Coin piles: stack data, blockstates, item models.", ci=True,
            requires=("prepare-currency", "preview-currency-icons", "norm-icons")),
    Command("gate-wardrobe", "gate", "test_wardrobe_assets.py",
            "Wardrobe halves, doors and GUI art.", ci=True,
            requires=("prepare-wardrobe", "prepare-wardrobe-gui", "preview-wardrobe-icon", "norm-icons")),
    Command("gate-rope", "gate", "test_hanging_rope_assets.py",
            "Rope segments connect and terminate correctly.", ci=True,
            requires=("prepare-rope",)),
    Command("gate-basket", "gate", "test_glow_berry_basket_assets.py",
            "Glow berry basket variants and occupancy.", ci=True,
            requires=("prepare-basket", "preview-basket-icon", "norm-icons")),
    Command("gate-outdoor", "gate", "test_recent_outdoor_assets.py",
            "Outdoor set geometry and assets.", ci=True,
            requires=("prepare-planter", "prepare-paintings", "norm-icons")),
    Command("gate-jar", "gate", "test_jar_contents.py",
            "The jar packages the resources, fonts and classes the features need at runtime.", ci=True,
            requires=("jar",)),
    Command("gate-icon-proxies", "gate", "validate_item_icon_proxies.py",
            "Every GUI icon proxy resolves to the model its item definition names.", ci=True,
            requires=("norm-icons",)),
    Command("gate-collision", "gate", "audit_recent_outdoor_collisions.py",
            "Declared collision shapes still cover the models they belong to.", ci=True,
            notes="Reads every model in src/, so it is only meaningful after the batch build."),
    Command("gate-import", "gate", "test_import_java_block_bbmodel.py",
            "The importer's uv scaling and cell slicing stay correct.", ci=True,
            notes="Unit test of the importer: writes to a temporary directory and needs no generated file."),

    # --------------------------------------------------------------- observe
    Command("ship", "observe", "model.py",
            "One piece end to end: generate --mirror, source-difference gate, reload, shoot, census.",
            verb=("ship",), needs_game=True, args=("<piece>",), batch=False),
    Command("shot", "observe", "model.py",
            "The only safe way to sample the game: stage the scene, shoot, crop, colour census.",
            verb=("live",), needs_game=True, args=("--piece <name>", "[--job <json>]", "[--reload]"),
            batch=False),
    Command("sweep", "observe", "model.py",
            "One generator constant, several values, one camera, one labelled comparison sheet.",
            verb=("sweep",), needs_game=True, args=("--piece <name>", "--param <NAME>", "--values a,b,c"),
            batch=False),
    Command("compare", "observe", "model.py",
            "Source vs shipped: viewport/live side by side, or per-face uv and coordinate diff.",
            verb=("compare",), args=("--piece <name>", "[--viewport <png> --live <png>]"), batch=False),
    Command("preview-model", "observe", "model.py",
            "Offline render for geometry only: no mip, no back-face culling, not a visual verdict.",
            verb=("preview",), args=("<models>", "[--raw <bbmodel>]", "[--views front,quarter]"),
            batch=False),
    Command("preview-icons", "observe", "preview_item_icons.py",
            "Render GUI icons and their measured silhouettes."),
    Command("preview-collision", "observe", "preview_collision_profiles.py",
            "Draw each collision profile against its model."),
    Command("reload", "observe", "reload_client_f3t.ps1",
            "Ask the preview client to reload resources; screenshots need ~25 s after this.",
            needs_game=True),
)

BY_NAME = {command.name: command for command in COMMANDS}
STAGES = ("source", "build", "gate", "observe")


def stage_commands(stage: str) -> tuple[Command, ...]:
    return tuple(command for command in COMMANDS if command.stage == stage)


def gate_commands() -> tuple[Command, ...]:
    return tuple(command for command in COMMANDS if command.stage == "gate" and command.ci)
