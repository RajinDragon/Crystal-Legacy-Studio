# Getting Started

## 1. Prepare Final Fantasy I Pixel Remaster

Select the game root containing:

```text
FINAL FANTASY.exe
BepInEx\
FINAL FANTASY_Data\StreamingAssets\Magicite\
FINAL FANTASY_Data\StreamingAssets\MagiciteExport\
```

`MagiciteExport` is the untouched reference layer. Studio reads from it but must not write to it.

## 2. Install Python

Install Python 3.11 or newer for Windows. During setup, enable **Add Python to PATH**. Tkinter must be included. The standard python.org Windows installer includes Tkinter by default.

The launcher installs these packages when missing:

```text
Pillow
cryptography
tkinterdnd2
lz4
```

`pytest` is included for developers and automated tests.

## 3. Run Studio

Run:

```text
Start Crystal Legacy Studio.bat
```

The launcher checks Python, installs dependencies from `requirements.txt`, then starts `main.py`.

## 4. Open the project

Choose the FF1PR game root. Studio creates or uses:

```text
BepInEx\Crystal Legacy\Working\
```

When an active mod already exists at:

```text
FINAL FANTASY_Data\StreamingAssets\Magicite\Crystal Legacy\
```

Studio treats it as the installed project state and adopts it into the working project.

## 5. How files are resolved

Studio reads files in this order:

1. Working copy
2. Active `Magicite\Crystal Legacy` mod
3. Read-only `MagiciteExport`

This allows a project to contain only changed files while preserving the original game data as a fallback.

## 6. Save and test

Use **Save** or an editor-specific save command. Studio writes working data and deploys it to the Crystal Legacy mod folder. Restart the game when testing assets that Unity may have cached.

Keep backups. Community Preview builds may still stage incomplete or invalid data.
