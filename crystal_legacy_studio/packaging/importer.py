from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import csv
import datetime
import hashlib
import io
import json
import shutil
import zipfile

from crystal_legacy_studio.core.errors import PackageBuildError
from crystal_legacy_studio.packaging.builder import PackageBuilder
from crystal_legacy_studio.project.models import Project


@dataclass(frozen=True)
class ImportConflict:
    conflict_id: str
    kind: str
    display_name: str
    target_relative: str
    record_key: str = ""
    current_summary: str = ""
    incoming_summary: str = ""


@dataclass
class ImportAnalysis:
    package_path: Path
    new_files: list[str]
    identical_files: list[str]
    conflicting_files: list[str]
    conflicts: list[ImportConflict] = field(default_factory=list)
    new_records: int = 0
    identical_records: int = 0


@dataclass
class ImportResult:
    imported_files: list[Path]
    backup: Path | None
    conflicts_overwritten: int
    conflicts_ignored: int = 0
    records_added: int = 0


@dataclass(frozen=True)
class _LegacyMember:
    archive_name: str
    kind: str  # csv, message, file
    target_relative: str
    resource_relative: str


class PackageImporter:
    """Import Crystal Legacy packages and merge Nexus/Magicite ZIP mods safely.

    Legacy master CSVs merge by their ``id`` column. Message tables merge by
    message key. Graphics, scripts, keys and other resources merge by exact
    Magicite-relative path. Existing differences are presented as individual
    conflicts so the user can approve or ignore each part of an import.
    """

    def analyze(self, project: Project, package_path: Path) -> ImportAnalysis:
        package_path = Path(package_path)
        PackageBuilder().verify(package_path)
        new_files: list[str] = []
        identical: list[str] = []
        conflicts: list[str] = []
        details: list[ImportConflict] = []
        with zipfile.ZipFile(package_path, "r") as archive:
            for name in sorted(n for n in archive.namelist() if n.startswith("content/") and not n.endswith("/")):
                relative = name.removeprefix("content/")
                target = project.working_root / Path(relative)
                payload = archive.read(name)
                if not target.exists():
                    new_files.append(relative)
                elif self._same(target.read_bytes(), payload):
                    identical.append(relative)
                else:
                    conflicts.append(relative)
                    details.append(ImportConflict(
                        f"file:{relative}", "File", relative, relative,
                        current_summary=self._file_summary(target.read_bytes()),
                        incoming_summary=self._file_summary(payload),
                    ))
        return ImportAnalysis(package_path, new_files, identical, conflicts, details)

    @staticmethod
    def _same(a: bytes, b: bytes) -> bool:
        return hashlib.sha256(a).digest() == hashlib.sha256(b).digest()

    @staticmethod
    def _file_summary(data: bytes) -> str:
        return f"{len(data):,} bytes · {hashlib.sha256(data).hexdigest()[:12]}"

    @staticmethod
    def _strip_magicite_wrapper(parts: list[str]) -> list[str]:
        lower = [p.lower() for p in parts]
        if "magicite" in lower:
            parts = parts[lower.index("magicite") + 1:]
        if not parts:
            return []
        known_prefixes = ('master', 'message', 'mn_', 'mt_', 'wp_', 'bg_', 'bc_', 'mo_', 'ef_', 'ff1_', 'monster_', 'chara_')
        if len(parts) >= 2 and not parts[0].lower().startswith(known_prefixes):
            parts = parts[1:]  # Nexus pack container, e.g. "001 - SoC + 20th Content"
        return parts

    def _legacy_members(self, archive: zipfile.ZipFile) -> list[_LegacyMember]:
        result: list[_LegacyMember] = []
        for name in archive.namelist():
            if name.endswith('/'):
                continue
            normalized = name.replace('\\', '/')
            parts = self._strip_magicite_wrapper(list(Path(normalized).parts))
            if not parts or '..' in parts:
                continue
            resource_relative = str(Path(*parts))
            lower_parts = [p.lower() for p in parts]
            filename = parts[-1]
            if 'data' in lower_parts and 'master' in lower_parts and filename.lower().endswith('.csv'):
                target = str(Path('Data') / 'Master' / filename)
                result.append(_LegacyMember(name, 'csv', target, resource_relative))
            elif 'data' in lower_parts and 'message' in lower_parts and filename.lower().endswith('.txt'):
                target = str(Path('Data') / 'Message' / filename)
                result.append(_LegacyMember(name, 'message', target, resource_relative))
            else:
                result.append(_LegacyMember(name, 'file', str(Path('Overlays') / resource_relative), resource_relative))
        return result

    @staticmethod
    def _read_csv_bytes(payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
        text = payload.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise PackageBuildError('CSV has no header.')
        return list(reader.fieldnames), [dict(row) for row in reader]

    @staticmethod
    def _csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _message_entries(payload: bytes) -> tuple[list[str], dict[str, str]]:
        text = payload.decode('utf-8-sig')
        order: list[str] = []
        entries: dict[str, str] = {}
        for line in text.splitlines():
            if not line.strip() or '\t' not in line:
                continue
            key, value = line.split('\t', 1)
            if key not in entries:
                order.append(key)
            entries[key] = value
        return order, entries

    @staticmethod
    def _message_bytes(order: list[str], entries: dict[str, str]) -> bytes:
        return ('\n'.join(f'{key}\t{entries[key]}' for key in order) + ('\n' if order else '')).encode('utf-8')

    @staticmethod
    def _row_summary(row: dict[str, str]) -> str:
        useful = [(k, v) for k, v in row.items() if v not in ('', '0', None)][:5]
        return ', '.join(f'{k}={v}' for k, v in useful) or 'empty/default row'


    @staticmethod
    def _ensure_reference_baseline(project: Project, member: _LegacyMember, target: Path) -> None:
        """Seed a missing editable table from read-only MagiciteExport before merging."""
        if target.exists() or member.kind not in {'csv', 'message'}:
            return
        folder = 'Master' if member.kind == 'csv' else 'Message'
        candidates = list(project.layout.magicite_export.rglob(f'Data/{folder}/{Path(member.target_relative).name}'))
        if not candidates:
            candidates = [p for p in project.layout.magicite_export.rglob(Path(member.target_relative).name)
                          if f'/Data/{folder}/'.lower() in p.as_posix().lower()]
        if candidates:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidates[0], target)

    def analyze_any(self, project: Project, package_path: Path) -> ImportAnalysis:
        package_path = Path(package_path)
        if package_path.suffix.lower() == '.crystalpackage':
            return self.analyze(project, package_path)
        if not zipfile.is_zipfile(package_path):
            raise PackageBuildError('The selected file is not a valid ZIP mod.')

        new_files: list[str] = []
        identical_files: list[str] = []
        conflicting_files: list[str] = []
        conflict_details: list[ImportConflict] = []
        new_records = 0
        identical_records = 0

        with zipfile.ZipFile(package_path, 'r') as archive:
            members = self._legacy_members(archive)
            if not members:
                raise PackageBuildError('ZIP does not contain a recognizable Magicite mod tree.')
            for member in members:
                payload = archive.read(member.archive_name)
                target = project.working_root / member.target_relative
                self._ensure_reference_baseline(project, member, target)
                if member.kind == 'csv':
                    incoming_fields, incoming_rows = self._read_csv_bytes(payload)
                    if 'id' not in incoming_fields:
                        # Non-ID tables are handled as exact files rather than guessed merges.
                        self._analyze_file(member, target, payload, new_files, identical_files, conflicting_files, conflict_details)
                        continue
                    current_fields: list[str] = incoming_fields
                    current_rows: list[dict[str, str]] = []
                    if target.exists():
                        current_fields, current_rows = self._read_csv_bytes(target.read_bytes())
                    current_by_id = {row.get('id', ''): row for row in current_rows}
                    for row in incoming_rows:
                        key = row.get('id', '')
                        label = f'{Path(member.target_relative).name} · ID {key}'
                        if key not in current_by_id:
                            new_records += 1
                        elif current_by_id[key] == row:
                            identical_records += 1
                        else:
                            conflict_id = f'csv:{member.target_relative}:{key}'
                            conflict_details.append(ImportConflict(
                                conflict_id, 'Data record', label, member.target_relative, key,
                                self._row_summary(current_by_id[key]), self._row_summary(row),
                            ))
                            conflicting_files.append(label)
                elif member.kind == 'message':
                    _, incoming = self._message_entries(payload)
                    current: dict[str, str] = {}
                    if target.exists():
                        _, current = self._message_entries(target.read_bytes())
                    for key, value in incoming.items():
                        label = f'{Path(member.target_relative).name} · {key}'
                        if key not in current:
                            new_records += 1
                        elif current[key] == value:
                            identical_records += 1
                        else:
                            conflict_id = f'message:{member.target_relative}:{key}'
                            conflict_details.append(ImportConflict(
                                conflict_id, 'Text entry', label, member.target_relative, key,
                                current[key][:180], value[:180],
                            ))
                            conflicting_files.append(label)
                else:
                    self._analyze_file(member, target, payload, new_files, identical_files, conflicting_files, conflict_details)

        return ImportAnalysis(package_path, new_files, identical_files, conflicting_files,
                              conflict_details, new_records, identical_records)

    def _analyze_file(self, member: _LegacyMember, target: Path, payload: bytes,
                      new_files: list[str], identical_files: list[str], conflicting_files: list[str],
                      conflict_details: list[ImportConflict]) -> None:
        relative = member.target_relative
        if not target.exists():
            new_files.append(relative)
        elif self._same(target.read_bytes(), payload):
            identical_files.append(relative)
        else:
            conflicting_files.append(relative)
            conflict_details.append(ImportConflict(
                f'file:{relative}', 'File', relative, relative,
                current_summary=self._file_summary(target.read_bytes()),
                incoming_summary=self._file_summary(payload),
            ))

    def import_any(self, project: Project, package_path: Path, *, backup: bool = True,
                   approved_conflicts: set[str] | None = None) -> ImportResult:
        package_path = Path(package_path)
        approved_conflicts = set(approved_conflicts or ())
        if package_path.suffix.lower() == '.crystalpackage':
            return self.import_package(project, package_path, backup=backup,
                                       approved_conflicts=approved_conflicts)

        analysis = self.analyze_any(project, package_path)
        backup_path = project.layout.timestamped_backup(project.working_root, 'BeforeNexusImport') if backup else None
        imported: list[Path] = []
        records_added = 0
        overwritten = 0
        ignored = 0

        with zipfile.ZipFile(package_path, 'r') as archive:
            for member in self._legacy_members(archive):
                payload = archive.read(member.archive_name)
                target = project.working_root / member.target_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                self._ensure_reference_baseline(project, member, target)
                if member.kind == 'csv':
                    incoming_fields, incoming_rows = self._read_csv_bytes(payload)
                    if 'id' not in incoming_fields:
                        wrote, was_conflict = self._import_file(member, target, payload, approved_conflicts)
                        if wrote: imported.append(target); overwritten += int(was_conflict)
                        elif was_conflict: ignored += 1
                        continue
                    current_fields, current_rows = (incoming_fields, [])
                    if target.exists():
                        current_fields, current_rows = self._read_csv_bytes(target.read_bytes())
                    fields = list(current_fields)
                    for field_name in incoming_fields:
                        if field_name not in fields:
                            fields.append(field_name)
                    by_id = {row.get('id', ''): row for row in current_rows}
                    order = [row.get('id', '') for row in current_rows]
                    changed = False
                    for incoming in incoming_rows:
                        key = incoming.get('id', '')
                        if key not in by_id:
                            by_id[key] = incoming; order.append(key); records_added += 1; changed = True
                        elif by_id[key] == incoming:
                            continue
                        elif f'csv:{member.target_relative}:{key}' in approved_conflicts:
                            by_id[key] = incoming; overwritten += 1; changed = True
                        else:
                            ignored += 1
                    if changed:
                        target.write_bytes(self._csv_bytes(fields, [by_id[key] for key in order]))
                        imported.append(target)
                elif member.kind == 'message':
                    incoming_order, incoming = self._message_entries(payload)
                    current_order: list[str] = []
                    current: dict[str, str] = {}
                    if target.exists():
                        current_order, current = self._message_entries(target.read_bytes())
                    changed = False
                    for key in incoming_order:
                        value = incoming[key]
                        if key not in current:
                            current[key] = value; current_order.append(key); records_added += 1; changed = True
                        elif current[key] == value:
                            continue
                        elif f'message:{member.target_relative}:{key}' in approved_conflicts:
                            current[key] = value; overwritten += 1; changed = True
                        else:
                            ignored += 1
                    if changed:
                        target.write_bytes(self._message_bytes(current_order, current)); imported.append(target)
                else:
                    wrote, was_conflict = self._import_file(member, target, payload, approved_conflicts)
                    if wrote: imported.append(target); overwritten += int(was_conflict)
                    elif was_conflict: ignored += 1

        report = project.metadata_dir / 'imports' / f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-nexus.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            'package': str(package_path), 'format': 'nexus-magicite-zip',
            'backup': str(backup_path) if backup_path else None,
            'newFiles': analysis.new_files, 'newRecords': analysis.new_records,
            'approvedConflicts': sorted(approved_conflicts),
            'ignoredConflicts': ignored,
        }, indent=2), encoding='utf-8')
        return ImportResult(imported, backup_path, overwritten, ignored, records_added)

    def _import_file(self, member: _LegacyMember, target: Path, payload: bytes,
                     approved_conflicts: set[str]) -> tuple[bool, bool]:
        if not target.exists():
            target.write_bytes(payload); return True, False
        if self._same(target.read_bytes(), payload):
            return False, False
        conflict_id = f'file:{member.target_relative}'
        if conflict_id in approved_conflicts:
            target.write_bytes(payload); return True, True
        return False, True

    def import_package(self, project: Project, package_path: Path, *, backup: bool = True,
                       approved_conflicts: set[str] | None = None) -> ImportResult:
        analysis = self.analyze(project, package_path)
        # Backward-compatible API: direct programmatic imports overwrite all
        # conflicts unless the caller explicitly supplies a selected set.
        if approved_conflicts is None:
            approved_conflicts = {conflict.conflict_id for conflict in analysis.conflicts}
        else:
            approved_conflicts = set(approved_conflicts)
        backup_path = project.layout.timestamped_backup(project.working_root, 'BeforeImport') if backup else None
        imported: list[Path] = []
        overwritten = 0
        ignored = 0
        with zipfile.ZipFile(package_path, 'r') as archive:
            for name in sorted(n for n in archive.namelist() if n.startswith('content/') and not n.endswith('/')):
                relative = name.removeprefix('content/')
                target = project.working_root / Path(relative)
                payload = archive.read(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                conflict_id = f'file:{relative}'
                if target.exists() and not self._same(target.read_bytes(), payload):
                    if conflict_id not in approved_conflicts:
                        ignored += 1; continue
                    overwritten += 1
                if not target.exists() or not self._same(target.read_bytes(), payload):
                    target.write_bytes(payload); imported.append(target)
        return ImportResult(imported, backup_path, overwritten, ignored, len(analysis.new_files))
