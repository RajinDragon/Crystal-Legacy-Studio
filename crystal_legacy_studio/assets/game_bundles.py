from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import datetime, hashlib, json, re, shutil, struct

BUNDLE_EXTENSIONS = {'.bundle', '.assets', '.ress', '.resource', '.resS'.lower()}
TECHNICAL_NAMES = {'catalog.json', 'settings.json', 'link.xml', 'boot.config', 'globalgamemanagers'}

@dataclass(frozen=True)
class GameFileRecord:
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    sha256: str
    family: str
    subject: str
    unity_signature: str
    unity_version: str
    file_kind: str
    source_path: str

PREFIX_RULES = [
    (re.compile(r'^bc_ff(?P<game>\d+)_p(?P<id>\d{3})', re.I), 'Character Battle Bundle', 'Playable character p{id}'),
    (re.compile(r'^mo_ff(?P<game>\d+)_p(?P<id>\d{3})', re.I), 'Character Field Bundle', 'Playable character p{id}'),
    (re.compile(r'^(?:bc|mon|monster)_ff(?P<game>\d+)_(?P<id>.+?)_assets', re.I), 'Monster Battle Bundle', 'Monster {id}'),
    (re.compile(r'^bg_ff(?P<game>\d+)_(?P<id>.+?)_assets', re.I), 'Battle Background Bundle', 'Background {id}'),
    (re.compile(r'^ef_(?P<id>.+?)_assets', re.I), 'Effect Bundle', 'Effect {id}'),
    (re.compile(r'^(?:we|weapon)_(?P<id>.+?)_assets', re.I), 'Weapon Bundle', 'Weapon {id}'),
    (re.compile(r'^(?:ui|common)_(?P<id>.+?)_assets', re.I), 'UI/Common Bundle', 'UI {id}'),
    (re.compile(r'^(?:map|field)_(?P<id>.+?)_assets', re.I), 'Map/Field Bundle', 'Map {id}'),
]

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def _read_cstring(f) -> str:
    b=bytearray()
    while True:
        c=f.read(1)
        if not c or c==b'\0': break
        b.extend(c)
    return b.decode('utf-8','replace')

def unity_header(path: Path) -> tuple[str,str,str]:
    try:
        with path.open('rb') as f:
            sig=_read_cstring(f)
            if sig not in {'UnityFS','UnityWeb','UnityRaw','UnityArchive'}:
                return sig[:32], '', 'Non-Unity or serialized data file'
            raw=f.read(4)
            if len(raw)!=4: return sig,'','Unity bundle'
            _fmt=struct.unpack('>I',raw)[0]
            unity_version=_read_cstring(f)
            _revision=_read_cstring(f)
            return sig, unity_version, 'Unity AssetBundle'
    except OSError:
        return '', '', 'Unreadable'

def classify_name(name: str, ext: str) -> tuple[str,str]:
    lower=name.lower()
    for rx,family,subject in PREFIX_RULES:
        m=rx.match(lower)
        if m:
            vals={k:v for k,v in m.groupdict().items() if v is not None}
            return family, subject.format(**vals)
    if lower.startswith('font_'): return 'Font Bundle', name
    if 'catalog' in lower: return 'Addressables Catalog', name
    if ext=='.assets': return 'Unity Serialized Asset', name
    if ext in {'.ress','.resource'}: return 'Unity Resource Stream', name
    if ext=='.bundle': return 'Unclassified Bundle', name
    return 'Game Support File', name

class GameBundleCatalog:
    def __init__(self, game_root: Path):
        self.game_root=Path(game_root)
        self.records:list[GameFileRecord]=[]

    def scan(self) -> list[GameFileRecord]:
        roots=[]
        data_dirs=list(self.game_root.glob('*_Data'))
        for data in data_dirs:
            for rel in ('StreamingAssets','Resources'):
                p=data/rel
                if p.exists(): roots.append(p)
            for filename in ('globalgamemanagers','globalgamemanagers.assets','resources.assets','sharedassets0.assets','sharedassets0.assets.resS','level0'):
                p=data/filename
                if p.exists(): roots.append(p)
        records=[]
        seen=set()
        paths=[]
        for root in roots:
            paths.extend([root] if root.is_file() else root.rglob('*'))
        for path in sorted(paths, key=lambda p:str(p).lower()):
            if not path.is_file() or path in seen: continue
            seen.add(path)
            ext=path.suffix.lower()
            lname=path.name.lower()
            include=ext in {'.bundle','.assets','.ress','.resource','.json','.bin'} or lname in TECHNICAL_NAMES or lname.endswith('.assets.ress')
            if not include: continue
            family,subject=classify_name(path.name, ext)
            sig,uv,kind=unity_header(path) if ext in {'.bundle','.assets'} or not ext else ('','','Support/metadata')
            records.append(GameFileRecord(
                relative_path=path.relative_to(self.game_root).as_posix(), filename=path.name,
                extension=ext, size_bytes=path.stat().st_size, sha256=sha256_file(path),
                family=family, subject=subject, unity_signature=sig, unity_version=uv,
                file_kind=kind, source_path=str(path)))
        self.records=records
        return records

    def write_manifest(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True,exist_ok=True)
        payload={'gameRoot':str(self.game_root),'generatedUtc':datetime.datetime.now(datetime.UTC).isoformat(),
                 'totalFiles':len(self.records),'files':[asdict(r) for r in self.records]}
        destination.write_text(json.dumps(payload,indent=2),encoding='utf-8')
        return destination

class DirectGameFileManager:
    def __init__(self, game_root: Path, backup_root: Path, working_root: Path):
        self.game_root=Path(game_root).resolve(); self.backup_root=Path(backup_root).resolve(); self.working_root=Path(working_root).resolve()

    def stage_replacement(self, record: GameFileRecord, replacement: Path) -> Path:
        replacement=Path(replacement)
        if replacement.suffix.lower()!=record.extension.lower():
            raise ValueError(f'Replacement must keep extension {record.extension}.')
        if record.unity_signature=='UnityFS':
            sig,_,_=unity_header(replacement)
            if sig!='UnityFS': raise ValueError('Replacement is not a UnityFS AssetBundle.')
        target=self.working_root/record.relative_path
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(replacement,target)
        return target

    def deploy_one(self, record: GameFileRecord, staged: Path) -> tuple[Path,Path]:
        live=self.game_root/record.relative_path
        if not live.is_file(): raise FileNotFoundError(live)
        stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup=self.backup_root/'DirectGameFiles'/stamp/record.relative_path
        backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(live,backup)
        shutil.copy2(staged,live)
        if sha256_file(live)!=sha256_file(staged):
            shutil.copy2(backup,live); raise IOError('Verification failed; original restored.')
        return live,backup
