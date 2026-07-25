# Plugin Development

Crystal Legacy Studio discovers plugins by scanning the top-level `Plugins` folder at startup.

## Minimal structure

```text
Plugins\MyPlugin\
    plugin.json
    plugin.py
```

## Manifest

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "entry": "plugin.py",
  "explorer_path": ["Community"],
  "label": "My Tool",
  "description": "Example community plugin.",
  "status": "preview"
}
```

`explorer_path` determines where the entry appears. Examples:

```json
["Game Data"]
["Sprite Studio"]
["Distribution"]
["Community", "Experimental"]
```

## Entry module

Use the included `Plugin SDK/ExamplePlugin` as the starting point. A plugin registers through the host API exposed by the shell. Do not reach into arbitrary `MainWindow` fields or assume paths such as `project_root` exist.

The shell owns:

- current project and game profile
- game-root validation
- working, reference and live deployment paths
- logging and inspector services
- workspace tabs
- package and deployment services

Plugins should request these capabilities through the supplied API/context.

## Design rules

1. Never write to `MagiciteExport`.
2. Stage changes in the working project first.
3. Preserve complete Magicite resource groups and their key metadata when required.
4. Use translated labels in the UI whenever a message key can be resolved.
5. Put risky or unfinished tools behind a visible `{UNTESTED}` label.
6. Do not bundle Cheat Engine tables or depend on Cheat Engine at runtime.
7. Keep plugin data under the project working directory, not inside the Studio installation folder.
8. Treat paths as game-root-relative; do not hard-code a drive letter.

## Installing during development

Copy the plugin folder to `Plugins`, restart Studio, and check **Core → Installed Plugins**. Removing the folder and restarting uninstalls it.

## Testing checklist

- Plugin loads with no traceback.
- Project Explorer entry appears at the declared path.
- Opening and closing the page does not leave dead Tk widgets or callbacks.
- No write occurs in `MagiciteExport`.
- All generated paths remain inside the selected game/project roots.
- Saving a project twice produces the same result.
- Errors are logged and shown to the user without crashing the shell.
- The plugin still behaves correctly when another optional plugin is removed.

## Pull requests

Include:

- plugin purpose
- tested Studio version
- tested FF1PR files/resources
- screenshots
- known limitations
- instructions for reproducing the test
