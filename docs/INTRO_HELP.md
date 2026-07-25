# Introduction to Crystal Legacy Studio

Crystal Legacy Studio is intended to make FF1PR modding feel closer to an RPG creation tool than a collection of raw CSV editors.

The left Project Explorer contains shell pages and installed plugins. Character and monster visual tools live under **Sprite Studio**. Game data editors live under **Game Data**. Package tools live under **Distribution**.

The central workspace uses tabs. Close ordinary pages when finished; the Welcome page may remain pinned. The right Inspector shows information about the currently selected record or asset. The bottom Output panel records file reads, writes, validation results and plugin errors.

A safe workflow is:

1. Open the game root.
2. Confirm the working and reference paths in the Inspector or Project page.
3. Open one editor.
4. Make a small change.
5. Save and inspect the Output log.
6. Restart the game and test.
7. Back up a known-good project before larger changes.

For sprite work, save imported battle and overworld assets as reusable library entries, pair them when appropriate, and use a new name for recolors instead of overwriting the source appearance.
