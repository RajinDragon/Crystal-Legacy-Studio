from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import datetime
import json
import shutil
import zipfile

try:
    from PIL import Image
except Exception:
    Image = None

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tga'}
AUDIO_EXTENSIONS = {'.wav', '.ogg', '.mp3', '.flac', '.m4a'}
TEXT_EXTENSIONS = {'.csv', '.txt', '.json', '.xml', '.yaml', '.yml', '.lua', '.cs', '.bytes'}
HIDDEN_TECHNICAL_NAMES = {'.ds_store', 'thumbs.db', 'desktop.ini'}
HIDDEN_TECHNICAL_SUFFIXES = {'.meta', '.manifest', '.md5', '.sha1', '.sha256'}

CATEGORY_ORDER = [
    'Monster Sprites',
    'Character Battle Sprites',
    'Character Field Sprites',
    'Weapon Images',
    'Armor & Item Icons',
    'Bestiary Assets',
    'Battle Backgrounds',
    'Spell & Battle Effects',
    'Maps & Field Assets',
    'UI & Common Graphics',
    'Audio',
    'Master Data',
    'Messages',
    'Battle Scripts & AI',
    'Other Resources',
]

@dataclass(frozen=True)
class AssetRecord:
    category: str
    resource_group: str
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    source_path: str

    @property
    def is_image(self) -> bool:
        return self.extension.lower() in IMAGE_EXTENSIONS

    @property
    def is_audio(self) -> bool:
        return self.extension.lower() in AUDIO_EXTENSIONS


def categorize(relative: Path) -> str:
    text = relative.as_posix().lower()
    parts = [part.lower() for part in relative.parts]
    top = parts[0] if parts else ''
    name = relative.name.lower()

    if 'bestiary' in text or 'encyclopedia' in text or 'monster_picture' in text or 'monster_thumbnail' in text or 'thumbnail' in text:
        return 'Bestiary Assets'
    if 'monster' in text and any(token in text for token in ('sprite', 'battle', 'texture')):
        return 'Monster Sprites'
    if top.startswith(('monster_', 'mon_')) or '/monster/' in f'/{text}/':
        return 'Monster Sprites'
    # Playable character exports are individual Magicite resource groups.
    # bc_ff1_p001 .. p012 contain the 12 battle-frame PNG/spriteData pairs.
    # mo_ff1_p001_c00 .. p012_c00 contain the map/field atlas and frame metadata.
    if top.startswith('bc_ff1_p') or top == 'chara_battle' or 'characterbattle' in text or 'battlecharacter' in text:
        return 'Character Battle Sprites'
    if top.startswith('mo_ff1_p') or top == 'chara_field' or 'fieldcharacter' in text or 'characterfield' in text:
        return 'Character Field Sprites'
    if any(token in text for token in ('weapon', 'sword', 'axe', 'staff', 'knife', 'hammer', 'nunchaku')) and relative.suffix.lower() in IMAGE_EXTENSIONS:
        return 'Weapon Images'
    if any(token in text for token in ('armor', 'armour', 'shield', 'helmet', 'itemicon', 'item_icon', '/icon', 'icons/')) and relative.suffix.lower() in IMAGE_EXTENSIONS:
        return 'Armor & Item Icons'
    if top.startswith('bg_ff') or 'battle_background' in text or '/battlebackground' in text:
        return 'Battle Backgrounds'
    if top.startswith('ef_') or 'effect' in text or 'condition_effect' in text:
        return 'Spell & Battle Effects'
    if top in {'map', 'field', 'fieldmap', 'tilemap'} or any(token in text for token in ('/map/', '/field/', 'mapchip', 'tileset')):
        return 'Maps & Field Assets'
    if relative.suffix.lower() in AUDIO_EXTENSIONS or top.startswith(('bgm', 'se_', 'sound')) or '/audio/' in text:
        return 'Audio'
    if top == 'master' or '/data/master/' in text or name.endswith('.csv') and 'message' not in text:
        return 'Master Data'
    if top in {'message', 'common_message'} or '/data/message/' in text or name.startswith('system_'):
        return 'Messages'
    if 'battle_script' in text or 'battleai' in text or '/ai/' in text or name.endswith('.lua'):
        return 'Battle Scripts & AI'
    if top.startswith('common') or any(token in text for token in ('title', 'menu', 'window', 'cursor', 'font', 'license', 'minimap')):
        return 'UI & Common Graphics'
    return 'Other Resources'


class MagiciteAssetCatalog:
    def __init__(self, export_root: Path):
        self.export_root = Path(export_root)
        self.records: list[AssetRecord] = []

    def scan(self) -> list[AssetRecord]:
        if not self.export_root.is_dir():
            raise FileNotFoundError(f'MagiciteExport was not found: {self.export_root}')
        records: list[AssetRecord] = []
        for path in sorted(self.export_root.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(self.export_root)
            # Packaging metadata is required by Magicite deployment but is not a
            # creative game asset. Keep it in the source tree and deployment, while
            # hiding it from RPG Maker-style asset selection pages.
            lower_name = path.name.lower()
            if lower_name in HIDDEN_TECHNICAL_NAMES or path.suffix.lower() in HIDDEN_TECHNICAL_SUFFIXES:
                continue
            if lower_name == 'export.json' and 'keys' in [part.lower() for part in rel.parts]:
                continue
            category = categorize(rel)
            # Sprite pages expose only actual PNG artwork. spriteData, bundle
            # metadata and other engine-side files remain available to deployment
            # but are hidden from the creator-facing catalog.
            if category in {'Monster Sprites', 'Character Battle Sprites', 'Character Field Sprites'}:
                if path.suffix.lower() != '.png':
                    continue
                # Empty transparent placeholders (for example unused attack frames)
                # add no editable artwork, so omit them without deleting the source.
                if Image is not None:
                    try:
                        with Image.open(path) as image:
                            rgba = image.convert('RGBA')
                            if rgba.getbbox() is None:
                                continue
                    except Exception:
                        pass
            records.append(AssetRecord(
                category=category,
                resource_group=rel.parts[0] if rel.parts else '',
                relative_path=rel.as_posix(),
                filename=path.name,
                extension=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                source_path=str(path),
            ))
        self.records = records
        return records

    def by_category(self, category: str) -> list[AssetRecord]:
        return [record for record in self.records if record.category == category]

    def counts(self) -> dict[str, int]:
        return {category: len(self.by_category(category)) for category in CATEGORY_ORDER}

    def write_manifest(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'source': str(self.export_root),
            'generatedUtc': datetime.datetime.now(datetime.UTC).isoformat(),
            'totalFiles': len(self.records),
            'categoryCounts': self.counts(),
            'assets': [asdict(record) for record in self.records],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return destination


class AssetStager:
    def __init__(self, export_root: Path, working_overlays: Path):
        self.export_root = Path(export_root).resolve()
        self.working_overlays = Path(working_overlays).resolve()

    def stage_replacement(self, record: AssetRecord, replacement: Path) -> Path:
        replacement = Path(replacement)
        if not replacement.is_file():
            raise FileNotFoundError(replacement)
        source_suffix = Path(record.filename).suffix.lower()
        if source_suffix and replacement.suffix.lower() != source_suffix:
            raise ValueError(f'Replacement must use the same extension ({source_suffix}).')
        target = self.working_overlays / Path(record.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(replacement, target)
        return target

    def stage_files_into_group(self, resource_group: str, files: list[Path]) -> list[Path]:
        if not resource_group or '/' in resource_group or '\\' in resource_group:
            raise ValueError('Select one valid Magicite resource group.')
        targets: list[Path] = []
        base = self.working_overlays / resource_group
        base.mkdir(parents=True, exist_ok=True)
        for source in files:
            source = Path(source)
            if source.is_file():
                target = base / source.name
                shutil.copy2(source, target)
                targets.append(target)
            elif source.is_dir():
                target = base / source.name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
                targets.extend(path for path in target.rglob('*') if path.is_file())
        return targets

    def stage_zip(self, archive: Path) -> list[Path]:
        archive = Path(archive)
        if not zipfile.is_zipfile(archive):
            raise ValueError('The dropped file is not a valid ZIP archive.')
        written: list[Path] = []
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = Path(info.filename)
                parts = list(rel.parts)
                if parts and parts[0].lower() in {'magicite', 'crystal legacy'}:
                    rel = Path(*parts[1:])
                if not rel.parts or '..' in rel.parts:
                    continue
                target = self.working_overlays / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                written.append(target)
        return written
