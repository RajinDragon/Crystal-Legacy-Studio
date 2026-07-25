from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import random
import colorsys
import re
import shutil
import struct
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import zipfile

from PIL import Image, ImageTk
import lz4.block

from crystal_legacy_studio.bundle_extractor import extract_bundle_textures

BATTLE_REQUIRED = (
    'Damage_00.png', 'Default_00.png', 'Down_00.png', 'Dying_00.png',
    'Ready_00.png', 'RightAttack_00.png', 'RightAttack_01.png',
    'SkillReady_00.png', 'SkillReady_01.png', 'Win_00.png',
)
BATTLE_OPTIONAL = ('LeftAttack_00.png', 'LeftAttack_01.png')
BUNDLE_BATTLE = re.compile(r'^bc_ff1_p(?P<id>\d{3})_assets_all_[0-9a-f]+\.bundle$', re.I)
BUNDLE_FIELD = re.compile(r'^mo_ff1_p(?P<id>\d{3})_c00_assets_all_[0-9a-f]+\.bundle$', re.I)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _visible_png(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            if image.width <= 0 or image.height <= 0:
                return False
            return image.convert('RGBA').getchannel('A').getbbox() is not None
    except Exception:
        return False


def _find_group(root: Path, group_name: str) -> Path | None:
    """Find the outer Magicite resource group, never its same-named asset folder.

    Character groups contain both ``bc_ff1_p###`` and an inner
    ``BC_FF1_P###`` directory. A case-insensitive first-match search can select
    the inner directory and silently omit keys/Export.json, which makes Magicite
    ignore the staged artwork. The outer group is identified by its keys folder.
    """
    if not root or not Path(root).is_dir():
        return None
    wanted = group_name.lower()
    candidates = [p for p in Path(root).rglob('*') if p.is_dir() and p.name.lower() == wanted]
    for path in candidates:
        if (path / 'keys' / 'Export.json').is_file():
            return path
    for path in candidates:
        if (path / 'Assets').is_dir():
            return path
    return candidates[0] if candidates else None


def _pngs(group: Path | None) -> list[Path]:
    return sorted(p for p in group.rglob('*.png') if p.is_file()) if group else []


def _unityfs(path: Path) -> bool:
    try:
        return path.read_bytes()[:8] == b'UnityFS\0'
    except OSError:
        return False


def _read_cstring_bytes(data: bytes, offset: int) -> tuple[bytes, int]:
    end = data.index(b"\0", offset)
    return data[offset:end], end + 1


def _lz4_decompress(data: bytes, flags: int, expected_size: int) -> bytes:
    compression = flags & 0x3F
    if compression == 0:
        return data
    if compression in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=expected_size)
    raise ValueError(f"Unsupported UnityFS compression type: {compression}")


def _lz4_compress(data: bytes, flags: int) -> bytes:
    compression = flags & 0x3F
    if compression == 0:
        return data
    if compression in (2, 3):
        return lz4.block.compress(data, store_size=False, mode="high_compression")
    raise ValueError(f"Unsupported UnityFS compression type: {compression}")


def _retarget_unityfs_bundle(source: Path, destination: Path, source_job: int, target_job: int) -> None:
    """Rewrite same-length playable-character identifiers inside a UnityFS bundle.

    FF1PR character bundles store their logical resource names as uppercase P###
    strings in the serialized payload. Replacing P012 with P001 is length-safe,
    then the UnityFS data blocks and block table are rebuilt. The original source
    model is never modified.
    """
    raw = source.read_bytes()
    offset = 0
    signature, offset = _read_cstring_bytes(raw, offset)
    if signature != b"UnityFS":
        raise ValueError(f"Invalid UnityFS bundle: {source.name}")
    fmt = struct.unpack_from(">I", raw, offset)[0]; offset += 4
    unity_version, offset = _read_cstring_bytes(raw, offset)
    revision, offset = _read_cstring_bytes(raw, offset)
    _old_size, compressed_info_size, uncompressed_info_size, flags = struct.unpack_from(">QIII", raw, offset)
    offset += 20
    aligned_offset = (offset + 15) & ~15 if fmt >= 7 else offset
    padding = raw[offset:aligned_offset]

    if flags & 0x80:
        info_compressed = raw[-compressed_info_size:]
        data_start = aligned_offset
        data_end = len(raw) - compressed_info_size
    else:
        info_compressed = raw[aligned_offset:aligned_offset + compressed_info_size]
        data_start = aligned_offset + compressed_info_size
        data_end = len(raw)

    info = _lz4_decompress(info_compressed, flags, uncompressed_info_size)
    cursor = 16
    block_count = struct.unpack_from(">I", info, cursor)[0]; cursor += 4
    blocks = []
    for _ in range(block_count):
        uncompressed_size, compressed_size, block_flags = struct.unpack_from(">IIH", info, cursor)
        cursor += 10
        blocks.append((uncompressed_size, compressed_size, block_flags))
    node_count_offset = cursor
    node_count = struct.unpack_from(">I", info, cursor)[0]; cursor += 4
    for _ in range(node_count):
        cursor += 20
        _, cursor = _read_cstring_bytes(info, cursor)
    node_section = info[node_count_offset:cursor]

    data_blob = raw[data_start:data_end]
    data_cursor = 0
    rebuilt_blocks = []
    rebuilt_data = bytearray()
    old_token = f"P{source_job:03d}".encode("ascii")
    new_token = f"P{target_job:03d}".encode("ascii")
    replacements = 0
    for uncompressed_size, compressed_size, block_flags in blocks:
        block_raw = _lz4_decompress(data_blob[data_cursor:data_cursor + compressed_size], block_flags, uncompressed_size)
        data_cursor += compressed_size
        replacements += block_raw.count(old_token)
        block_raw = block_raw.replace(old_token, new_token)
        block_compressed = _lz4_compress(block_raw, block_flags)
        rebuilt_blocks.append((len(block_raw), len(block_compressed), block_flags))
        rebuilt_data.extend(block_compressed)
    if replacements == 0:
        raise ValueError(f"No internal {old_token.decode()} resource identifiers were found in {source.name}.")

    rebuilt_info = bytearray(info[:16])
    rebuilt_info.extend(struct.pack(">I", len(rebuilt_blocks)))
    for uncompressed_size, compressed_size, block_flags in rebuilt_blocks:
        rebuilt_info.extend(struct.pack(">IIH", uncompressed_size, compressed_size, block_flags))
    rebuilt_info.extend(node_section)
    rebuilt_info_compressed = _lz4_compress(bytes(rebuilt_info), flags)

    header_prefix = bytearray()
    header_prefix.extend(signature + b"\0")
    header_prefix.extend(struct.pack(">I", fmt))
    header_prefix.extend(unity_version + b"\0")
    header_prefix.extend(revision + b"\0")
    size_position = len(header_prefix)
    header_prefix.extend(b"\0" * 8)
    header_prefix.extend(struct.pack(">III", len(rebuilt_info_compressed), len(rebuilt_info), flags))
    if fmt >= 7:
        header_prefix.extend(b"\0" * (((len(header_prefix) + 15) & ~15) - len(header_prefix)))

    if flags & 0x80:
        output = header_prefix + rebuilt_data + rebuilt_info_compressed
    else:
        output = header_prefix + rebuilt_info_compressed + rebuilt_data
    # UnityFS v7 files in FF1PR record size excluding alignment padding.
    recorded_size = len(output) - (len(header_prefix) - offset)
    struct.pack_into(">Q", output, size_position, recorded_size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
    if not _unityfs(destination):
        raise ValueError("Retargeted bundle failed UnityFS validation.")


def _extract_ready_from_package_art(source: Path, destination: Path) -> bool:
    """Create a sprite-focused preview from a Nexus banner when possible.

    This does not use the banner as the preview. It isolates a small character
    figure from the lower part of the artwork and removes only border-connected
    near-white background pixels.
    """
    try:
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
        width, height = image.size
        if width < 64 or height < 64:
            return False
        pixels = image.load()
        y0 = int(height * 0.52)
        counts = []
        for x in range(width):
            count = 0
            for y in range(y0, height):
                r, g, b, a = pixels[x, y]
                if a > 0 and not (r > 242 and g > 242 and b > 242):
                    count += 1
            counts.append(count)
        runs = []
        start = None
        for x, count in enumerate(counts + [0]):
            if count >= 3 and start is None:
                start = x
            elif count < 3 and start is not None:
                if 18 <= x - start <= 260:
                    runs.append((start, x))
                start = None
        if not runs:
            # Nexus banners commonly place the first representative battle pose
            # in the lower-left quadrant. Use a conservative proportional crop
            # as a fallback, then remove the connected white background below.
            x1, x2 = int(width * 0.085), int(width * 0.160)
        else:
            # Prefer the first compact character-sized run in reading order.
            x1, x2 = runs[0]
        ys = []
        for y in range(y0, height):
            if any(not all(c > 242 for c in pixels[x, y][:3]) for x in range(x1, x2)):
                ys.append(y)
        if not ys:
            y1, y2 = int(height * 0.46), int(height * 0.65)
        else:
            y1, y2 = max(y0, min(ys) - 4), min(height, max(ys) + 5)
        # If the detected span is dominated by border artwork, switch to the
        # first character cell used by common sprite-showcase banners.
        if x2 - x1 > 260 or y2 - y1 > 260:
            x1, x2 = int(width * 0.085), int(width * 0.160)
            y1, y2 = int(height * 0.46), int(height * 0.65)
        crop = image.crop((max(0, x1 - 4), y1, min(width, x2 + 4), y2))
        if crop.width > 256 or crop.height > 256 or crop.width < 12 or crop.height < 12:
            return False
        # Flood-fill only the outside white background, preserving enclosed whites.
        rgba = crop.copy(); px = rgba.load(); w, h = rgba.size
        stack = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
        seen = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
                continue
            seen.add((x, y))
            r, g, b, a = px[x, y]
            if a == 0 or (r > 235 and g > 235 and b > 235):
                px[x, y] = (r, g, b, 0)
                stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        if rgba.getchannel("A").getbbox() is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(destination)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class SpriteSet:
    set_id: str
    name: str
    source: str
    root: Path
    kind: str
    battle_files: tuple[str, ...]
    field_files: tuple[str, ...]
    ready_preview: str | None
    bundle_files: tuple[dict, ...]
    compatible_jobs: tuple[int, ...]
    has_battle: bool
    has_field: bool
    source_job_id: int | None = None


class SpriteSetLibrary:
    """Reusable class appearance library.

    PNG models are portable between jobs. Magicite imports retain a hidden copy of
    their original engine registration data so Studio can reproduce the working
    outer-target/inner-source mapping used by real FF1PR sprite mods. Bundle
    models can be retargeted by rewriting their internal playable-character ID.
    """

    def __init__(self, working_root: Path, export_root: Path, overlays_root: Path, bundle_root: Path | None = None):
        self.working_root = Path(working_root)
        self.project_root = self.working_root
        self.export_root = Path(export_root)
        self.overlays_root = Path(overlays_root)
        self.bundle_root = Path(bundle_root) if bundle_root else None
        self.game_root = self.bundle_root.parents[3] if self.bundle_root else None
        self.direct_stage_root = self.working_root / 'DirectGameFiles'
        self.root = self.working_root / 'SpriteSets'
        self.root.mkdir(parents=True, exist_ok=True)

    def _manifest(self, folder: Path) -> Path:
        return folder / 'sprite-set.json'

    def _slug(self, value: str) -> str:
        value = re.sub(r'[^A-Za-z0-9._-]+', '-', value.strip()).strip('-').lower()
        return value or 'sprite-set'

    def _unique_folder(self, base: str) -> Path:
        folder = self.root / self._slug(base)
        if not folder.exists():
            return folder
        index = 2
        while (self.root / f'{folder.name}-{index}').exists():
            index += 1
        return self.root / f'{folder.name}-{index}'

    def _write_png_set(self, folder: Path, name: str, source: str,
                       battle: list[Path], field: list[Path], *, overwrite=False,
                       battle_group: Path | None = None, field_group: Path | None = None,
                       source_job_id: int | None = None) -> SpriteSet:
        if folder.exists() and overwrite:
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
        battle_dir, field_dir = folder / 'Battle', folder / 'Field'
        battle_dir.mkdir(exist_ok=True); field_dir.mkdir(exist_ok=True)
        copied_battle, copied_field = [], []
        for path in battle:
            if path.suffix.lower() == '.png' and _visible_png(path):
                shutil.copy2(path, battle_dir / path.name); copied_battle.append(path.name)
        for path in field:
            if path.suffix.lower() == '.png' and _visible_png(path):
                shutil.copy2(path, field_dir / path.name); copied_field.append(path.name)
        # Preserve the complete source Magicite groups invisibly. The UI still
        # exposes only PNG artwork, but these files carry the addressable mapping
        # that makes cross-job assignments load in-game.
        engine_battle = None
        engine_field = None
        engine_root = folder / 'Engine'
        if battle_group and Path(battle_group).is_dir():
            engine_battle = 'Engine/Battle'
            shutil.copytree(Path(battle_group), engine_root / 'Battle')
        if field_group and Path(field_group).is_dir():
            engine_field = 'Engine/Field'
            shutil.copytree(Path(field_group), engine_root / 'Field')

        ready = 'Battle/Default_00.png' if (battle_dir / 'Default_00.png').exists() else (
            'Battle/Ready_00.png' if (battle_dir / 'Ready_00.png').exists() else
            (f'Field/{copied_field[0]}' if copied_field else None))
        payload = {
            'format': 'CrystalLegacySpriteSet', 'version': 2, 'id': folder.name,
            'name': name, 'source': source, 'kind': 'png',
            'battleFiles': copied_battle, 'fieldFiles': copied_field,
            'readyPreview': ready, 'bundleFiles': [], 'compatibleJobs': list(range(1, 13)),
            'hasBattle': bool(copied_battle), 'hasField': bool(copied_field),
            'sourceJobId': source_job_id, 'engineBattle': engine_battle, 'engineField': engine_field,
        }
        self._manifest(folder).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return self.load(folder)

    def _write_bundle_set(self, folder: Path, name: str, source: str,
                          bundles: list[Path], preview: Path | None = None) -> SpriteSet:
        folder.mkdir(parents=True, exist_ok=True)
        bundle_dir = folder / 'Bundles'; bundle_dir.mkdir(exist_ok=True)
        # Keep package artwork separate, but attempt to isolate an actual
        # character figure from it for the Ready selector preview.
        preview_rel = None
        package_artwork_rel = None
        if preview and preview.is_file():
            artwork_target = folder / 'package-artwork.png'
            shutil.copy2(preview, artwork_target)
            package_artwork_rel = artwork_target.name
            ready_target = folder / 'ready-preview.png'
            if _extract_ready_from_package_art(preview, ready_target):
                preview_rel = ready_target.name
        records, jobs = [], set()
        extracted_battle: list[str] = []
        extracted_field: list[str] = []
        extraction_root = folder / 'Extracted'
        for path in sorted(bundles):
            match = BUNDLE_BATTLE.match(path.name) or BUNDLE_FIELD.match(path.name)
            if not match or not _unityfs(path):
                continue
            kind = 'battle' if BUNDLE_BATTLE.match(path.name) else 'field'
            job_id = int(match.group('id'))
            target = bundle_dir / path.name
            shutil.copy2(path, target)
            extracted_dir = extraction_root / ('Battle' if kind == 'battle' else 'Field')
            extracted = extract_bundle_textures(target, extracted_dir)
            extracted_names = [item.output_file for item in extracted]
            if kind == 'battle':
                allowed = set(BATTLE_REQUIRED + BATTLE_OPTIONAL)
                extracted_battle.extend(name for name in extracted_names if name in allowed)
                extracted_names = [name for name in extracted_names if name in allowed]
            else:
                extracted_field.extend(extracted_names)
            records.append({
                'file': path.name, 'kind': kind, 'jobId': job_id, 'sha256': _sha(target),
                'extractedFiles': extracted_names,
                'extractionInventory': str((extracted_dir / 'bundle-extraction.json').relative_to(folder)).replace('\\', '/'),
            })
            jobs.add(job_id)
        if not records:
            raise ValueError('No valid FF1 UnityFS character bundles were found.')
        payload = {
            'format': 'CrystalLegacySpriteSet', 'version': 2, 'id': folder.name,
            'name': name, 'source': source, 'kind': 'bundle',
            'battleFiles': sorted(dict.fromkeys(extracted_battle)),
            'fieldFiles': sorted(dict.fromkeys(extracted_field)),
            'readyPreview': (
                'Extracted/Battle/Default_00.png' if (extraction_root / 'Battle' / 'Default_00.png').is_file() else
                'Extracted/Battle/Ready_00.png' if (extraction_root / 'Battle' / 'Ready_00.png').is_file() else
                preview_rel
            ),
            'bundleFiles': records, 'compatibleJobs': sorted(jobs),
            'packageArtwork': package_artwork_rel,
            'hasBattle': any(r['kind'] == 'battle' for r in records),
            'hasField': any(r['kind'] == 'field' for r in records),
        }
        self._manifest(folder).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return self.load(folder)

    def _component_png_paths(self, sprite_set: SpriteSet, component: str) -> list[Path]:
        component = 'battle' if component == 'battle' else 'field'
        if sprite_set.kind == 'bundle':
            base = sprite_set.root / 'Extracted' / ('Battle' if component == 'battle' else 'Field')
            names = sprite_set.battle_files if component == 'battle' else sprite_set.field_files
        else:
            base = sprite_set.root / ('Battle' if component == 'battle' else 'Field')
            names = sprite_set.battle_files if component == 'battle' else sprite_set.field_files
        result = []
        for name in names:
            candidate = base / Path(name).name
            if candidate.is_file() and _visible_png(candidate):
                result.append(candidate)
        return result

    @staticmethod
    def _recolor_image_multi(source: Path, destination: Path,
                             mappings: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
                             tolerance: int = 42) -> None:
        """Apply several palette substitutions while preserving shade and alpha.

        Each source color family is evaluated independently. A pixel is changed by
        only the closest enabled palette slot, which prevents a broad armor recolor
        from swallowing accent colors assigned to another slot.
        """
        import colorsys
        with Image.open(source) as opened:
            image = opened.convert('RGBA')
        prepared = []
        for src, dst in mappings:
            sh, ss, sv = colorsys.rgb_to_hsv(*(v / 255 for v in src))
            dh, ds, dv = colorsys.rgb_to_hsv(*(v / 255 for v in dst))
            prepared.append((src, dst, sh, ss, sv, dh, ds, dv))
        max_distance = max(4, min(180, int(tolerance)))
        out = []
        for r, g, b, a in image.getdata():
            if a == 0 or not prepared:
                out.append((r, g, b, a)); continue
            best = None
            best_distance = 10**9
            for record in prepared:
                src, dst, sh, ss, sv, dh, ds, dv = record
                # RGB distance is predictable for pixel-art palettes and keeps
                # nearby accent families independently selectable.
                distance = ((r-src[0])**2 + (g-src[1])**2 + (b-src[2])**2) ** 0.5
                if distance < best_distance:
                    best_distance, best = distance, record
            if best is None or best_distance > max_distance:
                out.append((r, g, b, a)); continue
            src, dst, sh, ss, sv, dh, ds, dv = best
            h, sat, val = colorsys.rgb_to_hsv(r/255, g/255, b/255)
            if ds < 0.08:
                shade = max(0.05, min(1.8, val / max(sv, 0.08)))
                nr = int(max(0, min(255, dst[0] * shade)))
                ng = int(max(0, min(255, dst[1] * shade)))
                nb = int(max(0, min(255, dst[2] * shade)))
            else:
                new_v = max(0.02, min(1.0, dv * (val / max(sv, 0.08))))
                # Preserve local saturation differences used for highlights.
                new_s = max(0.0, min(1.0, ds * (0.72 + 0.28 * sat)))
                rr, gg, bb = colorsys.hsv_to_rgb(dh, new_s, new_v)
                nr, ng, nb = int(rr*255), int(gg*255), int(bb*255)
            out.append((nr, ng, nb, a))
        image.putdata(out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)

    def create_recolor(self, battle_set: SpriteSet | None, field_set: SpriteSet | None,
                       name: str,
                       mappings: list[tuple[tuple[int, int, int], tuple[int, int, int]]],
                       tolerance: int = 42) -> SpriteSet:
        battle_paths = self._component_png_paths(battle_set, 'battle') if battle_set else []
        field_paths = self._component_png_paths(field_set, 'field') if field_set else []
        if not battle_paths and not field_paths:
            raise ValueError('The selected appearance has no extracted PNG artwork to recolor.')
        if not mappings:
            raise ValueError('Enable at least one palette color before creating a recolor.')
        folder = self._unique_folder(name)
        folder.mkdir(parents=True, exist_ok=True)
        battle_dir, field_dir = folder / 'Battle', folder / 'Field'
        battle_dir.mkdir(exist_ok=True); field_dir.mkdir(exist_ok=True)
        for source in battle_paths:
            self._recolor_image_multi(source, battle_dir / source.name, mappings, tolerance)
        for source in field_paths:
            self._recolor_image_multi(source, field_dir / source.name, mappings, tolerance)
        battle_names = sorted(p.name for p in battle_dir.glob('*.png') if _visible_png(p))
        field_names = sorted(p.name for p in field_dir.glob('*.png') if _visible_png(p))
        preview = 'Battle/Default_00.png' if (battle_dir / 'Default_00.png').is_file() else (
            'Battle/Ready_00.png' if (battle_dir / 'Ready_00.png').is_file() else
            (f'Field/{field_names[0]}' if field_names else None))
        payload = {
            'format': 'CrystalLegacySpriteSet', 'version': 2, 'id': folder.name,
            'name': name, 'source': 'Crystal Legacy Studio Recolor', 'kind': 'png',
            'battleFiles': battle_names, 'fieldFiles': field_names,
            'readyPreview': preview, 'bundleFiles': [], 'compatibleJobs': list(range(1, 13)),
            'hasBattle': bool(battle_names), 'hasField': bool(field_names),
            'recolor': {
                'mappings': [{'source': list(src), 'target': list(dst)} for src, dst in mappings],
                'tolerance': int(tolerance),
            },
        }
        self._manifest(folder).write_text(json.dumps(payload, indent=2), encoding='utf-8')
        return self.load(folder)

    def load(self, folder: Path) -> SpriteSet:
        manifest = self._manifest(folder)
        data = json.loads(manifest.read_text(encoding='utf-8'))
        kind = data.get('kind', 'png')
        ready_preview = data.get('readyPreview')

        # Alpha 12 Test 7 could save a Nexus banner as preview.png. Migrate those
        # records automatically so an old promotional screenshot can never be
        # displayed as the selected character's Ready frame.
        if kind == 'bundle' and ready_preview:
            preview_name = Path(ready_preview).name.lower()
            if preview_name != 'ready-preview.png':
                data['packageArtwork'] = ready_preview
                data['readyPreview'] = None
                ready_preview = None
                manifest.write_text(json.dumps(data, indent=2), encoding='utf-8')

        return SpriteSet(
            data['id'], data['name'], data.get('source', 'Unknown'), folder,
            kind, tuple(data.get('battleFiles', [])),
            tuple(data.get('fieldFiles', [])), ready_preview,
            tuple(data.get('bundleFiles', [])), tuple(int(v) for v in data.get('compatibleJobs', range(1, 13))),
            bool(data.get('hasBattle', data.get('battleFiles') or any(r.get('kind') == 'battle' for r in data.get('bundleFiles', [])))),
            bool(data.get('hasField', data.get('fieldFiles') or any(r.get('kind') == 'field' for r in data.get('bundleFiles', [])))),
            int(data['sourceJobId']) if data.get('sourceJobId') not in (None, '') else None,
        )

    def _deleted_registry(self) -> Path:
        return self.root / '.deleted-models.json'

    def _deleted_model_ids(self) -> set[str]:
        try:
            return set(json.loads(self._deleted_registry().read_text(encoding='utf-8')))
        except Exception:
            return set()

    def _remember_deleted(self, folder_name: str) -> None:
        values = self._deleted_model_ids()
        values.add(folder_name)
        self._deleted_registry().write_text(json.dumps(sorted(values), indent=2), encoding='utf-8')

    def delete(self, sprite_set: SpriteSet) -> None:
        """Delete one saved library model without touching game or staged files."""
        if not sprite_set.root.exists() or sprite_set.root.parent.resolve() != self.root.resolve():
            raise ValueError('The selected model is not stored in this Sprite Library.')
        if sprite_set.source == 'MagiciteExport default' or sprite_set.root.name.startswith('default-p'):
            raise ValueError('Default game models are protected. Imported and custom models can be deleted.')
        self._remember_deleted(sprite_set.root.name)
        shutil.rmtree(sprite_set.root)

    def rename(self, sprite_set: SpriteSet, new_name: str) -> SpriteSet:
        new_name = (new_name or '').strip()
        if not new_name:
            raise ValueError('A model name is required.')
        data = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
        data['name'] = new_name
        self._manifest(sprite_set.root).write_text(json.dumps(data, indent=2), encoding='utf-8')
        return self.load(sprite_set.root)

    def set_ready_preview(self, sprite_set: SpriteSet, image_path: Path) -> SpriteSet:
        image_path = Path(image_path)
        if not image_path.is_file() or image_path.suffix.lower() != '.png' or not _visible_png(image_path):
            raise ValueError('The Ready preview must be a visible PNG image.')
        target = sprite_set.root / 'ready-preview.png'
        shutil.copy2(image_path, target)
        data = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
        data['readyPreview'] = target.name
        self._manifest(sprite_set.root).write_text(json.dumps(data, indent=2), encoding='utf-8')
        return self.load(sprite_set.root)

    def _split_legacy_combined_bundle(self, item: SpriteSet) -> bool:
        """Migrate old bundle records that stored battle and field together.

        Returns True when the original record was replaced by two independent
        component records. This keeps old Test 7-18 libraries usable without
        requiring users to hunt down stale folders manually.
        """
        if item.kind != 'bundle' or not (item.has_battle and item.has_field):
            return False
        battle = []
        field = []
        for record in item.bundle_files:
            candidate = item.root / 'Bundles' / str(record.get('file', ''))
            if not candidate.is_file() or not _unityfs(candidate):
                continue
            (battle if record.get('kind') == 'battle' else field).append(candidate)
        if not battle or not field:
            return False
        preview = item.root / item.ready_preview if item.ready_preview else None
        self._write_bundle_set(self._unique_folder(f'{item.name} [Battle]'),
                               f'{item.name} [Battle]', item.source, battle,
                               preview if preview and preview.is_file() else None)
        self._write_bundle_set(self._unique_folder(f'{item.name} [Overworld]'),
                               f'{item.name} [Overworld]', item.source, field, None)
        self._remember_deleted(item.root.name)
        shutil.rmtree(item.root, ignore_errors=True)
        return True

    def list_sets(self) -> list[SpriteSet]:
        """Return only models whose saved payload still exists on disk.

        Older builds could leave a manifest behind after files were manually
        removed. Those ghost records remained in comboboxes and could even look
        protected when a different default model was selected for deletion.
        """
        result = []
        for manifest in sorted(self.root.glob('*/sprite-set.json')):
            folder = manifest.parent
            try:
                item = self.load(folder)
                if self._split_legacy_combined_bundle(item):
                    continue
                if item.kind == 'bundle':
                    valid = []
                    for record in item.bundle_files:
                        candidate = folder / 'Bundles' / str(record.get('file', ''))
                        if candidate.is_file() and _unityfs(candidate):
                            valid.append(record)
                    if not valid:
                        if not folder.name.startswith('default-p'):
                            shutil.rmtree(folder, ignore_errors=True)
                        continue
                else:
                    battle_files = [folder / 'Battle' / Path(name).name for name in item.battle_files]
                    field_files = [folder / 'Field' / Path(name).name for name in item.field_files]
                    has_battle_payload = any(path.is_file() and _visible_png(path) for path in battle_files)
                    has_field_payload = any(path.is_file() and _visible_png(path) for path in field_files)
                    if not has_battle_payload and not has_field_payload:
                        if not folder.name.startswith('default-p'):
                            shutil.rmtree(folder, ignore_errors=True)
                        continue
                result.append(item)
            except Exception:
                # Broken imported records are removable clutter. Defaults are
                # regenerated safely by sync_defaults on the next refresh.
                if not folder.name.startswith('default-p'):
                    shutil.rmtree(folder, ignore_errors=True)
                continue
        return sorted(result, key=lambda item: item.name.lower())

    def sync_defaults(self) -> int:
        created = 0
        for job_id in range(1, 13):
            pid = f'{job_id:03d}'; folder = self.root / f'default-p{pid}'
            battle_group = _find_group(self.export_root, f'bc_ff1_p{pid}')
            field_group = _find_group(self.export_root, f'mo_ff1_p{pid}_c00')
            battle = _pngs(battle_group)
            field = _pngs(field_group)
            needs_refresh = True
            if self._manifest(folder).exists():
                try:
                    current = json.loads(self._manifest(folder).read_text(encoding='utf-8'))
                    needs_refresh = not current.get('engineBattle') and not current.get('engineField')
                except Exception:
                    needs_refresh = True
            if (battle or field) and needs_refresh:
                self._write_png_set(folder, f'Default Class p{pid}', 'MagiciteExport default', battle, field,
                                    overwrite=True, battle_group=battle_group, field_group=field_group,
                                    source_job_id=job_id)
                created += 1
        return created

    def sync_current_imports(self) -> int:
        created = 0
        for job_id in range(1, 13):
            pid = f'{job_id:03d}'
            battle = _pngs(_find_group(self.overlays_root, f'bc_ff1_p{pid}'))
            field = _pngs(_find_group(self.overlays_root, f'mo_ff1_p{pid}_c00'))
            if not battle and not field: continue
            signature = hashlib.sha256(''.join(_sha(p) for p in battle + field).encode()).hexdigest()[:12]
            folder = self.root / f'imported-p{pid}-{signature}'
            if folder.name in self._deleted_model_ids():
                continue
            if not self._manifest(folder).exists():
                self._write_png_set(folder, f'Imported Class p{pid} ({signature[:6]})', 'Current working/imported mod', battle, field, battle_group=_find_group(self.overlays_root, f'bc_ff1_p{pid}'), field_group=_find_group(self.overlays_root, f'mo_ff1_p{pid}_c00'), source_job_id=job_id)
                created += 1
        return created

    def _bundle_groups(self, root: Path) -> list[tuple[str, list[Path], Path | None]]:
        """Split multi-model archives into one reusable model per encoded job ID.

        A folder such as Blue Knight containing p001 and p007 is deliberately
        broken into two independently named records. Battle and field bundles are
        paired only when they encode the same playable-character ID.
        """
        found = [p for p in root.rglob('*.bundle') if BUNDLE_BATTLE.match(p.name) or BUNDLE_FIELD.match(p.name)]
        if not found:
            return []
        containers: dict[Path, list[Path]] = {}
        for path in found:
            key = path.parent.parent if path.parent.name.lower() == 'standalonewindows64' else path.parent
            containers.setdefault(key, []).append(path)
        result = []
        for key, bundles in containers.items():
            previews = [p for p in key.glob('*.png') if _visible_png(p)]
            package_preview = previews[0] if previews else None
            by_job: dict[int, list[Path]] = {}
            for bundle in bundles:
                match = BUNDLE_BATTLE.match(bundle.name) or BUNDLE_FIELD.match(bundle.name)
                if match:
                    by_job.setdefault(int(match.group('id')), []).append(bundle)
            for job_id, job_bundles in sorted(by_job.items()):
                base = key.name or root.name
                name = f'{base} — p{job_id:03d}' if len(by_job) > 1 else base
                # Promotional art is package metadata, not a Ready preview. Keep it
                # out of the job selector unless the user explicitly sets it.
                result.append((name, job_bundles, package_preview))
        return result

    def import_source(self, source: Path) -> list[SpriteSet]:
        source = Path(source); temporary = None; root = source
        if source.is_file() and zipfile.is_zipfile(source):
            temporary = tempfile.TemporaryDirectory(prefix='cl-sprites-'); root = Path(temporary.name)
            with zipfile.ZipFile(source, 'r') as archive: archive.extractall(root)
        try:
            bundle_groups = self._bundle_groups(root)
            if bundle_groups:
                imported = []
                for group_name, bundles, preview in bundle_groups:
                    base_name = group_name if group_name and group_name != root.name else source.stem
                    battle_bundles = [b for b in bundles if BUNDLE_BATTLE.match(b.name)]
                    field_bundles = [b for b in bundles if BUNDLE_FIELD.match(b.name)]
                    # Battle and overworld bundles are independent library assets.
                    # Keeping them in separate records makes selection, renaming,
                    # deletion, and mixed assignments unambiguous.
                    if battle_bundles:
                        name = f'{base_name} [Battle]'
                        imported.append(self._write_bundle_set(
                            self._unique_folder(name), name,
                            f'Battle bundle imported from {source.name}', battle_bundles, preview))
                    if field_bundles:
                        name = f'{base_name} [Overworld]'
                        imported.append(self._write_bundle_set(
                            self._unique_folder(name), name,
                            f'Overworld bundle imported from {source.name}', field_bundles, None))
                return imported

            # Magicite class archives often contain several bc_ff1_p### and
            # mo_ff1_p###_c00 resource groups. Treat each playable-character ID
            # as its own reusable appearance instead of combining duplicate
            # filenames from every class into one corrupted model.
            battle_groups = {}
            field_groups = {}
            for path in root.rglob('*'):
                if not path.is_dir():
                    continue
                # Only the OUTER Magicite resource group is valid. Inner Unity
                # asset folders use uppercase BC_FF1/MO_FF1 names and do not own
                # keys/Export.json. Treating those as groups loses registration
                # metadata and can also combine the wrong class artwork.
                export_json = path / 'keys' / 'Export.json'
                match = re.fullmatch(r'bc_ff1_p(\d{3})', path.name)
                if match and export_json.is_file():
                    battle_groups[int(match.group(1))] = path
                    continue
                match = re.fullmatch(r'mo_ff1_p(\d{3})_c00', path.name)
                if match and export_json.is_file():
                    field_groups[int(match.group(1))] = path

            grouped_ids = sorted(set(battle_groups) | set(field_groups))
            if grouped_ids:
                imported = []
                for job_id in grouped_ids:
                    battle = _pngs(battle_groups.get(job_id))
                    field = _pngs(field_groups.get(job_id))
                    # Empty placeholder resource groups are not real components.
                    battle = [p for p in battle if _visible_png(p)]
                    field = [p for p in field if _visible_png(p)]
                    if not battle and not field:
                        continue
                    if battle:
                        present = {p.name for p in battle}
                        missing = [item for item in BATTLE_REQUIRED if item not in present]
                        if missing:
                            raise ValueError(
                                f'Class p{job_id:03d} has an incomplete battle set. Missing: ' + ', '.join(missing))
                    name = f'{source.stem} — p{job_id:03d}'
                    imported.append(self._write_png_set(
                        self._unique_folder(name), name,
                        f'Magicite class resources imported from {source.name}', battle, field,
                        battle_group=battle_groups.get(job_id), field_group=field_groups.get(job_id),
                        source_job_id=job_id))
                if imported:
                    # Every generated model must retain one exact source class ID.
                    # Refuse a suspicious archive instead of silently combining
                    # files from multiple classes with duplicate frame names.
                    for model in imported:
                        data = json.loads(self._manifest(model.root).read_text(encoding='utf-8'))
                        if int(data.get('sourceJobId') or 0) not in grouped_ids:
                            raise RuntimeError(f'Imported model {model.name} lost its source class identity.')
                    return imported

            battle = [p for p in root.rglob('*.png') if 'battle' in p.as_posix().lower() or p.name in BATTLE_REQUIRED + BATTLE_OPTIONAL]
            field = [p for p in root.rglob('*.png') if '/map/' in p.as_posix().lower() or 'field' in p.as_posix().lower() or p.name.lower().startswith('sactx-')]
            field = [p for p in field if p not in set(battle)]
            present = {p.name for p in battle if _visible_png(p)}
            missing = [item for item in BATTLE_REQUIRED if item not in present]
            if missing and not field:
                raise ValueError('No bundle mod was detected, and the PNG sprite project is incomplete. Missing: ' + ', '.join(missing))
            return [self._write_png_set(self._unique_folder(source.stem), source.stem, f'PNG set imported from {source.name}', battle, field)]
        finally:
            if temporary: temporary.cleanup()

    def import_folder_or_zip(self, source: Path, name: str | None = None) -> SpriteSet:
        items = self.import_source(source)
        if name and len(items) == 1:
            # Preserve legacy test/API behavior; imported content is already valid.
            pass
        return items[0]

    @staticmethod
    def _read_sprite_rect(path: Path) -> tuple[int, int, int, int] | None:
        try:
            text = path.read_text(encoding='utf-8-sig')
        except Exception:
            return None
        match = re.search(r'^\s*Rect\s*=\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]', text, re.M)
        if not match:
            return None
        return tuple(int(round(float(value))) for value in match.groups())

    @staticmethod
    def _read_texture_override(path: Path) -> str | None:
        """Read the atlas reference from a Magicite .spritedata file."""
        try:
            text = path.read_text(encoding='utf-8-sig')
        except Exception:
            return None
        match = re.search(r'^\s*TextureOverride\s*=\s*(.+?)\s*$', text, re.M)
        if not match:
            return None
        return match.group(1).strip().strip('"').replace('\\', '/')

    def ensure_field_default_preview(self, sprite_set: SpriteSet) -> Path | None:
        """Create a clean overworld thumbnail from Default_00.spritedata.

        The map texture is a packed 128x64 atlas. Displaying the whole atlas (or
        guessing a grid cell) produces tiny or incorrect previews. The canonical
        standing pose is defined by Default_00.spritedata, whose Rect uses Unity's
        bottom-left coordinate system. This method crops that exact rectangle and
        caches it without modifying the imported model or source atlas.
        """
        cached = sprite_set.root / 'field-default-preview.png'
        if cached.is_file() and _visible_png(cached):
            return cached

        try:
            manifest = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
        except Exception:
            manifest = {}

        metadata_roots: list[Path] = []
        engine_rel = manifest.get('engineField')
        if engine_rel and (sprite_set.root / engine_rel).is_dir():
            metadata_roots.append(sprite_set.root / engine_rel)

        source_job = int(manifest.get('sourceJobId') or sprite_set.source_job_id or 0)
        if not source_job:
            records = [r for r in sprite_set.bundle_files if r.get('kind') == 'field']
            if records:
                try:
                    source_job = int(records[0].get('jobId') or 0)
                except Exception:
                    source_job = 0
        if source_job:
            source_group = _find_group(self.export_root, f'mo_ff1_p{source_job:03d}_c00')
            if source_group:
                metadata_roots.append(source_group)

        sprite_data = None
        for root in metadata_roots:
            candidates = list(root.rglob('Default_00.spritedata'))
            if candidates:
                sprite_data = candidates[0]
                break
        if not sprite_data:
            return None
        rect = self._read_sprite_rect(sprite_data)
        if not rect:
            return None

        component_root = sprite_set.root / ('Extracted/Field' if sprite_set.kind == 'bundle' else 'Field')
        pngs = [p for p in component_root.rglob('*.png') if p.is_file() and _visible_png(p)] if component_root.is_dir() else []
        if not pngs:
            return None

        override = self._read_texture_override(sprite_data)
        atlas = None
        if override:
            wanted = Path(override).name.lower()
            atlas = next((p for p in pngs if p.stem.lower() == wanted or p.name.lower() == wanted + '.png'), None)
            if atlas is None:
                # Retargeted or bundle-extracted atlases can have a different hash
                # suffix while retaining the same logical sactx texture family.
                prefix = re.sub(r'-[0-9a-f]{8,}$', '', wanted, flags=re.I)
                atlas = next((p for p in pngs if p.stem.lower().startswith(prefix.lower())), None)
        if atlas is None:
            atlas = next((p for p in pngs if p.name.lower().startswith('sactx-')), pngs[0])

        try:
            with Image.open(atlas) as opened:
                image = opened.convert('RGBA')
            x, y, width, height = rect
            if width <= 0 or height <= 0:
                return None
            left, top = x, image.height - y - height
            if left < 0 or top < 0 or left + width > image.width or top + height > image.height:
                return None
            frame = image.crop((left, top, left + width, top + height))
            if frame.getchannel('A').getbbox() is None:
                return None
            cached.parent.mkdir(parents=True, exist_ok=True)
            frame.save(cached)
            return cached
        except Exception:
            return None

    def _remap_extracted_field_atlas(self, sprite_set: SpriteSet, target_root: Path, source_png: Path, target_png: Path) -> bool:
        """Rebuild an overworld atlas using source and target frame names.

        Different FF1PR jobs use different physical atlas positions for the same
        logical frames. A p012 bundle sheet copied over p001 metadata can therefore
        show WalkL when the player presses Down. The original source job is known
        from the bundle filename, and MagiciteExport contains that job's untouched
        .spritedata map. Studio crops every named frame with the SOURCE map and
        pastes it into the TARGET map, preserving correct directional controls.
        """
        source_job = None
        field_records = [r for r in sprite_set.bundle_files if r.get('kind') == 'field']
        if field_records:
            try:
                source_job = int(field_records[0].get('jobId'))
            except Exception:
                source_job = None
        if source_job is None:
            try:
                manifest = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
                source_job = int(manifest.get('sourceJobId'))
            except Exception:
                return False

        source_group = _find_group(self.export_root, f'mo_ff1_p{source_job:03d}_c00')
        if not source_group or not source_group.is_dir():
            return False
        source_rects = {}
        try:
            manifest = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
        except Exception:
            manifest = {}
        engine_rel = manifest.get('engineField')
        source_roots = []
        if engine_rel and (sprite_set.root / engine_rel).is_dir():
            source_roots.append(sprite_set.root / engine_rel)
        source_roots.append(source_group)
        for root in source_roots:
            for data_file in root.rglob('*.spritedata'):
                rect = self._read_sprite_rect(data_file)
                if rect:
                    source_rects[data_file.stem] = rect
            if source_rects:
                break

        target_rects = {}
        for data_file in target_root.rglob('*.spritedata'):
            rect = self._read_sprite_rect(data_file)
            if rect:
                target_rects[data_file.stem] = rect
        shared = sorted(set(source_rects) & set(target_rects))
        if not shared or not source_png.is_file() or not target_png.is_file():
            return False

        with Image.open(source_png) as opened_source, Image.open(target_png) as opened_target:
            source = opened_source.convert('RGBA')
            target = Image.new('RGBA', opened_target.size, (0, 0, 0, 0))
            copied = 0
            for name in shared:
                sx, sy, sw, sh = source_rects[name]
                tx, ty, tw, th = target_rects[name]
                if min(sw, sh, tw, th) <= 0:
                    continue
                source_box = (sx, source.height - sy - sh, sx + sw, source.height - sy)
                frame = source.crop(source_box)
                if frame.size != (tw, th):
                    frame = frame.resize((tw, th), Image.Resampling.NEAREST)
                target_y = target.height - ty - th
                target.alpha_composite(frame, (tx, target_y))
                copied += 1
            if copied != len(shared):
                return False
            target.save(target_png)
        return True

    def _apply_png(self, sprite_set: SpriteSet, job_id: int) -> list[Path]:
        """Stage a portable PNG appearance as a complete Magicite resource group.

        Working FF1PR class packs use an important two-part mapping: the outer
        resource group and inner asset directory identify the TARGET job, while
        keys/Export.json and source-named atlas files retain the SOURCE sprite
        addresses. Cloning target metadata destroys that mapping and the game
        silently keeps its original sprite. Studio therefore retains and reuses
        hidden source engine templates whenever an imported Magicite set has them.
        """
        pid = f'{job_id:03d}'
        written: list[Path] = []
        manifest = json.loads(self._manifest(sprite_set.root).read_text(encoding='utf-8'))
        source_job = int(manifest.get('sourceJobId') or job_id)

        def retarget_engine_group(target_root: Path, kind: str) -> None:
            """Retarget every logical asset address, not only the outer folders.

            Magicite's keys/Export.json is the authoritative mapping. Some working
            class packs deliberately store a p010 resource group whose Export.json
            points at P007. Copying that group to p004 without rewriting those
            values makes the overworld atlas override job 7 instead of job 4.
            """
            target_token = (f'BC_FF1_P{job_id:03d}' if kind == 'battle'
                            else f'MO_FF1_P{job_id:03d}_C00')
            export_file = target_root / 'keys' / 'Export.json'
            source_tokens = set()
            if export_file.is_file():
                try:
                    payload = json.loads(export_file.read_text(encoding='utf-8-sig'))
                    pattern = (r'BC_FF1_P\d{3}' if kind == 'battle'
                               else r'MO_FF1_P\d{3}_C00')
                    for value in payload.get('values', []):
                        source_tokens.update(re.findall(pattern, str(value), flags=re.I))
                    for value in payload.get('keys', []):
                        source_tokens.update(re.findall(pattern, str(value), flags=re.I))
                except Exception:
                    pass
            # Include physical source names as fallbacks, but never rewrite the
            # already-correct target token away.
            physical = (f'BC_FF1_P{source_job:03d}' if kind == 'battle'
                        else f'MO_FF1_P{source_job:03d}_C00')
            source_tokens.add(physical)
            source_tokens = {t for t in source_tokens if t.lower() != target_token.lower()}

            # Rewrite text metadata: Export.json, .spritedata, .atlas, anim_info.
            for file in [p for p in target_root.rglob('*') if p.is_file() and
                         p.suffix.lower() in {'.json', '.spritedata', '.atlas'}]:
                try:
                    text = file.read_text(encoding='utf-8-sig')
                except Exception:
                    continue
                updated = text
                for token in source_tokens:
                    updated = re.sub(re.escape(token), target_token, updated, flags=re.I)
                if updated != text:
                    file.write_text(updated, encoding='utf-8')

            # Rename files and directories containing the logical source token,
            # including the field atlas and sactx texture filename. Deepest first.
            paths = sorted(target_root.rglob('*'), key=lambda x: len(x.parts), reverse=True)
            for path in paths:
                name = path.name
                updated_name = name
                for token in source_tokens:
                    updated_name = re.sub(re.escape(token), target_token, updated_name, flags=re.I)
                if updated_name != name:
                    destination = path.with_name(updated_name)
                    if destination.exists():
                        if path.is_dir():
                            shutil.rmtree(destination)
                        else:
                            destination.unlink()
                    path.rename(destination)

        def stage_component(kind: str, filenames: tuple[str, ...]) -> None:
            if not filenames:
                return
            group_name = (f'bc_ff1_p{pid}' if kind == 'battle' else f'mo_ff1_p{pid}_c00')
            engine_rel = manifest.get('engineBattle' if kind == 'battle' else 'engineField')
            engine_source = sprite_set.root / engine_rel if engine_rel else None
            target_root = self.overlays_root / group_name
            if target_root.exists():
                shutil.rmtree(target_root)

            if ('Magicite class resources imported from' in sprite_set.source
                    and (not engine_source or not engine_source.is_dir())):
                raise RuntimeError(
                    'This model was imported by an older Studio build without its hidden Magicite engine template. '
                    'Delete it and import the original ZIP again before applying it.')

            # Battle packs can safely retain their source engine template.
            # Overworld animation directions are controlled by the TARGET job's
            # .spritedata/atlas layout, so always start field deployment from the
            # untouched target reference and remap imported artwork by frame name.
            if kind == 'battle' and engine_source and engine_source.is_dir():
                shutil.copytree(engine_source, target_root)
                retarget_engine_group(target_root, kind)
            else:
                reference = _find_group(self.export_root, group_name)
                if not reference:
                    raise FileNotFoundError(f'No {kind} reference exists for p{pid}.')
                shutil.copytree(reference, target_root)

            if kind == 'battle':
                for filename in filenames:
                    candidates = list(target_root.rglob(filename))
                    if candidates:
                        shutil.copy2(sprite_set.root / 'Battle' / filename, candidates[0])
            else:
                target_pngs = _pngs(target_root)
                if target_pngs:
                    source_png = sprite_set.root / 'Field' / filenames[0]
                    # Bundle-extracted field sheets must be reordered by Sprite
                    # name. Loose Magicite sheets already match their metadata and
                    # can still be copied directly.
                    if not self._remap_extracted_field_atlas(sprite_set, target_root, source_png, target_pngs[0]):
                        shutil.copy2(source_png, target_pngs[0])
            written.extend(path for path in target_root.rglob('*') if path.is_file())

        stage_component('battle', sprite_set.battle_files)
        stage_component('field', sprite_set.field_files)
        return list(dict.fromkeys(written))

    def _apply_bundle(self, sprite_set: SpriteSet, job_id: int) -> list[Path]:
        if not self.bundle_root or not self.bundle_root.is_dir() or not self.game_root:
            raise FileNotFoundError('The game Addressables bundle folder is unavailable.')
        written = []
        # Prefer the source record that matches the chosen component/job. When a
        # model was compiled for another class, rebuild it with the target P###
        # identifiers instead of blocking assignment.
        for kind in ('battle', 'field'):
            candidates = [r for r in sprite_set.bundle_files if r.get('kind') == kind]
            if not candidates:
                continue
            record = next((r for r in candidates if int(r['jobId']) == job_id), candidates[0])
            source_job = int(record['jobId'])
            logical = ('bc_ff1_' if kind == 'battle' else 'mo_ff1_') + (
                f'p{job_id:03d}_assets_all_' if kind == 'battle' else f'p{job_id:03d}_c00_assets_all_')
            matches = sorted(p for p in self.bundle_root.glob(f'{logical}*.bundle') if p.is_file())
            if len(matches) != 1:
                raise FileNotFoundError(f'Expected exactly one installed target bundle for {logical}, found {len(matches)}.')
            live = matches[0]
            relative = live.relative_to(self.game_root)
            target = self.direct_stage_root / relative
            source = sprite_set.root / 'Bundles' / record['file']
            if source_job == job_id:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            else:
                _retarget_unityfs_bundle(source, target, source_job, job_id)
            written.append(target)
        if not written:
            raise RuntimeError(f'The model has no battle or field bundle that can be assigned to job {job_id}.')
        return written

    def apply(self, sprite_set: SpriteSet, job_id: int, component: str = 'both') -> list[Path]:
        component = component.lower()
        if component not in {'battle', 'field', 'both'}:
            raise ValueError('Component must be battle, field, or both.')
        if sprite_set.kind == 'bundle':
            # Prefer the internally extracted PNG payload. This produces normal
            # Magicite bc/mo resource groups that are included in Save, Build
            # Package, import/merge, and the live Crystal Legacy folder. Earlier
            # builds only staged Addressables bundles in DirectGameFiles, so a
            # package ZIP could contain battle data but no mo_ff1 overworld group.
            extracted_battle = sprite_set.root / 'Extracted' / 'Battle'
            extracted_field = sprite_set.root / 'Extracted' / 'Field'
            battle_files = tuple(p.name for p in sorted(extracted_battle.glob('*.png')) if _visible_png(p) and p.name in set(BATTLE_REQUIRED + BATTLE_OPTIONAL))
            field_files = tuple(p.name for p in sorted(extracted_field.glob('*.png')) if _visible_png(p))
            requested_battle = component in {'battle', 'both'} and bool(battle_files)
            requested_field = component in {'field', 'both'} and bool(field_files)
            if requested_battle or requested_field:
                portable = SpriteSet(
                    sprite_set.set_id, sprite_set.name, sprite_set.source, sprite_set.root, 'png',
                    battle_files if requested_battle else tuple(),
                    field_files if requested_field else tuple(),
                    sprite_set.ready_preview, sprite_set.bundle_files, sprite_set.compatible_jobs,
                    requested_battle, requested_field,
                )
                # _apply_png expects files in Battle/Field. Mirror extracted files
                # into those hidden working folders without exposing engine data.
                if requested_battle:
                    target_dir = sprite_set.root / 'Battle'
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for name in battle_files:
                        shutil.copy2(extracted_battle / name, target_dir / name)
                if requested_field:
                    target_dir = sprite_set.root / 'Field'
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for name in field_files:
                        shutil.copy2(extracted_field / name, target_dir / name)
                return self._apply_png(portable, int(job_id))
            # Fall back to exact whole-bundle staging only when extraction found no
            # supported textures.
            written = self._apply_bundle(sprite_set, int(job_id))
            if component != 'both':
                wanted = 'bc_ff1_' if component == 'battle' else 'mo_ff1_'
                for path in list(written):
                    if wanted not in path.name.lower():
                        try: path.unlink()
                        except OSError: pass
                        written.remove(path)
            return written
        if component == 'both':
            return self._apply_png(sprite_set, int(job_id))
        original_battle, original_field = sprite_set.battle_files, sprite_set.field_files
        filtered = SpriteSet(sprite_set.set_id, sprite_set.name, sprite_set.source, sprite_set.root, sprite_set.kind,
                             original_battle if component == 'battle' else tuple(),
                             original_field if component == 'field' else tuple(), sprite_set.ready_preview,
                             sprite_set.bundle_files, sprite_set.compatible_jobs,
                             sprite_set.has_battle if component == 'battle' else False,
                             sprite_set.has_field if component == 'field' else False)
        return self._apply_png(filtered, int(job_id))


class SpriteSetSelector(ttk.Frame):
    """User-facing character appearance picker.

    Battle and overworld appearances are selected independently so projects can
    mix a battle-only mod with a separate field/overworld sprite model.
    """

    def __init__(self, parent, library: SpriteSetLibrary, *, on_status=None, on_dirty=None):
        super().__init__(parent, padding=12)
        self.library = library
        self.on_status = on_status or (lambda *_: None)
        self.on_dirty = on_dirty or (lambda *_: None)
        self.job_id = None
        self.job_name = ''
        self.items: list[SpriteSet] = []
        self.preview_image = None
        self.mosaic_images = []
        self.show_all_frames = tk.BooleanVar(value=False)
        self.last_component = 'battle'
        self.pending_by_job = {}
        self._selection_loading = False
        self.pairs_path = self.library.project_root / '.crystal' / 'appearance_pairs.json'
        self.pairs_path.parent.mkdir(parents=True, exist_ok=True)
        self.pairs = self._load_pairs()
        self._build()
        self.refresh()

    def _build(self):
        ttk.Label(self, text='Character Appearance Library', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(
            self,
            text='Choose battle and overworld assets separately. Selections are staged automatically when you save or change jobs. Optional pairs keep favorite battle and overworld models together.',
            style='Muted.TLabel', wraplength=850,
        ).pack(anchor='w', pady=(4, 10))

        controls = ttk.Frame(self)
        controls.pack(fill='x')

        battle_row = ttk.Frame(controls)
        battle_row.pack(fill='x', pady=(0, 6))
        ttk.Label(battle_row, text='Battle model:', width=18).pack(side='left')
        self.battle_choice = tk.StringVar()
        self.battle_combo = ttk.Combobox(battle_row, textvariable=self.battle_choice, state='readonly')
        self.battle_combo.pack(side='left', fill='x', expand=True)
        self.battle_combo.bind('<<ComboboxSelected>>', lambda _e: self._selection_changed('battle'))
        self.battle_badge = ttk.Label(battle_row, text='')
        self.battle_badge.pack(side='left', padx=(8, 0))

        battle_name_row = ttk.Frame(controls)
        battle_name_row.pack(fill='x', pady=(0, 6))
        ttk.Label(battle_name_row, text='Battle nickname:', width=18).pack(side='left')
        self.battle_nickname = tk.StringVar()
        self.battle_name_entry = tk.Entry(
            battle_name_row, textvariable=self.battle_nickname,
            bg='#30343b', fg='#f2f2f2', insertbackground='#f2f2f2',
            selectbackground='#4d78cc', selectforeground='#ffffff', relief='flat',
        )
        self.battle_name_entry.pack(side='left', fill='x', expand=True, ipady=5)
        ttk.Button(battle_name_row, text='Rename Battle', command=lambda: self.rename_component('battle')).pack(side='left', padx=(8, 0))

        field_row = ttk.Frame(controls)
        field_row.pack(fill='x', pady=(0, 6))
        ttk.Label(field_row, text='Overworld model:', width=18).pack(side='left')
        self.field_choice = tk.StringVar()
        self.field_combo = ttk.Combobox(field_row, textvariable=self.field_choice, state='readonly')
        self.field_combo.pack(side='left', fill='x', expand=True)
        self.field_combo.bind('<<ComboboxSelected>>', lambda _e: self._selection_changed('field'))
        self.field_badge = ttk.Label(field_row, text='')
        self.field_badge.pack(side='left', padx=(8, 0))

        field_name_row = ttk.Frame(controls)
        field_name_row.pack(fill='x')
        ttk.Label(field_name_row, text='Map nickname:', width=18).pack(side='left')
        self.field_nickname = tk.StringVar()
        self.field_name_entry = tk.Entry(
            field_name_row, textvariable=self.field_nickname,
            bg='#30343b', fg='#f2f2f2', insertbackground='#f2f2f2',
            selectbackground='#4d78cc', selectforeground='#ffffff', relief='flat',
        )
        self.field_name_entry.pack(side='left', fill='x', expand=True, ipady=5)
        ttk.Button(field_name_row, text='Rename Overworld', command=lambda: self.rename_component('field')).pack(side='left', padx=(8, 0))

        load_pair_row = ttk.Frame(self)
        load_pair_row.pack(fill='x', pady=(10, 0))
        ttk.Label(load_pair_row, text='Saved appearance:', width=18).pack(side='left')
        self.saved_pair_choice = tk.StringVar()
        self.saved_pair_combo = ttk.Combobox(load_pair_row, textvariable=self.saved_pair_choice, state='readonly')
        self.saved_pair_combo.pack(side='left', fill='x', expand=True)
        ttk.Button(load_pair_row, text='Load Pair', command=self.load_selected_pair).pack(side='left', padx=(8, 0))
        ttk.Button(load_pair_row, text='Delete Pair…', command=self.delete_selected_pair).pack(side='left', padx=(6, 0))

        pair_row = ttk.Frame(self)
        pair_row.pack(fill='x', pady=(6, 0))
        self.pair_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(pair_row, text='Pair selected battle and overworld', variable=self.pair_enabled).pack(side='left')
        ttk.Label(pair_row, text='Pair name:').pack(side='left', padx=(12, 4))
        self.pair_name = tk.StringVar()
        self.pair_entry = tk.Entry(
            pair_row, textvariable=self.pair_name, width=28,
            bg='#30343b', fg='#f2f2f2', insertbackground='#f2f2f2',
            selectbackground='#4d78cc', selectforeground='#ffffff', relief='flat',
        )
        self.pair_entry.pack(side='left', ipady=5)
        ttk.Button(pair_row, text='Save Pair', command=self.save_pair).pack(side='left', padx=(8, 0))

        library_row = ttk.Frame(self)
        library_row.pack(fill='x', pady=(10, 0))
        ttk.Button(library_row, text='Import Model…', command=self.import_set).pack(side='left')
        ttk.Button(library_row, text='Create Recolor…', command=self.open_recolor_dialog).pack(side='left', padx=(6, 0))
        ttk.Button(library_row, text='Set Default Preview…', command=self.set_ready_image).pack(side='left', padx=(6, 0))
        ttk.Button(library_row, text='Refresh Library', command=self.refresh).pack(side='left', padx=(6, 0))

        manage_row = ttk.Frame(self)
        manage_row.pack(fill='x', pady=(6, 0))
        ttk.Button(manage_row, text='Delete Selected Battle…', command=lambda: self.delete_selected('battle')).pack(side='left')
        ttk.Button(manage_row, text='Delete Selected Overworld…', command=lambda: self.delete_selected('field')).pack(side='left', padx=(6, 0))
        ttk.Checkbutton(manage_row, text='Show all sprites', variable=self.show_all_frames, command=self._toggle_frames).pack(side='left', padx=(12, 0))

        self.preview_host = ttk.Frame(self)
        self.preview_host.pack(fill='both', expand=True, pady=12)
        self.preview = ttk.Label(self.preview_host, text='No model selected.', anchor='center')
        self.preview.pack(fill='both', expand=True)
        self.mosaic_canvas = None
        self.details = ttk.Label(self, text='', style='Muted.TLabel', wraplength=850)
        self.details.pack(anchor='w')

    def _center_child(self, window: tk.Toplevel) -> None:
        self.update_idletasks(); window.update_idletasks()
        parent = self.winfo_toplevel()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        ww, wh = window.winfo_reqwidth(), window.winfo_reqheight()
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 2)
        window.geometry(f'+{x}+{y}')

    def _palette_colors(self, item: SpriteSet | None, limit: int = 8) -> list[tuple[int, int, int]]:
        """Return the most useful visible colors from Default_00, then other frames."""
        if not item:
            return []
        paths = self.library._component_png_paths(item, 'battle') or self.library._component_png_paths(item, 'field')
        ordered = sorted(paths, key=lambda p: (p.name.lower() != 'default_00.png', p.name.lower()))
        counts: dict[tuple[int, int, int], int] = {}
        for path in ordered[:4]:
            try:
                with Image.open(path) as opened:
                    image = opened.convert('RGBA')
                    # Exact palette colors are important in pixel art; do not blur.
                    for r, g, b, a in image.getdata():
                        if a < 32:
                            continue
                        rgb = (r, g, b)
                        counts[rgb] = counts.get(rgb, 0) + 1
            except Exception:
                continue
        if not counts:
            return [(200, 40, 40)]
        # Remove near-duplicate shades only when they are extremely close. This
        # leaves red armor and yellow accents as independent slots.
        selected: list[tuple[int, int, int]] = []
        for color, _count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            if color[0] < 18 and color[1] < 18 and color[2] < 18:
                continue  # outlines are normally left intact
            if any(sum((color[i]-old[i])**2 for i in range(3)) ** .5 < 18 for old in selected):
                continue
            selected.append(color)
            if len(selected) >= limit:
                break
        return selected or [(200, 40, 40)]

    def open_recolor_dialog(self):
        current_battle = self._selected_set('battle')
        current_field = self._selected_set('field')
        if not current_battle and not current_field:
            messagebox.showinfo('Create Recolor', 'Select a battle or overworld model first.', parent=self)
            return

        dialog = tk.Toplevel(self)
        dialog.title('Palette Recolor Studio')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Palette Recolor Studio', style='Heading.TLabel').grid(row=0, column=0, columnspan=7, sticky='w')
        ttk.Label(
            frame,
            text='Choose the current battle/map selection or load a saved pair. Click a color swatch to replace it; no color codes are required.',
            style='Muted.TLabel', wraplength=720,
        ).grid(row=1, column=0, columnspan=7, sticky='w', pady=(4, 10))

        pair_names = sorted(self.pairs)
        source_options = ['Current battle + overworld selection'] + [f'Pair: {name}' for name in pair_names]
        source_var = tk.StringVar(value=source_options[0])
        ttk.Label(frame, text='Source appearance:').grid(row=2, column=0, columnspan=2, sticky='w')
        source_combo = ttk.Combobox(frame, textvariable=source_var, values=source_options, state='readonly', width=46)
        source_combo.grid(row=2, column=2, columnspan=5, sticky='ew')

        ttk.Label(frame, text='New appearance name:').grid(row=3, column=0, columnspan=2, sticky='w', pady=(8, 0))
        name_var = tk.StringVar(value=f'{(current_battle or current_field).name} Recolor')
        name_entry = tk.Entry(
            frame, textvariable=name_var, width=46, bg='#30343b', fg='#f2f2f2',
            insertbackground='#f2f2f2', selectbackground='#4d78cc', selectforeground='#fff', relief='flat',
        )
        name_entry.grid(row=3, column=2, columnspan=5, sticky='ew', ipady=5, pady=(8, 0))

        ttk.Label(frame, text='Use').grid(row=4, column=0, sticky='w', pady=(12, 2))
        ttk.Label(frame, text='Original').grid(row=4, column=1, columnspan=2, sticky='w', pady=(12, 2))
        ttk.Label(frame, text='New color').grid(row=4, column=3, columnspan=2, sticky='w', pady=(12, 2))

        enabled = [tk.BooleanVar(value=False) for _ in range(8)]
        sources = [[0, 0, 0] for _ in range(8)]
        targets = [[0, 0, 0] for _ in range(8)]
        source_swatches = []
        target_swatches = []
        slot_labels = []
        history = []
        selected = {'battle': current_battle, 'field': current_field}
        auto_base = {'targets': None}
        preview_ref = {'image': None}

        def swatch_color(rgb):
            return '#%02X%02X%02X' % tuple(int(v) for v in rgb)

        def paint_swatch(canvas, rgb):
            canvas.delete('all')
            canvas.create_rectangle(1, 1, 43, 25, fill=swatch_color(rgb), outline='#aab0b8')

        def choose(index, which):
            # Manual target edits leave automatic-slider mode so the chosen swatch
            # remains exactly as selected. Source corrections also refresh the
            # automatic baseline.
            if which == 'target' and auto_enabled.get():
                auto_enabled.set(False)
            current = sources[index] if which == 'source' else targets[index]
            result = colorchooser.askcolor(color=swatch_color(current), parent=dialog, title='Choose sprite color')
            if not result or not result[0]:
                return
            history.append(([list(v) for v in sources], [list(v) for v in targets], [v.get() for v in enabled]))
            current[:] = [int(v) for v in result[0]]
            paint_swatch(source_swatches[index] if which == 'source' else target_swatches[index], current)
            refresh_preview()

        for i in range(8):
            row = 5 + i
            ttk.Checkbutton(frame, variable=enabled[i], command=lambda: refresh_preview()).grid(row=row, column=0, sticky='w')
            slot = ttk.Label(frame, text=f'Color {i + 1}', width=9)
            slot.grid(row=row, column=1, sticky='w', pady=3)
            slot_labels.append(slot)
            src_canvas = tk.Canvas(frame, width=46, height=28, bg='#24272d', highlightthickness=0, cursor='hand2')
            src_canvas.grid(row=row, column=2, sticky='w', padx=(0, 14), pady=2)
            src_canvas.bind('<Button-1>', lambda _e, i=i: choose(i, 'source'))
            source_swatches.append(src_canvas)
            dst_canvas = tk.Canvas(frame, width=46, height=28, bg='#24272d', highlightthickness=0, cursor='hand2')
            dst_canvas.grid(row=row, column=3, sticky='w', pady=2)
            dst_canvas.bind('<Button-1>', lambda _e, i=i: choose(i, 'target'))
            target_swatches.append(dst_canvas)
            ttk.Button(frame, text='Choose…', width=9, command=lambda i=i: choose(i, 'target')).grid(row=row, column=4, sticky='w', padx=(6, 12))

        preview_label = ttk.Label(frame, text='Preview', anchor='center')
        preview_label.grid(row=5, column=5, columnspan=2, rowspan=8, padx=(16, 0), sticky='nsew')
        tolerance = tk.IntVar(value=42)

        def current_mappings():
            return [(tuple(sources[i]), tuple(targets[i])) for i in range(8) if enabled[i].get()]

        def preview_source():
            battle = selected['battle']
            field = selected['field']
            paths = self.library._component_png_paths(battle, 'battle') if battle else []
            if not paths and field:
                paths = self.library._component_png_paths(field, 'field')
            return next((p for p in paths if p.name.lower() == 'default_00.png'), paths[0] if paths else None)

        def refresh_preview(*_):
            source_preview = preview_source()
            if not source_preview:
                preview_label.configure(text='No extracted PNG preview', image='')
                return
            try:
                with tempfile.TemporaryDirectory() as td:
                    out = Path(td) / 'preview.png'
                    self.library._recolor_image_multi(source_preview, out, current_mappings(), tolerance.get())
                    with Image.open(out) as opened:
                        pic = opened.convert('RGBA')
                        scale_factor = max(1, min(8, 176 // max(pic.width, pic.height)))
                        pic = pic.resize((pic.width * scale_factor, pic.height * scale_factor), Image.Resampling.NEAREST)
                    photo = ImageTk.PhotoImage(pic)
                    preview_ref['image'] = photo
                    preview_label.configure(image=photo, text='')
            except Exception as exc:
                preview_label.configure(text=f'Preview unavailable\n{exc}', image='')

        def load_palette(reset_name=True):
            battle = selected['battle']
            field = selected['field']
            palette = self._palette_colors(battle or field, 8)
            for i in range(8):
                active = i < len(palette)
                enabled[i].set(active)
                color = palette[i] if active else (0, 0, 0)
                sources[i][:] = list(color)
                targets[i][:] = list(color)
                slot_labels[i].configure(text=f'Color {i + 1}')
                paint_swatch(source_swatches[i], sources[i])
                paint_swatch(target_swatches[i], targets[i])
            if reset_name:
                base = source_var.get().removeprefix('Pair: ') if source_var.get().startswith('Pair: ') else (battle or field).name
                name_var.set(f'{base} Recolor')
            history.clear()
            auto_base['targets'] = [list(v) for v in targets]
            hue_shift.set(0)
            saturation_scale.set(100)
            brightness_scale.set(100)
            refresh_preview()

        def source_changed(_event=None):
            choice = source_var.get()
            if choice.startswith('Pair: '):
                pair_name = choice[6:]
                pair = self.pairs.get(pair_name, {})
                selected['battle'] = next((item for item in self.items if item.name == pair.get('battle', '')), None)
                selected['field'] = next((item for item in self.items if item.name == pair.get('field', '')), None)
            else:
                selected['battle'] = current_battle
                selected['field'] = current_field
            include_battle.set(bool(selected['battle'] and selected['battle'].has_battle))
            include_field.set(bool(selected['field'] and selected['field'].has_field))
            load_palette(True)

        source_combo.bind('<<ComboboxSelected>>', source_changed)

        ttk.Label(frame, text='Match range:').grid(row=13, column=0, columnspan=2, sticky='w', pady=(10, 0))
        scale = tk.Scale(
            frame, from_=8, to=100, orient='horizontal', variable=tolerance, length=260,
            showvalue=True, highlightthickness=0, command=refresh_preview,
        )
        scale.grid(row=13, column=2, columnspan=3, sticky='ew', pady=(10, 0))

        # Automatic palette transformation. It operates only on enabled swatches,
        # preserving colors the artist has deliberately unchecked. Sliders update
        # the live preview immediately and can be combined with manual swatches.
        auto_enabled = tk.BooleanVar(value=False)
        hue_shift = tk.IntVar(value=0)
        saturation_scale = tk.IntVar(value=100)
        brightness_scale = tk.IntVar(value=100)

        def apply_auto(*_):
            if not auto_enabled.get():
                return
            import colorsys
            base = auto_base.get('targets') or [list(v) for v in targets]
            hue_delta = hue_shift.get() / 360.0
            sat_mult = saturation_scale.get() / 100.0
            val_mult = brightness_scale.get() / 100.0
            for i in range(8):
                if not enabled[i].get():
                    continue
                r, g, b = base[i]
                h, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                h = (h + hue_delta) % 1.0
                sat = max(0.0, min(1.0, sat * sat_mult))
                val = max(0.02, min(1.0, val * val_mult))
                rr, gg, bb = colorsys.hsv_to_rgb(h, sat, val)
                targets[i][:] = [round(rr * 255), round(gg * 255), round(bb * 255)]
                paint_swatch(target_swatches[i], targets[i])
            refresh_preview()

        def toggle_auto():
            if auto_enabled.get():
                history.append(([list(v) for v in sources], [list(v) for v in targets], [v.get() for v in enabled]))
                # Use the palette currently visible in the preview as the slider base.
                # This preserves a randomized/manual palette exactly when Auto is enabled.
                auto_base['targets'] = [list(v) for v in targets]
                hue_shift.set(0)
                saturation_scale.set(100)
                brightness_scale.set(100)
                refresh_preview()

        auto_row = ttk.Frame(frame)
        auto_row.grid(row=14, column=0, columnspan=7, sticky='ew', pady=(10, 0))
        ttk.Checkbutton(auto_row, text='Auto recolor enabled colors', variable=auto_enabled, command=toggle_auto).pack(side='left')
        ttk.Label(auto_row, text='Drag the sliders to preview coordinated variants instantly.', style='Muted.TLabel').pack(side='left', padx=(10, 0))

        slider_row = ttk.Frame(frame)
        slider_row.grid(row=15, column=0, columnspan=7, sticky='ew', pady=(4, 0))
        ttk.Label(slider_row, text='Hue').pack(side='left')
        tk.Scale(slider_row, from_=-180, to=180, orient='horizontal', variable=hue_shift, length=150,
                 showvalue=True, highlightthickness=0, command=apply_auto).pack(side='left', padx=(4, 12))
        ttk.Label(slider_row, text='Saturation').pack(side='left')
        tk.Scale(slider_row, from_=25, to=200, orient='horizontal', variable=saturation_scale, length=130,
                 showvalue=True, highlightthickness=0, command=apply_auto).pack(side='left', padx=(4, 12))
        ttk.Label(slider_row, text='Brightness').pack(side='left')
        tk.Scale(slider_row, from_=25, to=175, orient='horizontal', variable=brightness_scale, length=130,
                 showvalue=True, highlightthickness=0, command=apply_auto).pack(side='left', padx=(4, 0))

        # Disgaea-inspired coordinated palette randomizer. Checked rows are randomized;
        # unchecked rows act as locks. One seed reproduces the same palette on battle and map sprites.
        random_style = tk.StringVar(value='Balanced')
        random_seed = tk.StringVar(value='')
        random_history = []

        def random_theme_color(rng, style, source, family_hue, index):
            # Disgaea-style palette families use a coordinated primary, secondary,
            # and accent hue instead of collapsing every swatch onto one hue.
            h0, s0, v0 = colorsys.rgb_to_hsv(*(c / 255 for c in source))
            families = {
                'Balanced': ((family_hue, (family_hue + .08) % 1.0, (family_hue + .50) % 1.0), .62, .88),
                'Dark Knight': ((.72, .78, .14), .68, .55),
                'Holy': ((.13, .58, .09), .40, 1.0),
                'Fire': ((.00, .055, .13), .88, .98),
                'Ice': ((.56, .61, .51), .66, 1.0),
                'Lightning': ((.15, .62, .78), .84, 1.0),
                'Nature': ((.31, .24, .10), .66, .82),
                'Poison': ((.78, .36, .90), .76, .84),
                'Shadow': ((.74, .62, .92), .66, .50),
                'Royal': ((.72, .04, .13), .70, .88),
                'Metallic': ((.58, .62, .13), .20, .94),
                'Wild': ((rng.random(), rng.random(), rng.random()), .90, .98),
            }
            hues, sat_base, val_base = families.get(style, families['Balanced'])
            # Preserve neutral/skin-like rows more gently; otherwise rotate through
            # the theme anchors so trim and accents remain visibly distinct.
            if s0 < .14:
                hue = hues[0]
                sat = min(.22, sat_base * .35)
            else:
                hue = hues[index % len(hues)]
                sat = max(.08, min(1.0, sat_base * rng.uniform(.88, 1.10)))
            hue = (hue + rng.uniform(-.018, .018)) % 1.0
            # Maintain the original light/shadow ladder for consistent pixel art shading.
            value = max(.055, min(1.0, val_base * (.48 + .62 * max(.10, v0))))
            return [round(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, value)]

        def _hue_distance(a, b):
            d = abs(a - b) % 1.0
            return min(d, 1.0 - d)

        def _shade_groups(indices):
            # Group neighboring source shades by hue/material before assigning theme colors.
            # This keeps fur, armor, cloth, etc. as smooth ramps rather than spotted hues.
            groups = []
            for i in indices:
                h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in sources[i]))
                neutral = sat < .16
                placed = False
                for group in groups:
                    gh, gsat, _ = group['center']
                    same_kind = neutral == group['neutral']
                    if same_kind and (neutral or (_hue_distance(h, gh) <= .075 and abs(sat - gsat) <= .34)):
                        group['items'].append((i, h, sat, val))
                        vals = group['items']
                        group['center'] = (
                            sum(x[1] for x in vals) / len(vals),
                            sum(x[2] for x in vals) / len(vals),
                            sum(x[3] for x in vals) / len(vals),
                        )
                        placed = True
                        break
                if not placed:
                    groups.append({'neutral': neutral, 'center': (h, sat, val), 'items': [(i, h, sat, val)]})
            for group in groups:
                group['items'].sort(key=lambda x: x[3])
            groups.sort(key=lambda g: g['center'][2])
            return groups

        def randomize_palette(again=False):
            random_history.append(([list(v) for v in targets], [v.get() for v in enabled]))
            raw = random_seed.get().strip()
            if again or not raw:
                raw = str(random.SystemRandom().randrange(100000, 999999999))
                random_seed.set(raw)
            try:
                seed = int(raw)
            except ValueError:
                seed = sum((i + 1) * ord(ch) for i, ch in enumerate(raw))
            rng = random.Random(seed)
            family_hue = rng.random()
            indices = [i for i in range(8) if enabled[i].get()]
            groups = _shade_groups(indices)
            for group_index, group in enumerate(groups):
                # Every shade in one material group shares the same theme anchor.
                anchor_index = group_index
                for i, _h, _sat, _val in group['items']:
                    targets[i][:] = random_theme_color(
                        rng, random_style.get(), sources[i], family_hue, anchor_index
                    )
                    paint_swatch(target_swatches[i], targets[i])
            auto_enabled.set(False)
            auto_base['targets'] = [list(v) for v in targets]
            hue_shift.set(0)
            saturation_scale.set(100)
            brightness_scale.set(100)
            refresh_preview()

        def undo_random():
            if not random_history:
                return
            old_targets, old_enabled = random_history.pop()
            for i in range(8):
                targets[i][:] = old_targets[i]
                enabled[i].set(old_enabled[i])
                paint_swatch(target_swatches[i], targets[i])
            refresh_preview()

        random_box = ttk.LabelFrame(frame, text='Disgaea-style Appearance Randomizer', padding=8)
        random_box.grid(row=16, column=0, columnspan=7, sticky='ew', pady=(10, 0))
        ttk.Label(random_box, text='Style').grid(row=0, column=0, sticky='w')
        ttk.Combobox(random_box, textvariable=random_style, state='readonly', width=18,
                     values=('Balanced','Dark Knight','Holy','Fire','Ice','Lightning','Nature','Poison','Shadow','Royal','Metallic','Wild')).grid(row=0,column=1,sticky='ew',padx=6)
        ttk.Label(random_box, text='Seed').grid(row=1,column=0,sticky='w',pady=(5,0))
        ttk.Entry(random_box, textvariable=random_seed, width=18).grid(row=1,column=1,sticky='ew',padx=6,pady=(5,0))
        ttk.Button(random_box, text='Randomize', command=randomize_palette).grid(row=0,column=2,padx=(4,0))
        ttk.Button(random_box, text='Again', command=lambda: randomize_palette(True)).grid(row=1,column=2,padx=(4,0),pady=(5,0))
        ttk.Button(random_box, text='Undo Random', command=undo_random).grid(row=2,column=1,columnspan=2,sticky='e',pady=(6,0))
        ttk.Label(random_box, text='Unchecked colors are locked. The seed reproduces the same coordinated result for battle and overworld.', style='Muted.TLabel', wraplength=650).grid(row=3,column=0,columnspan=3,sticky='w',pady=(6,0))
        random_box.columnconfigure(1, weight=1)

        include_battle = tk.BooleanVar(value=bool(current_battle and current_battle.has_battle))
        include_field = tk.BooleanVar(value=bool(current_field and current_field.has_field))
        ttk.Checkbutton(frame, text='Create battle recolor', variable=include_battle).grid(row=17, column=0, columnspan=3, sticky='w', pady=(8, 0))
        ttk.Checkbutton(frame, text='Create matching overworld recolor', variable=include_field).grid(row=17, column=3, columnspan=4, sticky='w', pady=(8, 0))

        def undo():
            if not history:
                return
            auto_enabled.set(False)
            old_sources, old_targets, old_enabled = history.pop()
            for i in range(8):
                sources[i][:] = old_sources[i]
                targets[i][:] = old_targets[i]
                enabled[i].set(old_enabled[i])
                paint_swatch(source_swatches[i], sources[i])
                paint_swatch(target_swatches[i], targets[i])
            refresh_preview()

        def reset():
            auto_enabled.set(False)
            hue_shift.set(0)
            saturation_scale.set(100)
            brightness_scale.set(100)
            history.append(([list(v) for v in sources], [list(v) for v in targets], [v.get() for v in enabled]))
            for i in range(8):
                targets[i][:] = sources[i]
                paint_swatch(target_swatches[i], targets[i])
            refresh_preview()

        buttons = ttk.Frame(frame)
        buttons.grid(row=18, column=0, columnspan=7, sticky='e', pady=(14, 0))
        ttk.Button(buttons, text='Undo', command=undo).pack(side='left')
        ttk.Button(buttons, text='Reset Colors', command=reset).pack(side='left', padx=(6, 16))

        def create():
            battle = selected['battle'] if include_battle.get() else None
            field = selected['field'] if include_field.get() else None
            try:
                result = self.library.create_recolor(battle, field, name_var.get().strip(), current_mappings(), tolerance.get())
                if result.has_battle and result.has_field:
                    pair_name = result.name
                    self.pairs[pair_name] = {'battle': result.name, 'field': result.name}
                    self._save_pairs()
                dialog.destroy()
                self.refresh()
                if result.has_battle:
                    self.battle_choice.set(result.name)
                if result.has_field:
                    self.field_choice.set(result.name)
                self._selection_changed('battle' if result.has_battle else 'field')
                pair_note = ' and saved it as a paired appearance' if result.has_battle and result.has_field else ''
                self.on_status('PASS', f'Created recolored appearance “{result.name}”{pair_note}.')
            except Exception as exc:
                messagebox.showerror('Could not create recolor', str(exc), parent=dialog)

        ttk.Button(buttons, text='Save Recolor As…', command=create).pack(side='left')
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='left', padx=(8, 0))
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        self._center_child(dialog)
        name_entry.focus_set()
        load_palette(False)
    def _load_pairs(self):
        try:
            data = json.loads(self.pairs_path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_pairs(self):
        self.pairs_path.write_text(json.dumps(self.pairs, indent=2), encoding='utf-8')

    def _refresh_pair_choices(self):
        names = sorted(self.pairs, key=str.lower)
        if hasattr(self, 'saved_pair_combo'):
            self.saved_pair_combo['values'] = tuple(names)
            if self.saved_pair_choice.get() not in names:
                self.saved_pair_choice.set(names[0] if names else '')

    def load_selected_pair(self):
        name = self.saved_pair_choice.get().strip()
        pair = self.pairs.get(name)
        if not pair:
            return
        battle = pair.get('battle', '')
        field = pair.get('field', '')
        missing = []
        if battle not in self.battle_combo['values']:
            missing.append(f'battle model “{battle}”')
        if field not in self.field_combo['values']:
            missing.append(f'overworld model “{field}”')
        if missing:
            messagebox.showerror('Could not load pair', 'The pair references a missing ' + ' and '.join(missing) + '.', parent=self)
            return
        self._selection_loading = True
        self.battle_choice.set(battle)
        self.field_choice.set(field)
        self._selection_loading = False
        self.battle_nickname.set(battle)
        self.field_nickname.set(field)
        self.pair_enabled.set(True)
        self.pair_name.set(name)
        if self.job_id:
            self.pending_by_job.setdefault(self.job_id, {}).update({'battle': battle, 'field': field})
            self.on_dirty(True)
        self.last_component = 'battle'
        self._show('battle')
        self.on_status('PASS', f'Loaded paired appearance “{name}”.')

    def delete_selected_pair(self):
        name = self.saved_pair_choice.get().strip()
        if not name or name not in self.pairs:
            return
        if not messagebox.askyesno('Delete Pair', f'Delete the saved pairing “{name}”?\n\nThe battle and overworld sprite models will remain in the library.', parent=self):
            return
        del self.pairs[name]
        self._save_pairs()
        self.pair_name.set('')
        self.pair_enabled.set(False)
        self._refresh_pair_choices()
        self.on_status('PASS', f'Deleted paired appearance “{name}”.')

    def save_pair(self):
        battle = self._selected_set('battle')
        field = self._selected_set('field')
        if not battle or not field:
            messagebox.showinfo('Pair Appearance', 'Select both a battle and an overworld model first.', parent=self)
            return
        name = self.pair_name.get().strip() or f'{battle.name} + {field.name}'
        self.pairs[name] = {'battle': battle.name, 'field': field.name}
        self._save_pairs()
        self.pair_enabled.set(True)
        self.pair_name.set(name)
        self.saved_pair_choice.set(name)
        self._refresh_pair_choices()
        self.saved_pair_choice.set(name)
        self.on_status('PASS', f'Saved paired appearance “{name}”.')

    def _selection_changed(self, component):
        if self._selection_loading:
            return
        self.last_component = component
        item = self._selected_set(component)
        if component == 'battle':
            self.battle_nickname.set(item.name if item else '')
        else:
            self.field_nickname.set(item.name if item else '')
        if self.job_id:
            pending = self.pending_by_job.setdefault(self.job_id, {})
            pending[component] = item.name if item else ''
            self.on_dirty(True)
        if self.pair_enabled.get():
            for pair_name, pair in self.pairs.items():
                if component == 'battle' and pair.get('battle') == self.battle_choice.get() and pair.get('field') in self.field_combo['values']:
                    self._selection_loading = True; self.field_choice.set(pair['field']); self._selection_loading = False
                    self.pending_by_job.setdefault(self.job_id, {})['field'] = pair['field']
                    self.pair_name.set(pair_name)
                    break
                if component == 'field' and pair.get('field') == self.field_choice.get() and pair.get('battle') in self.battle_combo['values']:
                    self._selection_loading = True; self.battle_choice.set(pair['battle']); self._selection_loading = False
                    self.pending_by_job.setdefault(self.job_id, {})['battle'] = pair['battle']
                    self.pair_name.set(pair_name)
                    break
        self._show(component)

    def rename_component(self, component):
        item = self._selected_set(component)
        if not item:
            return
        value = (self.battle_nickname.get() if component == 'battle' else self.field_nickname.get()).strip()
        if not value or value == item.name:
            return
        try:
            renamed = self.library.rename(item, value)
            # update pairs referencing the old name
            for pair in self.pairs.values():
                if pair.get(component) == item.name:
                    pair[component] = renamed.name
            self._save_pairs()
            self.refresh()
            if component == 'battle':
                self.battle_choice.set(renamed.name); self.battle_nickname.set(renamed.name)
            else:
                self.field_choice.set(renamed.name); self.field_nickname.set(renamed.name)
            self._show(component)
        except Exception as exc:
            messagebox.showerror('Could not rename model', str(exc), parent=self)

    def commit_pending(self, job_id=None):
        target = int(job_id or self.job_id or 0)
        if not target:
            return []
        pending = self.pending_by_job.get(target, {})
        written = []
        for component in ('battle', 'field'):
            name = pending.get(component)
            if not name:
                continue
            item = next((entry for entry in self.items if entry.name == name), None)
            if not item:
                continue
            written.extend(self.library.apply(item, target, component))
            label = 'battle' if component == 'battle' else 'overworld'
            self.on_status('PASS', f'Staged {label} model “{item.name}” for Job {target}.')
        self.pending_by_job.pop(target, None)
        return written

    def set_job(self, job_id, job_name):
        previous = self.job_id
        if previous and previous != int(job_id or 0):
            self.commit_pending(previous)
        try:
            self.job_id = int(job_id)
        except Exception:
            self.job_id = None
        self.job_name = job_name
        self._selection_loading = True
        self._select_active_for_job()
        pending = self.pending_by_job.get(self.job_id, {})
        if pending.get('battle'):
            self.battle_choice.set(pending['battle'])
        if pending.get('field'):
            self.field_choice.set(pending['field'])
        self._selection_loading = False
        battle = self._selected_set('battle'); field = self._selected_set('field')
        self.battle_nickname.set(battle.name if battle else '')
        self.field_nickname.set(field.name if field else '')
        self._show('battle')


    def _select_active_for_job(self):
        """Prefer the current working/live appearance for the selected job.

        Only fall back to the protected MagiciteExport default when no current
        working sprite group exists for that component.
        """
        if not self.job_id:
            return
        current = [i for i in self.items if i.source == 'Current working/imported mod' and i.source_job_id == self.job_id]
        default = [i for i in self.items if i.source == 'MagiciteExport default' and i.source_job_id == self.job_id]
        battle = next((i for i in current if i.has_battle), None) or next((i for i in default if i.has_battle), None)
        field = next((i for i in current if i.has_field), None) or next((i for i in default if i.has_field), None)
        if battle:
            self.battle_choice.set(battle.name)
        if field:
            self.field_choice.set(field.name)

    def _toggle_frames(self):
        self._show(self.last_component)

    def _clear_preview_host(self):
        for child in self.preview_host.winfo_children():
            child.destroy()
        self.mosaic_images = []

    def _sprite_files_for_mosaic(self, item, component):
        # Verification must show the selected LIBRARY MODEL exactly as imported.
        # Earlier builds silently substituted the currently staged job overlay,
        # making a correct import look wrong (or vice versa).
        rels = item.battle_files if component == 'battle' else item.field_files
        if item.kind == 'bundle':
            base = item.root / 'Extracted' / ('Battle' if component == 'battle' else 'Field')
        else:
            base = item.root / ('Battle' if component == 'battle' else 'Field')
        files = [base / Path(rel).name for rel in rels]
        return [p for p in files if p.is_file() and _visible_png(p)]

    @staticmethod
    def _normalize_frame_name(name: str) -> str:
        value = Path(str(name)).stem
        return value[:-7] if value.lower().endswith("_sprite") else value

    def _field_frame_rects(self, item) -> dict[str, tuple[int, int, int, int]]:
        """Return logical overworld frames from the model's own engine map.

        FF1PR atlases use 16x16 images on a padded 20-pixel grid, so visually
        slicing every 16 pixels produces broken fragments. Bundle Sprite.m_Rect
        is not the packed atlas rectangle in these Unity 2019 bundles; the
        matching Magicite .spritedata map is the reliable source of frame names
        and padded coordinates.
        """
        rects: dict[str, tuple[int, int, int, int]] = {}
        try:
            manifest = json.loads(self.library._manifest(item.root).read_text(encoding='utf-8'))
        except Exception:
            manifest = {}
        engine_rel = manifest.get('engineField')
        roots = []
        if engine_rel and (item.root / engine_rel).is_dir():
            roots.append(item.root / engine_rel)
        source_job = int(manifest.get('sourceJobId') or item.source_job_id or 0)
        if source_job:
            source_group = _find_group(self.library.export_root, f'mo_ff1_p{source_job:03d}_c00')
            if source_group:
                roots.append(source_group)
        for root in roots:
            for data_file in root.rglob('*.spritedata'):
                rect = self.library._read_sprite_rect(data_file)
                if rect:
                    rects[self._normalize_frame_name(data_file.stem)] = rect
            if rects:
                break
        return rects

    def _show_mosaic(self, item, component):
        self._clear_preview_host()
        files = self._sprite_files_for_mosaic(item, component)
        if not files:
            if item.kind == 'bundle':
                records = [r for r in item.bundle_files if r.get('kind') == component]
                names = '\n'.join(f"• {r.get('file', 'Unknown bundle')}" for r in records)
                message = (
                    f'Compiled {"battle" if component == "battle" else "overworld"} bundle included.\n\n'
                    f'{names or "No bundle file is saved for this component."}\n\n'
                    'Studio opened the UnityFS bundle, but no supported Texture2D payload was found. '
                    'The original bundle remains saved and deployable.'
                )
            else:
                message = 'No visible PNG frames are available for this model/component.'
            ttk.Label(self.preview_host, text=message, anchor='center', justify='center', wraplength=720).pack(fill='x', pady=24)
            return
        style = ttk.Style(self)
        panel_bg = style.lookup('TFrame', 'background') or self.winfo_toplevel().cget('background')
        canvas = tk.Canvas(self.preview_host, highlightthickness=0, borderwidth=0, background=panel_bg)
        scroll = ttk.Scrollbar(self.preview_host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        frame = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=frame, anchor='nw')
        def sync_scrollregion(_event=None):
            bbox = canvas.bbox('all')
            if bbox:
                canvas.configure(scrollregion=bbox)
        frame.bind('<Configure>', sync_scrollregion)
        canvas.bind('<Configure>', lambda e: (canvas.itemconfigure(window, width=e.width), sync_scrollregion()))
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        display_items = []
        for path in files:
            with Image.open(path) as opened:
                image = opened.convert('RGBA')
            if component == 'field' and (image.width > 32 or image.height > 32):
                rects = self._field_frame_rects(item)
                if rects:
                    preferred = [
                        'Default_00', 'Default_01', 'WalkB_00', 'WalkB_01',
                        'WalkL_00', 'WalkL_01', 'LookDown_00', 'Down_00',
                        'RightHandUp_00', 'RightHandUp_01',
                    ]
                    ordered = [n for n in preferred if n in rects] + sorted(n for n in rects if n not in preferred)
                    for name in ordered:
                        x, y, w, h = rects[name]
                        box = (x, image.height - y - h, x + w, image.height - y)
                        cell = image.crop(box)
                        if cell.getchannel('A').getbbox() is None:
                            continue
                        display_items.append((f'{name}.png', cell))
                else:
                    display_items.append((path.name, image))
            else:
                display_items.append((path.name, image))

        columns = 5
        for index, (label, image) in enumerate(display_items):
            tile = ttk.Frame(frame, padding=6)
            tile.grid(row=index // columns, column=index % columns, sticky='nsew', padx=4, pady=4)
            ttk.Label(tile, text=label, anchor='center', wraplength=145).pack(fill='x', pady=(0, 4))
            target = 96
            scale = max(1, min(8, target // max(1, max(image.width, image.height))))
            image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image)
            self.mosaic_images.append(photo)
            ttk.Label(tile, image=photo, anchor='center').pack(fill='both', expand=True)
        for col in range(columns):
            frame.columnconfigure(col, weight=1)

    def refresh(self):
        self.library.sync_defaults()
        self.library.sync_current_imports()
        self.items = self.library.list_sets()
        battle = [item.name for item in self.items if item.has_battle]
        field = [item.name for item in self.items if item.has_field]
        self.battle_combo['values'] = tuple(battle)
        self.field_combo['values'] = tuple(field)
        if self.battle_choice.get() not in battle:
            self.battle_choice.set(battle[0] if battle else '')
        if self.field_choice.get() not in field:
            self.field_choice.set(field[0] if field else '')
        self._select_active_for_job()
        self._refresh_pair_choices()
        self._show(self.last_component)

    def _selected_set(self, component='battle'):
        name = self.battle_choice.get() if component == 'battle' else self.field_choice.get()
        return next((item for item in self.items if item.name == name), None)

    def _show(self, component='battle'):
        self.last_component = component
        item = self._selected_set(component)
        if not item:
            self._clear_preview_host()
            self.preview = ttk.Label(self.preview_host, text='No saved character models are available.', anchor='center')
            self.preview.pack(fill='both', expand=True)
            self.details.configure(text='')
            self.preview_image = None
            return
        if self.show_all_frames.get():
            self._show_mosaic(item, component)
            self.preview_image = None
        else:
            self._clear_preview_host()
            self.preview = ttk.Label(self.preview_host, text='', anchor='center')
            self.preview.pack(fill='both', expand=True)
            # Battle models use the neutral Default_00 frame. Overworld models
            # use the exact standing rectangle defined by Default_00.spritedata.
            if component == 'field':
                preview = self.library.ensure_field_default_preview(item)
            else:
                component_root = item.root / ('Extracted/Battle' if item.kind == 'bundle' else 'Battle')
                default_preview = component_root / 'Default_00.png'
                preview = default_preview if default_preview.is_file() else (item.root / item.ready_preview if item.ready_preview else None)
            if preview and preview.exists():
                try:
                    with Image.open(preview) as image:
                        image = image.convert('RGBA')
                        scale = max(1, min(8, 256 // max(image.width, image.height)))
                        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
                        self.preview_image = ImageTk.PhotoImage(image)
                    self.preview.configure(image=self.preview_image, text='')
                except Exception as exc:
                    self.preview.configure(image='', text=f'Ready preview failed: {exc}')
            else:
                self.preview.configure(
                    image='',
                    text=(
                        'No Default_00 overworld preview could be built from this model.'
                        if component == 'field' else
                        'No default preview is attached to this model.\nUse “Set Default Preview…” to select a representative PNG.'
                    ),
                )
                self.preview_image = None
        target = f'{self.job_name} (Job {self.job_id})' if self.job_id else 'No job selected'
        model_type = 'Editable PNG model' if item.kind == 'png' else ('Compiled battle bundle asset' if item.has_battle else 'Compiled overworld bundle asset')
        compatible = 'Any job' if item.kind in {'png', 'bundle'} else ', '.join(str(v) for v in item.compatible_jobs)
        battle_status = 'Included' if item.has_battle else 'Not included'
        field_status = 'Included' if item.has_field else 'Not included'
        self.battle_badge.configure(text='Battle ✓' if item.has_battle else 'Battle —')
        self.field_badge.configure(text='Overworld ✓' if item.has_field else 'Overworld —')
        original_jobs = (
            ', '.join(str(v) for v in item.compatible_jobs)
            if item.kind == 'bundle'
            else 'Portable PNG'
        )
        self.details.configure(
            text=(
                f'Name: {item.name}\nType: {model_type}\nSource: {item.source}\n'
                f'Battle sprite set: {battle_status}\nOverworld sprite set: {field_status}\n'
                f'Original bundle job IDs: {original_jobs}\n'
                f'Assignable jobs: {compatible}\nTarget: {target}'
            )
        )

    def import_set(self):
        value = filedialog.askopenfilename(
            title='Import character-model ZIP',
            filetypes=[('ZIP archive', '*.zip'), ('All files', '*.*')], parent=self,
        )
        if not value:
            value = filedialog.askdirectory(title='Or select an extracted model folder', parent=self)
            if not value:
                return
        try:
            items = self.library.import_source(Path(value))
            self.on_status('PASS', f'Saved {len(items)} reusable character model(s).')
            self.refresh()
            if items:
                if items[0].has_battle:
                    self.battle_choice.set(items[0].name)
                    self._show('battle')
                elif items[0].has_field:
                    self.field_choice.set(items[0].name)
                    self._show('field')
            messagebox.showinfo(
                'Character models imported',
                f'Imported and separated {len(items)} appearance asset(s):\n\n' + '\n'.join(
                    f'• {item.name}  [Battle: {"Yes" if item.has_battle else "No"}; Overworld: {"Yes" if item.has_field else "No"}]'
                    for item in items
                ), parent=self,
            )
        except Exception as exc:
            messagebox.showerror('Model rejected', str(exc), parent=self)
            self.on_status('ERROR', f'Model import failed: {exc}')

    def rename_selected(self):
        item = self._selected_set('battle') or self._selected_set('field')
        if not item:
            return
        dialog = tk.Toplevel(self)
        dialog.title('Rename Character Model')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        ttk.Label(dialog, text='Model name:').pack(anchor='w', padx=12, pady=(12, 4))
        value = tk.StringVar(value=item.name)
        entry = ttk.Entry(dialog, textvariable=value, width=48)
        entry.pack(fill='x', padx=12)
        entry.select_range(0, 'end')
        entry.focus_set()

        def save():
            try:
                renamed = self.library.rename(item, value.get())
                dialog.destroy()
                self.refresh()
                if renamed.has_battle:
                    self.battle_choice.set(renamed.name)
                if renamed.has_field:
                    self.field_choice.set(renamed.name)
                self._show('battle' if renamed.has_battle else 'field')
            except Exception as exc:
                messagebox.showerror('Could not rename model', str(exc), parent=dialog)

        buttons = ttk.Frame(dialog)
        buttons.pack(fill='x', padx=12, pady=12)
        ttk.Button(buttons, text='Save', command=save).pack(side='right')
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right', padx=(0, 6))

    def delete_selected(self, component='battle'):
        """Delete only the model selected in the requested component selector."""
        component = 'field' if component == 'field' else 'battle'
        item = self._selected_set(component)
        label = 'overworld' if component == 'field' else 'battle'
        if not item:
            messagebox.showinfo('Delete Character Model', f'No {label} model is selected.', parent=self)
            return
        if item.source == 'MagiciteExport default' or item.root.name.startswith('default-p'):
            messagebox.showinfo(
                'Default model protected',
                f'The original {label} model is a read-only fallback and cannot be deleted. '
                'Imported and current-working models can be removed.',
                parent=self,
            )
            return
        if not messagebox.askyesno(
            f'Delete {label.title()} Model',
            f'Delete “{item.name}” from the {label} library?\n\n'
            'This removes only the saved library copy. It does not alter the game, backups, '
            'or files already staged for deployment.',
            parent=self,
        ):
            return
        try:
            deleted_name = item.name
            self.library.delete(item)
            if component == 'battle' and self.battle_choice.get() == deleted_name:
                self.battle_choice.set('')
            if component == 'field' and self.field_choice.get() == deleted_name:
                self.field_choice.set('')
            self.refresh()
            self.last_component = component
            self._show(component)
            self.on_status('PASS', f'Deleted {label} model “{deleted_name}” from the library.')
        except Exception as exc:
            messagebox.showerror('Could not delete model', str(exc), parent=self)

    def set_ready_image(self):
        item = self._selected_set('battle') or self._selected_set('field')
        if not item:
            return
        value = filedialog.askopenfilename(
            title='Select extracted Ready image', filetypes=[('PNG image', '*.png')], parent=self,
        )
        if not value:
            return
        try:
            updated = self.library.set_ready_preview(item, Path(value))
            self.refresh()
            if updated.has_battle:
                self.battle_choice.set(updated.name)
                self._show('battle')
            else:
                self.field_choice.set(updated.name)
                self._show('field')
        except Exception as exc:
            messagebox.showerror('Ready image rejected', str(exc), parent=self)

    def apply(self, component='battle'):
        item = self._selected_set(component)
        if not item or not self.job_id:
            messagebox.showinfo('Character model', 'Select a job and a saved model first.', parent=self)
            return
        if component == 'battle' and not item.has_battle:
            messagebox.showerror('No battle sprites', 'This model does not include a battle sprite set.', parent=self)
            return
        if component == 'field' and not item.has_field:
            messagebox.showerror('No overworld sprites', 'This model does not include an overworld sprite set.', parent=self)
            return
        try:
            written = self.library.apply(item, self.job_id, component)
            self.on_dirty(True)
            destination = 'Direct Game Files staging' if item.kind == 'bundle' else 'Magicite overlay staging'
            label = 'battle' if component == 'battle' else 'overworld'
            self.on_status('PASS', f'Applied {label} model “{item.name}” to {self.job_name}: {len(written)} file(s) staged.')
            note = 'Use Direct Game Bundle Workbench to back up and deploy the compiled bundle.' if item.kind == 'bundle' else 'The PNG files are ready for normal Crystal Legacy deployment.'
            messagebox.showinfo(
                'Character appearance applied',
                f'Applied the {label} portion of “{item.name}” to {self.job_name}.\n\n{len(written)} file(s) staged in {destination}.\n\n{note}',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror('Could not apply model', str(exc), parent=self)
            self.on_status('ERROR', f'Character model apply failed: {exc}')
