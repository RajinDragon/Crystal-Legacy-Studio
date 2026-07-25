from dataclasses import dataclass
from pathlib import Path
from crystal_legacy_studio.game.profiles import GAME_PROFILES, get_profile

@dataclass
class GameInstallation:
    profile_id: str
    root: Path
    executable: Path | None
    data_dir: Path | None
    streaming_assets: Path | None
    magicite_export: Path | None
    magicite_dir: Path | None
    bepinex_dir: Path | None
    plugins_dir: Path | None
    mods_dir: Path | None

    @property
    def is_valid_game(self): return bool(self.executable and self.data_dir and self.streaming_assets)
    @property
    def is_valid_crystal_legacy_root(self):
        return bool(self.is_valid_game and self.magicite_export and self.magicite_export.is_dir() and self.magicite_dir and self.magicite_dir.is_dir() and self.bepinex_dir and self.bepinex_dir.is_dir())
    @property
    def has_magicite_export(self): return bool(self.magicite_export and self.magicite_export.is_dir())
    @property
    def has_magicite(self): return bool(self.magicite_dir and self.magicite_dir.is_dir())
    @property
    def has_bepinex(self): return bool(self.bepinex_dir and self.bepinex_dir.is_dir())

class GameDetector:
    def inspect(self, root: Path, profile_id: str='ff1pr-steam-windows'):
        profile=get_profile(profile_id); root=root.expanduser().resolve()
        exe=next((root/n for n in profile.executable_names if (root/n).is_file()),None)
        data=next((root/n for n in profile.data_dir_names if (root/n).is_dir()),None)
        streaming=data/'StreamingAssets' if data else None; streaming=streaming if streaming and streaming.is_dir() else None
        export=streaming/'MagiciteExport' if streaming else None; export=export if export and export.is_dir() else None
        magicite=streaming/'Magicite' if streaming else None; magicite=magicite if magicite and magicite.is_dir() else None
        bepinex=root/'BepInEx'; bepinex=bepinex if bepinex.is_dir() else None
        plugins=bepinex/'plugins' if bepinex else None; plugins=plugins if plugins and plugins.is_dir() else None
        mods=root/'Mods'; mods=mods if mods.is_dir() else None
        return GameInstallation(profile_id,root,exe,data,streaming,export,magicite,bepinex,plugins,mods)

    def auto_detect(self, profile_id='ff1pr-steam-windows'):
        profile=get_profile(profile_id)
        candidates=[Path(r'C:\Program Files (x86)\Steam\steamapps\common')/profile.folder_hint,Path(r'C:\Program Files\Steam\steamapps\common')/profile.folder_hint]
        candidates += [Path(fr'{d}:\SteamLibrary\steamapps\common')/profile.folder_hint for d in 'BCDEFGHIJKLMNOPQRSTUVWXYZ']
        for root in candidates:
            if root.exists():
                result=self.inspect(root,profile_id)
                if result.is_valid_crystal_legacy_root:return result
        return None

    def identify(self, root: Path):
        for profile in GAME_PROFILES:
            result=self.inspect(root,profile.profile_id)
            if result.is_valid_game:return result
        return None

def is_inside(child: Path,parent: Path):
    try: child.resolve().relative_to(parent.resolve()); return True
    except ValueError:return False
