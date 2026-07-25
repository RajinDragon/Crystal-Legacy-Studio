# Known Issues and Test Status

## Critical / active investigation

### Monster recolor deployment

The palette editor can create and stage a recolored PNG. The current deployment pass seeds the complete original monster resource group before replacing the selected image. This still requires in-game verification across encounters and game restarts. If enemies become invisible, remove the affected working/live monster resource group and restore it from a backup before continuing.

### Job permissions

Weapon, armor and magic permissions are not considered solved. Earlier working behavior edited existing native `job_group.csv` rows. Creating additional permission group IDs can be ignored by FF1PR or break loading. This area needs reverse engineering and tests before community release.

## Preview limitations

- Some generated overworld previews may fail when their atlas and `Default_00.spritedata` relationship cannot be reconstructed.
- Unity/FF1PR may cache already-loaded artwork. Restart the game when a new battle does not show a recently deployed asset.
- Imported third-party mods can use unexpected bundle layouts or naming conventions.

## Plugins marked `{UNTESTED}`

These plugins are included for development and contributor testing, not as completed features:

- Direct Game Bundle Workbench
- Encounter Designer
- Package Manager
- Weapon Editor

## General preview limitations

- No signed installer or automatic updater.
- Plugin API is still evolving and may change before 1.0.
- Not every field has a translated user-facing label.
- Import conflict handling is incomplete in some editors.
- Back up working and live mod folders before testing.
