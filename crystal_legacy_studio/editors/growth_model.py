from dataclasses import dataclass
from pathlib import Path
from crystal_legacy_studio.editors.csv_document import CsvDocument, locate_csv, ensure_project_copy

CALC_FIELDS=["hp_value1","mp_value1","strength","vitality","agility","intelligence","spirit","magic","luck","accuracy_rate","magic_evasion_rate"]

@dataclass
class GrowthBundle:
    intermediate:CsvDocument
    curves:CsvDocument
    group_id:str
    @property
    def rows(self):
        rows=[r for r in self.curves.rows if r.get("group_id","").strip()==self.group_id]
        return sorted(rows,key=lambda r:int(r.get("lv","0") or 0))
    def totals(self,base):
        out={}
        for f in CALC_FIELDS:
            total=0
            if f in ("strength","vitality","agility","magic"):
                try: total=int(base.get(f,"0") or 0)
                except: pass
            for row in self.rows:
                try: total+=int(row.get(f,"0") or 0)
                except: pass
            out[f]=total
        return out
    def save(self):
        self.intermediate.save(); self.curves.save()

def load_growth(project_root:Path,export_root:Path|None,job_id:str):
    a=locate_csv(export_root,"intermediate_growth_curve.csv")
    b=locate_csv(export_root,"growth_curve.csv")
    if not a or not b:return None
    ai=ensure_project_copy(project_root,a,"intermediate_growth_curve.csv")
    bi=ensure_project_copy(project_root,b,"growth_curve.csv")
    inter=CsvDocument.load(ai,source_path=a); curves=CsvDocument.load(bi,source_path=b)
    mapping=next((r for r in inter.rows if r.get("job_id","").strip()==str(job_id)),None)
    return GrowthBundle(inter,curves,mapping.get("growth_curve_group_id","").strip()) if mapping else None


def apply_generated_curve(bundle,field,base_value,target_value,curve_type,slope,late_start):
    from crystal_legacy_studio.editors.curve_profiles import CurveRequest,generate_curve
    levels=[int(r.get("lv","0") or 0) for r in bundle.rows]
    if not levels:return
    inc=generate_curve(CurveRequest(min(levels),max(levels),base_value,target_value,curve_type,slope,late_start))
    for row in bundle.rows:
        level=int(row.get("lv","0") or 0)
        if field in row: row[field]=str(inc.get(level,0))
