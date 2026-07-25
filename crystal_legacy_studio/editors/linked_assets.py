from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from crystal_legacy_studio.assets.catalog import MagiciteAssetCatalog, AssetRecord, IMAGE_EXTENSIONS

BATTLE_BUNDLE_RE = re.compile(r'^bc_ff1_p(\d{3})_assets_all_[0-9a-f]+\.bundle$', re.I)
FIELD_BUNDLE_RE = re.compile(r'^mo_ff1_p(\d{3})_c00_assets_all_[0-9a-f]+\.bundle$', re.I)
BATTLE_GROUP_RE = re.compile(r'^bc_ff1_p(\d{3})$', re.I)
FIELD_GROUP_RE = re.compile(r'^mo_ff1_p(\d{3})_c00$', re.I)

BATTLE_FRAME_NAMES = (
    'Damage_00', 'Default_00', 'Down_00', 'Dying_00',
    'LeftAttack_00', 'LeftAttack_01', 'Ready_00',
    'RightAttack_00', 'RightAttack_01', 'SkillReady_00',
    'SkillReady_01', 'Win_00',
)
FIELD_FRAME_NAMES = (
    'Default_00', 'Default_01', 'Down_00', 'LookDown_00',
    'RightHandUp_00', 'RightHandUp_01', 'WalkB_00', 'WalkB_01',
    'WalkL_00', 'WalkL_01',
)

try:
    from tkinterdnd2 import DND_FILES
except Exception:  # pragma: no cover
    DND_FILES = 'DND_Files'


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _image_signature(path: Path) -> dict:
    with Image.open(path) as image:
        return {
            'format': image.format or path.suffix.lstrip('.').upper(),
            'width': image.width,
            'height': image.height,
            'mode': image.mode,
            'frames': int(getattr(image, 'n_frames', 1)),
        }


def validate_replacement(reference: Path, replacement: Path) -> ValidationResult:
    reference, replacement = Path(reference), Path(replacement)
    errors: list[str] = []
    warnings: list[str] = []
    if not replacement.is_file():
        return ValidationResult(False, (f'File does not exist: {replacement}',))
    if replacement.stat().st_size <= 0:
        errors.append('Replacement file is empty.')
    if reference.suffix.lower() != replacement.suffix.lower():
        errors.append(f'File type must remain {reference.suffix.lower() or "extensionless"}; received {replacement.suffix.lower() or "extensionless"}.')
    if reference.suffix.lower() in IMAGE_EXTENSIONS and replacement.suffix.lower() in IMAGE_EXTENSIONS:
        try:
            wanted = _image_signature(reference)
            actual = _image_signature(replacement)
            if (wanted['width'], wanted['height']) != (actual['width'], actual['height']):
                errors.append(
                    f'Canvas size must be exactly {wanted["width"]}×{wanted["height"]}; '
                    f'replacement is {actual["width"]}×{actual["height"]}.'
                )
            if wanted['frames'] != actual['frames']:
                errors.append(f'Frame count must be {wanted["frames"]}; replacement has {actual["frames"]}.')
            if wanted['mode'] != actual['mode']:
                warnings.append(f'Pixel mode differs ({wanted["mode"]} → {actual["mode"]}). Preserve transparency/palette when possible.')
        except Exception as exc:
            errors.append(f'Image could not be read: {exc}')
    elif reference.suffix.lower() == '.spritedata':
        try:
            text = replacement.read_text(encoding='utf-8', errors='replace')
            required = ('TextureOverride', 'Rect', 'Pivot', 'PixelsPerUnit')
            missing = [key for key in required if key not in text]
            if missing:
                errors.append('spriteData is missing required field(s): ' + ', '.join(missing))
        except Exception as exc:
            errors.append(f'spriteData could not be read: {exc}')
    elif reference.suffix.lower() == '.bundle':
        try:
            if replacement.read_bytes()[:7] != b'UnityFS':
                errors.append('Replacement is not a UnityFS asset bundle.')
        except Exception as exc:
            errors.append(f'Bundle could not be read: {exc}')
        ref_family = re.sub(r'_[0-9a-f]{16,}(?=\.bundle$)', '', reference.name, flags=re.I)
        new_family = re.sub(r'_[0-9a-f]{16,}(?=\.bundle$)', '', replacement.name, flags=re.I)
        if ref_family != new_family:
            errors.append(f'Bundle family must remain {ref_family}; received {new_family}.')
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


class LinkedAssetPanel(ttk.Frame):
    """Entity-aware sprite/icon replacement page with strict reference validation."""

    def __init__(self, parent, export_root: Path, working_overlays: Path, categories: tuple[str, ...], *,
                 title='Linked Assets', on_status=None, on_dirty=None, bundle_root: Path | None = None):
        super().__init__(parent, padding=10)
        self.export_root = Path(export_root)
        self.working_overlays = Path(working_overlays)
        self.categories = categories
        self.bundle_root = Path(bundle_root) if bundle_root else None
        self.title_text = title
        self.on_status = on_status or (lambda *_: None)
        self.on_dirty = on_dirty or (lambda *_: None)
        self.catalog = MagiciteAssetCatalog(self.export_root)
        # Artists work only with visible PNGs. Unity metadata and whole bundles
        # remain engine details managed by deployment, not user-editable sprite entries.
        self.records = [r for r in self.catalog.scan() if r.category in categories and r.extension.lower() == '.png']
        self.visible: list[AssetRecord] = []
        self.tokens: list[str] = []
        self.entity_label = 'No record selected'
        self.preview_image = None
        self.selected: AssetRecord | None = None
        self._build()
        self.set_entity('No record selected', [])


    def _scan_character_bundles(self) -> list[AssetRecord]:
        if not self.bundle_root or not self.bundle_root.is_dir():
            return []
        records: list[AssetRecord] = []
        for path in sorted(self.bundle_root.glob('*.bundle')):
            name = path.name
            if BATTLE_BUNDLE_RE.match(name) and 'Character Battle Sprites' in self.categories:
                category = 'Character Battle Sprites'
            elif FIELD_BUNDLE_RE.match(name) and 'Character Field Sprites' in self.categories:
                category = 'Character Field Sprites'
            else:
                continue
            records.append(AssetRecord(
                category=category,
                resource_group='Addressables / Character Bundles',
                relative_path=f'__addressables__/{name}',
                filename=name, extension='.bundle',
                size_bytes=path.stat().st_size, source_path=str(path),
            ))
        return records

    def _build(self):
        ttk.Label(self, text=self.title_text, style='Heading.TLabel').pack(anchor='w')
        self.help = ttk.Label(self, text='', style='Muted.TLabel', wraplength=850)
        self.help.pack(anchor='w', pady=(4, 8))
        toolbar = ttk.Frame(self); toolbar.pack(fill='x', pady=(0, 6))
        self.search = tk.StringVar(); self.search.trace_add('write', lambda *_: self._refresh())
        ttk.Label(toolbar, text='Filter').pack(side='left')
        ttk.Entry(toolbar, textvariable=self.search).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(toolbar, text='Show All Category Assets', command=self.show_all).pack(side='right')

        pane = ttk.Panedwindow(self, orient='horizontal'); pane.pack(fill='both', expand=True)
        left = ttk.Frame(pane); right = ttk.Frame(pane, padding=(10, 0, 0, 0)); pane.add(left, weight=3); pane.add(right, weight=2)
        self.tree = ttk.Treeview(left, columns=('category', 'group', 'state'), show='tree headings')
        self.tree.heading('#0', text='File'); self.tree.heading('category', text='Category'); self.tree.heading('group', text='Group'); self.tree.heading('state', text='State')
        self.tree.column('#0', width=300); self.tree.column('category', width=170); self.tree.column('group', width=130); self.tree.column('state', width=95)
        sy = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side='left', fill='both', expand=True); sy.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self._selected)

        self.preview = ttk.Label(right, text='Select a linked asset.', anchor='center'); self.preview.pack(fill='both', expand=True)
        self.details = tk.Text(right, height=9, wrap='word'); self.details.pack(fill='x', pady=6); self.details.configure(state='disabled')
        self.drop = tk.Label(right, text='DROP REPLACEMENT HERE', bg='#24272c', fg='#d7dbe0', relief='groove', bd=1, padx=8, pady=18)
        self.drop.pack(fill='x', pady=6)
        buttons = ttk.Frame(right); buttons.pack(fill='x')
        ttk.Button(buttons, text='Import / Replace…', command=self.import_selected).pack(side='left')
        ttk.Button(buttons, text='Restore Reference', command=self.restore_selected).pack(side='left', padx=5)
        if hasattr(self.drop, 'drop_target_register'):
            self.drop.drop_target_register(DND_FILES); self.drop.dnd_bind('<<Drop>>', self._drop_received)
        else:
            self.drop.configure(text='Drag/drop unavailable; use Import / Replace…')

    def set_entity(self, label: str, tokens: list[str | int]):
        self.entity_label = label
        normalized = []
        self.entity_ids: set[str] = set()
        for value in tokens:
            value = str(value or '').strip().lower()
            if not value:
                continue
            if value.isdigit():
                pid = value.zfill(3)
                self.entity_ids.add(pid)
                normalized.extend([f'p{pid}', f'_p{pid}_', f'_p{pid}_c00_'])
            else:
                normalized.append(value)
        self.tokens = sorted(set(normalized), key=len, reverse=True)
        ids = ', '.join(f'p{value}' for value in sorted(self.entity_ids)) or 'unmapped'
        self.help.configure(text=(
            f'{label} ({ids}): showing only the exact Magicite class resource group. '
            'Battle classes use bc_ff1_p###; map/field classes use mo_ff1_p###_c00. '
            'Only visible PNG artwork is shown. Imported images must match the reference canvas and transparency before staging.'
        ))
        self._refresh(entity_only=True)

    def show_all(self):
        self.tokens = []
        self._refresh(entity_only=False)

    def _matches(self, record: AssetRecord) -> bool:
        if not self.tokens:
            return True
        name = record.filename.lower()
        battle_bundle = BATTLE_BUNDLE_RE.match(name)
        field_bundle = FIELD_BUNDLE_RE.match(name)
        if battle_bundle or field_bundle:
            return (battle_bundle or field_bundle).group(1) in getattr(self, 'entity_ids', set())

        group = record.resource_group.lower()
        battle_group = BATTLE_GROUP_RE.match(group)
        field_group = FIELD_GROUP_RE.match(group)
        if battle_group or field_group:
            return (battle_group or field_group).group(1) in getattr(self, 'entity_ids', set())
        return False

    def _refresh(self, entity_only=True):
        query = self.search.get().strip().lower()
        matched = [r for r in self.records if self._matches(r) and (not query or query in r.relative_path.lower())]
        self.visible = matched
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.visible):
            working = self._working_path(record)
            display = f'{self.entity_label} — {record.filename}' if self.tokens else record.filename
            self.tree.insert('', 'end', iid=str(index), text=display,
                             values=(record.category, record.resource_group, 'Modified' if working.exists() else 'Reference'))
        if self.tokens and not self.visible:
            expected = []
            for pid in sorted(getattr(self, 'entity_ids', set())):
                if 'Character Battle Sprites' in self.categories:
                    expected.append(f'bc_ff1_p{pid}')
                if 'Character Field Sprites' in self.categories:
                    expected.append(f'mo_ff1_p{pid}_c00')
            self.preview.configure(image='', text='No exact class sprite export found.\nExpected resource group: ' + ', '.join(expected))
            self.preview_image = None


    def _working_path(self, record: AssetRecord) -> Path:
        if record.relative_path.startswith('__addressables__/'):
            return self.working_overlays / 'Addressables' / 'StandaloneWindows64' / record.filename
        return self.working_overlays / record.relative_path

    def _selected(self, _event=None):
        selection = self.tree.selection()
        if not selection: return
        self.selected = self.visible[int(selection[0])]
        source = Path(self.selected.source_path); working = self._working_path(self.selected)
        active = working if working.exists() else source
        detail = f'Class: {self.entity_label}\nResource group: {self.selected.resource_group}\nReference: {source}\nWorking: {working}\nDeploy path: {self.selected.relative_path}'
        if source.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                sig = _image_signature(source); detail += f'\nRequired image: {sig["width"]}×{sig["height"]}, {sig["mode"]}, {sig["frames"]} frame(s)'
                image = Image.open(active); image.thumbnail((390, 330), Image.Resampling.NEAREST)
                self.preview_image = ImageTk.PhotoImage(image); self.preview.configure(image=self.preview_image, text='')
            except Exception as exc:
                self.preview.configure(image='', text=f'Preview failed: {exc}'); self.preview_image = None
        else:
            self.preview.configure(image='', text=f'{source.name}\n{source.suffix or "binary resource"}'); self.preview_image = None
        self.details.configure(state='normal'); self.details.delete('1.0', 'end'); self.details.insert('1.0', detail); self.details.configure(state='disabled')

    def _parse_drop(self, value: str) -> Path | None:
        value = value.strip()
        if value.startswith('{') and value.endswith('}'):
            value = value[1:-1]
        return Path(value) if value else None

    def _drop_received(self, event):
        paths = self.tk.splitlist(event.data)
        if len(paths) != 1:
            messagebox.showerror('Sprite import', 'Drop exactly one replacement file onto a selected asset.', parent=self); return
        self.import_selected(Path(paths[0]))

    def import_selected(self, replacement: Path | None = None):
        if not self.selected:
            messagebox.showinfo('Sprite import', 'Select the exact sprite or icon image being replaced first.', parent=self); return False
        if replacement is None:
            value = filedialog.askopenfilename(title=f'Replace {self.selected.filename}', parent=self)
            if not value: return False
            replacement = Path(value)
        reference = Path(self.selected.source_path)
        result = validate_replacement(reference, replacement)
        if not result.ok:
            messagebox.showerror('Asset does not fit', '\n'.join(result.errors), parent=self)
            self.on_status('ERROR', f'Rejected {replacement.name}: ' + '; '.join(result.errors)); return False
        if result.warnings and not messagebox.askyesno('Asset warning', '\n'.join(result.warnings) + '\n\nImport anyway?', parent=self):
            return False
        target = self._working_path(self.selected)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(replacement, target)
        self.on_dirty(True); self.on_status('PASS', f'Validated and staged asset: {target}')
        self._refresh(); return True

    def restore_selected(self):
        if not self.selected: return
        target = self._working_path(self.selected)
        if target.exists():
            target.unlink(); self.on_dirty(True); self.on_status('PASS', f'Removed working replacement; reference restored: {self.selected.relative_path}')
            self._refresh()
