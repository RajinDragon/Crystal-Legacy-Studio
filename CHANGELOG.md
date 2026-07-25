## 0.6.5 — Community Launch Syntax Fix

- Fixed the malformed f-string in `sprite_sets.py` that prevented Studio from starting on clean installations.
- Split the bundle-job display calculation into a safe intermediate variable.
- Verified every Python source file with `compileall`.

## 0.6.4 — Requirements README

- Added official download links and PowerShell installation commands.
- Added `requirements.txt`.
- Added package verification and troubleshooting commands.
- Added `docs/INSTALLATION.md`.

# Changelog

## 0.6.3 Community Preview

- Monster Sprite Studio now opens each monster from the highest-priority active layer.
- Preview priority is Working edit, Active deployed Crystal Legacy mod, then untouched MagiciteExport.
- Palette extraction, live preview, Save Recolor As, and Apply & Deploy all begin from the active edited sprite instead of silently reverting to the original.
- Monster Designer uses the same layered preview rule and labels the source as WORKING EDIT, ACTIVE MOD, or ORIGINAL.

## 0.6.2 Community Preview

- Replaced the horizontal ttk pane with a protected three-pane workspace.
- Project Explorer now has a hard minimum width and cannot open fully collapsed.
- Inspector starts compact for every editor tab.
- Startup sash placement is reapplied after window mapping and maximization.
- Added runtime guards that repair accidental zero-width panes without overriding normal resizing.

## 0.6.1

- Fixed the Project Explorer starting fully collapsed on some displays.
- The Explorer now has a nonzero requested width and reapplies its sash position after the window is mapped.

# Changelog

## 0.6.1 Community Preview

- Project Explorer now opens wide enough to display its longest visible entry.
- Inspector remains compact so plugins receive most of the workspace.
- Removed the Level Probe plugin and user-facing Level Probe controls from the distribution.
- Added GitHub-ready setup, plugin development, contribution and known-issue documentation.
- Marked unfinished plugins with `{UNTESTED}`.
- Removed Python cache files from the distribution.
- Retained the v0.5.8 complete monster resource-group deployment experiment for community verification.
