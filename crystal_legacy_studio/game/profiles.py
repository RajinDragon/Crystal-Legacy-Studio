from dataclasses import dataclass

@dataclass(frozen=True)
class GameProfile:
    profile_id: str
    roman: str
    display_name: str
    folder_hint: str
    executable_names: tuple[str, ...]
    data_dir_names: tuple[str, ...]

GAME_PROFILES: tuple[GameProfile, ...] = (
    GameProfile('ff1pr-steam-windows', 'I', 'Final Fantasy I Pixel Remaster', 'FINAL FANTASY PR', ('FINAL FANTASY.exe','FINAL FANTASY PR.exe'), ('FINAL FANTASY_Data',)),
    GameProfile('ff2pr-steam-windows', 'II', 'Final Fantasy II Pixel Remaster', 'FINAL FANTASY II PR', ('FINAL FANTASY II.exe','FINAL FANTASY II PR.exe'), ('FINAL FANTASY II_Data',)),
    GameProfile('ff3pr-steam-windows', 'III', 'Final Fantasy III Pixel Remaster', 'FINAL FANTASY III PR', ('FINAL FANTASY III.exe','FINAL FANTASY III PR.exe'), ('FINAL FANTASY III_Data',)),
    GameProfile('ff4pr-steam-windows', 'IV', 'Final Fantasy IV Pixel Remaster', 'FINAL FANTASY IV PR', ('FINAL FANTASY IV.exe','FINAL FANTASY IV PR.exe'), ('FINAL FANTASY IV_Data',)),
    GameProfile('ff5pr-steam-windows', 'V', 'Final Fantasy V Pixel Remaster', 'FINAL FANTASY V PR', ('FINAL FANTASY V.exe','FINAL FANTASY V PR.exe'), ('FINAL FANTASY V_Data',)),
    GameProfile('ff6pr-steam-windows', 'VI', 'Final Fantasy VI Pixel Remaster', 'FINAL FANTASY VI PR', ('FINAL FANTASY VI.exe','FINAL FANTASY VI PR.exe'), ('FINAL FANTASY VI_Data',)),
)

PROFILE_BY_ID = {p.profile_id: p for p in GAME_PROFILES}
PROFILE_BY_DISPLAY = {p.display_name: p for p in GAME_PROFILES}

def get_profile(profile_id: str) -> GameProfile:
    return PROFILE_BY_ID.get(profile_id, GAME_PROFILES[0])
