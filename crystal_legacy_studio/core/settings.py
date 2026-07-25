from dataclasses import dataclass, asdict, field
from pathlib import Path
import json
from .atomic import atomic_write_text

DEFAULT_PROFILE='ff1pr-steam-windows'

@dataclass
class StudioSettings:
    theme:str='dark'; window_geometry:str='1440x900'; last_project:str=''; recent_projects:list[str]=field(default_factory=list)
    game_root:str=''; workspace_root:str=''; setup_completed:bool=False
    game_installations:dict[str,str]=field(default_factory=dict)
    active_game_profile:str=DEFAULT_PROFILE
    show_only_active_game:bool=True
    left_pane_width:int=260; inspector_width:int=330; output_height:int=220

    def normalize(self):
        # Migrate Alpha 11h's single FF1 path into the multi-game installation map.
        if self.game_root and DEFAULT_PROFILE not in self.game_installations:
            self.game_installations[DEFAULT_PROFILE]=self.game_root
        if self.active_game_profile not in self.game_installations and self.game_installations:
            self.active_game_profile=next(iter(self.game_installations))
        if self.active_game_profile in self.game_installations:
            self.game_root=self.game_installations[self.active_game_profile]
            self.workspace_root=str(Path(self.game_root)/'BepInEx'/'Crystal Legacy'/'Working')
        self.setup_completed=bool(self.game_installations)
        return self

class SettingsStore:
    def __init__(self,base_dir=None): self.base_dir=base_dir or Path.home()/'.crystal-legacy-studio'; self.path=self.base_dir/'settings.json'
    def load(self):
        if not self.path.exists(): return StudioSettings()
        try:
            p=json.loads(self.path.read_text()); allowed=StudioSettings.__dataclass_fields__.keys(); return StudioSettings(**{k:v for k,v in p.items() if k in allowed}).normalize()
        except Exception: return StudioSettings()
    def save(self,s):
        s.normalize(); atomic_write_text(self.path,json.dumps(asdict(s),indent=2))
