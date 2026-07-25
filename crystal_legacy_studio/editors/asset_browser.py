from __future__ import annotations

import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from crystal_legacy_studio.assets.catalog import (
    AssetRecord,
    AssetStager,
    MagiciteAssetCatalog,
    CATEGORY_ORDER,
    IMAGE_EXTENSIONS,
)

try:
    from tkinterdnd2 import DND_FILES
except Exception:  # pragma: no cover - optional runtime integration
    DND_FILES = 'DND_Files'


class AssetBrowser(ttk.Frame):
    """RPG Maker-style view over the complete MagiciteExport resource tree."""

    def __init__(self, master, export_root: Path, working_overlays: Path, *,
                 initial_category: str | None = None, on_status=None, on_inspect=None,
                 on_dirty=None, on_saved=None):
        super().__init__(master, padding=12)
        self.export_root = Path(export_root)
        self.working_overlays = Path(working_overlays)
        self.on_status = on_status or (lambda *_: None)
        self.on_inspect = on_inspect or (lambda *_: None)
        self.on_dirty = on_dirty or (lambda *_: None)
        self.on_saved = on_saved
        self.catalog = MagiciteAssetCatalog(self.export_root)
        self.stager = AssetStager(self.export_root, self.working_overlays)
        self.records = self.catalog.scan()
        self.filtered: list[AssetRecord] = []
        self.preview_image = None
        self.selected_record: AssetRecord | None = None

        self.category_var = tk.StringVar(value=initial_category or CATEGORY_ORDER[0])
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value=f'{len(self.records):,} MagiciteExport files cataloged')
        self._build()
        self._refresh()
        self._enable_drop()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text='Magicite Asset Catalog', style='Title.TLabel').pack(side='left')
        ttk.Button(top, text='Rescan', command=self.rescan).pack(side='right', padx=3)
        ttk.Button(top, text='Deploy Working Assets', command=self.deploy).pack(side='right', padx=3)

        filters = ttk.Frame(self)
        filters.pack(fill='x', pady=(0, 8))
        ttk.Label(filters, text='Category').pack(side='left')
        combo = ttk.Combobox(filters, textvariable=self.category_var, state='readonly',
                             values=CATEGORY_ORDER, width=31)
        combo.pack(side='left', padx=(6, 12))
        combo.bind('<<ComboboxSelected>>', lambda _e: self._refresh())
        ttk.Label(filters, text='Search').pack(side='left')
        search = ttk.Entry(filters, textvariable=self.search_var)
        search.pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.search_var.trace_add('write', lambda *_: self._refresh())

        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes, padding=(10, 0, 0, 0))
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        self.tree = ttk.Treeview(left, columns=('group', 'type', 'size'), show='tree headings')
        self.tree.heading('#0', text='Asset / File')
        self.tree.heading('group', text='Resource Group')
        self.tree.heading('type', text='Type')
        self.tree.heading('size', text='Size')
        self.tree.column('#0', width=330, stretch=True)
        self.tree.column('group', width=150)
        self.tree.column('type', width=70, anchor='center')
        self.tree.column('size', width=90, anchor='e')
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self._selection_changed)
        self.tree.bind('<Double-1>', lambda _e: self.replace_selected())

        self.preview_label = ttk.Label(right, text='Select an asset to preview.', anchor='center')
        self.preview_label.pack(fill='both', expand=True)
        self.path_text = tk.Text(right, height=7, wrap='word')
        self.path_text.pack(fill='x', pady=(8, 6))
        self.path_text.configure(state='disabled')

        self.drop_zone = tk.Label(
            right,
            text='DROP REPLACEMENT FILE HERE\n\nOr use Replace Selected…',
            bg='#24272c', fg='#d7dbe0', relief='groove', bd=1,
            padx=12, pady=20, justify='center'
        )
        self.drop_zone.pack(fill='x', pady=(4, 8))
        actions = ttk.Frame(right)
        actions.pack(fill='x')
        ttk.Button(actions, text='Replace Selected…', command=self.replace_selected).pack(side='left')
        ttk.Button(actions, text='Add Files to Resource Group…', command=self.add_files).pack(side='left', padx=5)
        ttk.Button(actions, text='Open Source Folder', command=self.open_source_folder).pack(side='left')

        ttk.Label(self, textvariable=self.status_var, style='Muted.TLabel').pack(anchor='w', pady=(6, 0))

    def _enable_drop(self):
        # tkinterdnd2 adds these methods when MainWindow uses TkinterDnD.Tk.
        if hasattr(self.drop_zone, 'drop_target_register'):
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind('<<Drop>>', self._drop_received)
            self.drop_zone.configure(text='DROP REPLACEMENT FILE HERE\n\nZIPs and folders can also be staged')
        else:
            self.drop_zone.configure(text='Drag/drop support unavailable in this Python environment.\nUse Replace Selected… or Add Files…')

    @staticmethod
    def _human_size(value: int) -> str:
        size = float(value)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024 or unit == 'GB':
                return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
            size /= 1024
        return f'{value} B'

    def _refresh(self):
        category = self.category_var.get()
        query = self.search_var.get().strip().lower()
        self.filtered = [r for r in self.records if r.category == category and (
            not query or query in r.relative_path.lower() or query in r.resource_group.lower()
        )]
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.filtered):
            self.tree.insert('', 'end', iid=str(index), text=record.filename,
                             values=(record.resource_group, record.extension or 'file', self._human_size(record.size_bytes)))
        self.status_var.set(f'{len(self.filtered):,} shown in {category} • {len(self.records):,} total cataloged files')
        self.on_inspect('Magicite Asset Catalog', {
            'Category': category,
            'Visible assets': len(self.filtered),
            'Total files': len(self.records),
            'Read-only source': self.export_root,
            'Editable replacements': self.working_overlays,
        })

    def rescan(self):
        self.records = self.catalog.scan()
        manifest = self.catalog.write_manifest(self.working_overlays.parent / '.crystal' / 'magicite-asset-catalog.json')
        self._refresh()
        self.on_status('PASS', f'Cataloged {len(self.records):,} MagiciteExport files. Manifest: {manifest}')

    def _selection_changed(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_record = self.filtered[int(selected[0])]
        record = self.selected_record
        self._set_path_text(
            f'Category: {record.category}\nResource group: {record.resource_group}\n'
            f'Magicite path: {record.relative_path}\nSource: {record.source_path}\n'
            f'Working replacement: {self.working_overlays / record.relative_path}'
        )
        self.on_inspect(record.filename, {
            'Category': record.category,
            'Resource group': record.resource_group,
            'Extension': record.extension or '(none)',
            'Size': self._human_size(record.size_bytes),
            'Magicite relative path': record.relative_path,
            'Reference source': record.source_path,
            'Working replacement': self.working_overlays / record.relative_path,
        })
        self._preview(record)

    def _set_path_text(self, value: str):
        self.path_text.configure(state='normal')
        self.path_text.delete('1.0', 'end')
        self.path_text.insert('1.0', value)
        self.path_text.configure(state='disabled')

    def _preview(self, record: AssetRecord):
        source = Path(record.source_path)
        working = self.working_overlays / record.relative_path
        preview = working if working.exists() else source
        if record.extension not in IMAGE_EXTENSIONS:
            self.preview_image = None
            self.preview_label.configure(image='', text=f'{record.filename}\n\nNo visual preview for {record.extension or "this file type"}.')
            return
        try:
            image = Image.open(preview)
            image.thumbnail((440, 420), Image.Resampling.NEAREST)
            self.preview_image = ImageTk.PhotoImage(image)
            label = 'WORKING REPLACEMENT' if working.exists() else 'READ-ONLY REFERENCE'
            self.preview_label.configure(image=self.preview_image, text=label, compound='top')
        except Exception as exc:
            self.preview_image = None
            self.preview_label.configure(image='', text=f'Preview failed:\n{exc}')

    def replace_selected(self, replacement: Path | None = None):
        if not self.selected_record:
            messagebox.showinfo('Replace Asset', 'Select a catalog asset first.', parent=self)
            return False
        if replacement is None:
            replacement = filedialog.askopenfilename(
                title=f'Replace {self.selected_record.filename}',
                filetypes=[('Matching file', f'*{self.selected_record.extension}'), ('All files', '*.*')]
            )
            if not replacement:
                return False
        try:
            target = self.stager.stage_replacement(self.selected_record, Path(replacement))
            self.on_dirty(True)
            self.on_status('WRITE', f'Staged asset replacement: {target}')
            self.status_var.set(f'Staged replacement for {self.selected_record.filename}')
            self._preview(self.selected_record)
            return True
        except Exception as exc:
            messagebox.showerror('Replace Asset', str(exc), parent=self)
            self.on_status('ERROR', f'Asset replacement failed: {exc}')
            return False

    def add_files(self):
        group = self.selected_record.resource_group if self.selected_record else ''
        files = filedialog.askopenfilenames(title='Add files to selected Magicite resource group')
        if not files:
            return
        if not group:
            messagebox.showinfo('Add Assets', 'Select an existing resource group first.', parent=self)
            return
        try:
            targets = self.stager.stage_files_into_group(group, [Path(path) for path in files])
            self.on_dirty(True)
            self.on_status('WRITE', f'Staged {len(targets)} file(s) in resource group {group}.')
        except Exception as exc:
            messagebox.showerror('Add Assets', str(exc), parent=self)

    def _drop_received(self, event):
        try:
            paths = [Path(item) for item in self.tk.splitlist(event.data)]
            if len(paths) == 1 and paths[0].is_file() and paths[0].suffix.lower() == '.zip':
                targets = self.stager.stage_zip(paths[0])
                self.on_dirty(True)
                self.on_status('WRITE', f'Staged {len(targets)} file(s) from dropped ZIP.')
                return
            if len(paths) == 1 and paths[0].is_file() and self.selected_record:
                self.replace_selected(paths[0])
                return
            group = self.selected_record.resource_group if self.selected_record else ''
            if not group:
                raise ValueError('Select a resource group before dropping multiple files or folders.')
            targets = self.stager.stage_files_into_group(group, paths)
            self.on_dirty(True)
            self.on_status('WRITE', f'Staged {len(targets)} dropped file(s) in {group}.')
        except Exception as exc:
            messagebox.showerror('Drop Assets', str(exc), parent=self)

    def open_source_folder(self):
        if not self.selected_record:
            return
        folder = str(Path(self.selected_record.source_path).parent)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception:
            self.on_status('INFO', f'Source folder: {folder}')

    def save_changes(self):
        self.on_dirty(False)
        if self.on_saved:
            return bool(self.on_saved())
        return True

    def deploy(self):
        if self.on_saved:
            return self.on_saved()
        return False
