# Crystal Legacy Studio Installation

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
