# Crystal Legacy Studio

Crystal Legacy Studio is a Windows desktop modding platform for **Final Fantasy I Pixel Remaster (Steam)**. The application uses a stable shell plus folder-installed plugins so contributors can work on separate editors without rebuilding the whole program.

> **Release state:** Community Preview. Back up your game and mod folders before testing. Items marked `{UNTESTED}` are included for contributor testing and should not be treated as production-ready.

## What this preview includes

- Project and FF1PR game-root detection
- Read-only `MagiciteExport` reference data
- Writable BepInEx working project
- Deployment to `StreamingAssets\Magicite\Crystal Legacy`
- Folder-discovered plugins
- Character battle/overworld sprite importing, pairing, previews and recoloring
- Monster palette recoloring and resource-group staging
- Job, item, armor, magic and monster data editors
- Asset browsing and plugin management

## Requirements

- Windows 10 or 11
- Final Fantasy I Pixel Remaster installed through Steam
- Python 3.11 or newer, including Tkinter
- Internet access for the first dependency installation, or the required Python packages installed manually
- BepInEx in the FF1PR game folder
- Extracted reference data at `FINAL FANTASY_Data\StreamingAssets\MagiciteExport`
- Active Magicite mod folder at `FINAL FANTASY_Data\StreamingAssets\Magicite`

Python dependencies are listed in `requirements.txt` and are installed by the launcher when missing.

## Start the Studio

1. Extract the archive. Keep the complete `Crystal Legacy Studio` folder together.
2. Run `Start Crystal Legacy Studio.bat`.
3. Select the FF1PR game root when prompted. The correct folder contains `FINAL FANTASY.exe`.
4. Confirm the detected BepInEx, Magicite and MagiciteExport paths.
5. Open an editor from Project Explorer.
6. Use **Save** to commit and deploy working changes.

Detailed setup: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

## Plugin installation

Copy a complete plugin folder into:

```text
Crystal Legacy Studio\Plugins\
```

Restart Studio. The plugin appears at the Project Explorer location declared by its `plugin.json` manifest. Remove the folder and restart to uninstall it. Project data is not removed when a plugin is uninstalled.

Plugin development guide: [docs/PLUGIN_DEVELOPMENT.md](docs/PLUGIN_DEVELOPMENT.md)

## Important folders

```text
<Game Root>\BepInEx\Crystal Legacy\Working\
    Studio working project and reusable sprite libraries

<Game Root>\FINAL FANTASY_Data\StreamingAssets\MagiciteExport\
    Read-only reference data; Studio must never overwrite this folder

<Game Root>\FINAL FANTASY_Data\StreamingAssets\Magicite\Crystal Legacy\
    Deployed playable mod

<Game Root>\Crystal Legacy\Import\
<Game Root>\Crystal Legacy\Export\
<Game Root>\Crystal Legacy\Backups\
```

## Current cautions

- Monster recolor deployment is under active testing. A complete resource group is now staged, but testers should verify visibility and palette changes after restarting the game.
- Job equipment and magic permission behavior is not considered solved. Native FF1PR permission rows must be preserved; do not rely on newly created permission groups.
- Bundle editing and package workflows labeled `{UNTESTED}` need contributor verification.
- The application is a Python community preview, not a signed Windows installer.

See [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) before reporting a bug.

## Contributing

Please create one plugin or focused shell change per pull request. Include reproduction steps, screenshots where useful, and a note describing which FF1PR files were read or written. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

A project license has not yet been selected by the repository owner. Add an appropriate `LICENSE` file before treating this repository as generally licensed open-source software.

## Requirements and installation

### Required

- **Windows 10 or Windows 11, 64-bit**
- **Final Fantasy I Pixel Remaster for Windows/Steam**
- **Python 3.12 or newer, 64-bit**
- The game must already contain the folders Studio uses:
  - `BepInEx\`
  - `FINAL FANTASY_Data\StreamingAssets\Magicite\`
  - `FINAL FANTASY_Data\StreamingAssets\MagiciteExport\`

Python download:

- https://www.python.org/downloads/windows/

During Python installation, enable:

```text
Add python.exe to PATH
```

### Install Python with PowerShell

Open **PowerShell as Administrator** and run one of these commands.

Using Windows Package Manager:

```powershell
winget install --id Python.Python.3.12 -e
```

Or install the newest available Python 3 release:

```powershell
winget search Python.Python
```

After installation, close and reopen PowerShell, then verify:

```powershell
py --version
py -0p
```

### Install Studio packages

Open PowerShell inside the extracted `Crystal Legacy Studio` folder:

```powershell
cd "B:\Crystal Legacy Workspace\Crystal Legacy Studio"
```

Install all required packages from the included file:

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

The current package list is:

```powershell
py -m pip install Pillow lz4
```

Verify the packages:

```powershell
py -c "from PIL import Image; import lz4.block; print('Crystal Legacy Studio requirements are installed.')"
```

### Start Studio

Recommended:

```text
Start Crystal Legacy.bat
```

PowerShell alternative:

```powershell
py main.py
```

### Optional development tools

Git for Windows:

- https://git-scm.com/download/win

```powershell
winget install --id Git.Git -e
```

GitHub Desktop:

- https://desktop.github.com/download/

```powershell
winget install --id GitHub.GitHubDesktop -e
```

Visual Studio Code:

- https://code.visualstudio.com/download

```powershell
winget install --id Microsoft.VisualStudioCode -e
```

### Quick environment check

Run this from the Studio folder:

```powershell
$ErrorActionPreference = "Stop"

Write-Host "Checking Python..."
py --version

Write-Host "Checking Pillow..."
py -c "from PIL import Image; print('Pillow OK')"

Write-Host "Checking lz4..."
py -c "import lz4.block; print('lz4 OK')"

Write-Host "Checking Studio source..."
py -m compileall -q .

Write-Host "Environment check passed."
```

### Common installation problems

**`py` is not recognized**

Install Python from the official Windows download page or with `winget`, ensure Python is added to `PATH`, and reopen PowerShell.

**`ModuleNotFoundError: No module named 'PIL'`**

```powershell
py -m pip install Pillow
```

**`ModuleNotFoundError: No module named 'lz4'`**

```powershell
py -m pip install lz4
```

**PowerShell cannot run the launcher**

The included launcher is a `.bat` file and normally does not require a PowerShell execution-policy change. Run it from File Explorer or use:

```powershell
cmd /c "Start Crystal Legacy.bat"
```

**Studio cannot find the game**

Select the Final Fantasy I Pixel Remaster root folder—the folder containing `FINAL FANTASY.exe`—not `FINAL FANTASY_Data` and not the `Magicite` folder.

> Studio must never write to `MagiciteExport`. That folder is the untouched read-only reference source.
