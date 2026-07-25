from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import csv
import io
import shutil

from crystal_legacy_studio.core.atomic import atomic_write_text
from crystal_legacy_studio.core.errors import StudioError

class CsvDocumentError(StudioError):
    code = "CSV-001"

@dataclass
class CsvDocument:
    path: Path
    fieldnames: list[str]
    rows: list[dict[str, str]]
    source_path: Path | None = None

    @classmethod
    def load(cls, path: Path, source_path: Path | None = None) -> "CsvDocument":
        try:
            text = path.read_text(encoding="utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise CsvDocumentError("CSV has no header.", detail=str(path))
            rows = []
            for source_row in reader:
                rows.append({name: (source_row.get(name) or "") for name in reader.fieldnames})
            return cls(path=path, fieldnames=list(reader.fieldnames), rows=rows, source_path=source_path)
        except CsvDocumentError:
            raise
        except Exception as exc:
            raise CsvDocumentError("Could not read CSV.", detail=f"{path}: {exc}") from exc

    def save(self) -> None:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=self.fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(self.rows)
        atomic_write_text(self.path, stream.getvalue(), encoding="utf-8")

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.fieldnames:
            issues.append("CSV header is missing.")
            return issues
        if "id" in self.fieldnames:
            seen: dict[str, int] = {}
            for index, row in enumerate(self.rows, start=2):
                value = row.get("id", "").strip()
                if not value:
                    issues.append(f"Row {index}: id is blank.")
                elif value in seen:
                    issues.append(f"Row {index}: duplicate id {value} (first used on row {seen[value]}).")
                else:
                    seen[value] = index
        for index, row in enumerate(self.rows, start=2):
            missing = [field for field in self.fieldnames if field not in row]
            if missing:
                issues.append(f"Row {index}: missing fields: {', '.join(missing)}.")
        return issues

def locate_csv(search_root: Path | None, filename: str) -> Path | None:
    if not search_root or not search_root.exists():
        return None
    direct_candidates = [
        search_root / "master" / "Assets" / "GameAssets" / "Serial" / "Data" / "Master" / filename,
        search_root / "Assets" / "GameAssets" / "Serial" / "Data" / "Master" / filename,
        search_root / "Master" / filename,
        search_root / filename,
    ]
    for candidate in direct_candidates:
        if candidate.is_file():
            return candidate
    matches = list(search_root.rglob(filename))
    return matches[0] if matches else None

def ensure_project_copy(project_root: Path, source_path: Path, filename: str) -> Path:
    destination = project_root / "Data" / "Master" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination
