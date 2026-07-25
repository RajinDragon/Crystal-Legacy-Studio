from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import csv, json, math, shutil, datetime

BOOST_FIELDS = ("hp","mp","attack","defense","accuracy_rate","evasion_rate","magic","ability_attack","ability_defense","magic_evasion_rate","agility","exp","gill","drop_rate")

@dataclass
class BoostResult:
    processed:int
    changed:int
    profile_path:Path|None = None


def _num(value:str)->int:
    try:return int(value or 0)
    except (TypeError,ValueError):return 0


def boosted_rows(rows, multipliers, additions=None, include_bosses=True, include_normal=True, preserve_zero=True, round_up=True, caps=None):
    additions=additions or {}; caps=caps or {}
    out=[]; changed=0; processed=0
    for source in rows:
        row=dict(source); is_boss=_num(row.get("boss","0")) != 0
        if (is_boss and not include_bosses) or ((not is_boss) and not include_normal):
            out.append(row); continue
        processed += 1
        row_changed=False
        for field,mul in multipliers.items():
            if field not in row: continue
            old=_num(row.get(field,"0"))
            if preserve_zero and old == 0: continue
            raw=old*float(mul)+int(additions.get(field,0) or 0)
            new=math.ceil(raw) if round_up else round(raw)
            if field in caps and caps[field] is not None:new=min(new,int(caps[field]))
            new=max(0,new)
            if new != old: row[field]=str(new); row_changed=True
        if row_changed:changed += 1
        out.append(row)
    return out, BoostResult(processed,changed)


def write_csv(path:Path, fieldnames, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fieldnames,extrasaction="ignore",lineterminator="\n");w.writeheader();w.writerows(rows)


def save_profile(project_root:Path, name:str, fieldnames, rows, settings:dict):
    safe="".join(c for c in name if c.isalnum() or c in " _+-").strip() or "Custom"
    folder=project_root/"Profiles"/"Monsters"/safe
    write_csv(folder/"monster.csv",fieldnames,rows)
    report={"name":safe,"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"settings":settings,"rows":len(rows)}
    (folder/"profile.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return folder/"monster.csv"


def activate_profile(profile_csv:Path, active_csv:Path):
    active_csv.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(profile_csv,active_csv)
