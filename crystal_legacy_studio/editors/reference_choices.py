from dataclasses import dataclass
from pathlib import Path
from crystal_legacy_studio.editors.csv_document import CsvDocument, locate_csv
from crystal_legacy_studio.localization.catalog import MessageCatalog

@dataclass(frozen=True)
class Choice:
    value:str
    label:str
    @property
    def display(self): return self.label if self.value=="0" else f"{self.value} — {self.label}"

def command_choices(export_root:Path|None,catalog:MessageCatalog):
    result=[Choice("0","None / No command")]
    path=locate_csv(export_root,"command.csv")
    if not path:return result
    for row in CsvDocument.load(path).rows:
        cid=row.get("id","").strip()
        key=row.get("mes_id_name","").strip()
        label=catalog.display(key) or key or f"Command {cid}"
        aid=row.get("ability_id","").strip()
        if aid and aid!="0": label+=f" [ability {aid}]"
        result.append(Choice(cid,label))
    return result
