from __future__ import annotations

import colorsys
import json
import random
import shutil
from collections import Counter
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, simpledialog

from PIL import Image, ImageTk

from crystal_legacy_studio.assets.catalog import MagiciteAssetCatalog


BG = '#24272d'
FG = '#f2f2f2'


def _rgb_hex(rgb):
    return '#%02X%02X%02X' % tuple(int(v) for v in rgb)


def _distance(a, b):
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)) ** 0.5


def _palette(path: Path, limit: int = 8):
    with Image.open(path) as opened:
        image = opened.convert('RGBA')
        counts = Counter((r, g, b) for r, g, b, a in image.getdata() if a >= 32)
    selected = []
    for color, _ in counts.most_common():
        if max(color) < 18:
            continue
        if any(_distance(color, old) < 16 for old in selected):
            continue
        selected.append(color)
        if len(selected) >= limit:
            break
    return selected or [(200, 40, 40)]


def _recolor(source: Path, target: Path, mappings, tolerance: int):
    with Image.open(source) as opened:
        image = opened.convert('RGBA')
        pixels = []
        for r, g, b, a in image.getdata():
            if a < 32:
                pixels.append((r, g, b, a)); continue
            rgb = (r, g, b)
            candidates = [( _distance(rgb, src), src, dst) for src, dst in mappings]
            if candidates:
                dist, src, dst = min(candidates, key=lambda item: item[0])
                if dist <= tolerance:
                    # Preserve the source shade's brightness relative to its palette anchor.
                    src_l = max(1.0, sum(src) / 3.0)
                    pix_l = sum(rgb) / 3.0
                    ratio = max(0.25, min(2.0, pix_l / src_l))
                    nr, ng, nb = [max(0, min(255, round(v * ratio))) for v in dst]
                    pixels.append((nr, ng, nb, a)); continue
            pixels.append((r, g, b, a))
        image.putdata(pixels)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)


class MonsterPaletteStudio(ttk.Frame):
    def __init__(self, master, api, manifest):
        super().__init__(master, padding=12)
        self.api = api
        self.manifest = manifest
        self.export_root = Path(api.host._magicite_export_root())
        self.overlay_root = Path(api.project.layout.working_overlays)
        self.active_mod_root = Path(api.project.layout.active_mod)
        self.current_source_path = None
        self.current_source_kind = 'Original reference'
        self.library_root = Path(api.project.working_root) / 'MonsterSpriteSets'
        self.library_root.mkdir(parents=True, exist_ok=True)
        self.records = [r for r in MagiciteAssetCatalog(self.export_root).scan()
                        if r.category == 'Monster Sprites' and r.extension == '.png' and 'shadow' not in r.filename.lower()]
        self.filtered = []
        self.selected = None
        self.preview_ref = None
        self.generated_path = None
        self.search_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.tolerance = tk.IntVar(value=42)
        self.hue = tk.IntVar(value=0)
        self.saturation = tk.IntVar(value=100)
        self.brightness = tk.IntVar(value=100)
        self.random_style = tk.StringVar(value='Balanced')
        self.random_seed = tk.StringVar(value='')
        self.random_history = []
        self.enabled = [tk.BooleanVar(value=False) for _ in range(8)]
        self.sources = [[0, 0, 0] for _ in range(8)]
        self.targets = [[0, 0, 0] for _ in range(8)]
        self.slider_base = [[0, 0, 0] for _ in range(8)]
        self.source_canvases = []
        self.target_canvases = []
        self._build()
        self._refresh_list()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text='Monster Palette Studio', style='Title.TLabel').pack(side='left')
        ttk.Label(top, text='Recolor a monster appearance without changing its shape or transparency.', style='Muted.TLabel').pack(side='left', padx=14)

        body = ttk.Panedwindow(self, orient='horizontal'); body.pack(fill='both', expand=True)
        left = ttk.Frame(body); center = ttk.Frame(body, padding=(10,0)); right = ttk.Frame(body, padding=(10,0,0,0))
        body.add(left, weight=3); body.add(center, weight=3); body.add(right, weight=6)

        ttk.Label(left, text='Monster artwork').pack(anchor='w')
        search = ttk.Entry(left, textvariable=self.search_var); search.pack(fill='x', pady=(4,6))
        self.search_var.trace_add('write', lambda *_: self._refresh_list())
        self.tree = ttk.Treeview(left, columns=('group',), show='tree headings')
        self.tree.heading('#0', text='Image'); self.tree.heading('group', text='Resource group')
        self.tree.column('#0', width=245); self.tree.column('group', width=125)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._select)

        self.preview = ttk.Label(center, text='Select a monster sprite.', anchor='center')
        self.preview.pack(fill='both', expand=True)
        ttk.Label(center, text='Save as reusable appearance', style='Muted.TLabel').pack(anchor='w', pady=(8,2))
        name_entry = tk.Entry(center, textvariable=self.name_var, bg='#30343b', fg=FG,
                              insertbackground=FG, selectbackground='#4d78cc', relief='flat')
        name_entry.pack(fill='x', ipady=5)
        actions = ttk.Frame(center); actions.pack(fill='x', pady=(8,0))
        ttk.Button(actions, text='Save Recolor As…', command=self.save_as).pack(side='left')
        ttk.Button(actions, text='Apply && Deploy to Game', command=self.apply_selected).pack(side='left', padx=6)
        ttk.Button(actions, text='Restore Preview', command=self._render).pack(side='left')

        ttk.Label(right, text='Palette', style='Heading.TLabel').grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Label(right, text='Use').grid(row=1,column=0,sticky='w')
        ttk.Label(right, text='Original').grid(row=1,column=1,sticky='w')
        ttk.Label(right, text='New color').grid(row=1,column=2,sticky='w')
        for i in range(8):
            row = 2 + i
            ttk.Checkbutton(right, variable=self.enabled[i], command=self._render).grid(row=row,column=0,sticky='w')
            src = tk.Canvas(right, width=44, height=25, bg=BG, highlightthickness=0, cursor='hand2')
            src.grid(row=row,column=1,padx=(0,10),pady=2); src.bind('<Button-1>', lambda e, i=i: self._choose(i, False))
            dst = tk.Canvas(right, width=44, height=25, bg=BG, highlightthickness=0, cursor='hand2')
            dst.grid(row=row,column=2,pady=2); dst.bind('<Button-1>', lambda e, i=i: self._choose(i, True))
            ttk.Button(right, text='Choose…', width=9, command=lambda i=i: self._choose(i, True)).grid(row=row,column=3,padx=(6,0))
            self.source_canvases.append(src); self.target_canvases.append(dst)

        ttk.Label(right, text='Match range').grid(row=10,column=0,columnspan=2,sticky='w',pady=(10,0))
        tk.Scale(right, from_=8,to=100,orient='horizontal',variable=self.tolerance,length=390,
                 showvalue=True,highlightthickness=0,command=lambda _=None:self._render()).grid(row=10,column=2,columnspan=2,sticky='ew',pady=(10,0))
        sliders = [('Hue', self.hue, -180, 180), ('Saturation', self.saturation, 25, 200), ('Brightness', self.brightness, 25, 175)]
        for offset, (label,var,lo,hi) in enumerate(sliders, start=11):
            ttk.Label(right,text=label).grid(row=offset,column=0,sticky='w')
            tk.Scale(right,from_=lo,to=hi,orient='horizontal',variable=var,length=390,
                     showvalue=True,highlightthickness=0,command=lambda _=None:self._auto()).grid(row=offset,column=1,columnspan=3,sticky='ew')

        random_box = ttk.LabelFrame(right, text='Disgaea-style Palette Randomizer', padding=8)
        random_box.grid(row=14, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        ttk.Label(random_box, text='Style').grid(row=0, column=0, sticky='w')
        ttk.Combobox(random_box, textvariable=self.random_style, state='readonly', width=16,
                     values=('Balanced','Dark','Bright','Fire','Ice','Poison','Undead','Metallic','Royal','Wild')).grid(row=0,column=1,sticky='ew',padx=6)
        ttk.Label(random_box, text='Seed').grid(row=1, column=0, sticky='w', pady=(5,0))
        seed_entry = ttk.Entry(random_box, textvariable=self.random_seed, width=16)
        seed_entry.grid(row=1,column=1,sticky='ew',padx=6,pady=(5,0))
        ttk.Button(random_box, text='Randomize', command=self._randomize).grid(row=0,column=2,padx=(4,0))
        ttk.Button(random_box, text='Again', command=lambda: self._randomize(True)).grid(row=1,column=2,padx=(4,0),pady=(5,0))
        ttk.Button(random_box, text='Undo Random', command=self._undo_random).grid(row=2,column=1,columnspan=2,sticky='e',pady=(6,0))
        ttk.Label(random_box, text='Unchecked palette rows stay locked. Near-black outlines are protected automatically.', style='Muted.TLabel', wraplength=390).grid(row=3,column=0,columnspan=3,sticky='w',pady=(6,0))
        random_box.columnconfigure(1, weight=1)
        ttk.Button(right, text='Reset Palette', command=self._reset).grid(row=15,column=0,columnspan=4,sticky='e',pady=(8,0))

    def _refresh_list(self):
        q = self.search_var.get().lower().strip()
        self.filtered = [r for r in self.records if not q or q in r.filename.lower() or q in r.resource_group.lower()]
        self.tree.delete(*self.tree.get_children())
        for idx, record in enumerate(self.filtered):
            self.tree.insert('', 'end', iid=str(idx), text=record.filename, values=(record.resource_group,))

    def _select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        self.selected = self.filtered[int(sel[0])]
        self.name_var.set(f'{Path(self.selected.filename).stem} Recolor')
        self.current_source_path, self.current_source_kind = self._resolve_current_source()
        colors = _palette(self.current_source_path, 8)
        for i in range(8):
            active = i < len(colors); self.enabled[i].set(active)
            c = colors[i] if active else (0,0,0)
            self.sources[i][:] = c; self.targets[i][:] = c; self.slider_base[i][:] = c
            self._paint(self.source_canvases[i], c); self._paint(self.target_canvases[i], c)
        self.hue.set(0); self.saturation.set(100); self.brightness.set(100)
        self.generated_path = None
        self._render()
        self.api.inspect('Monster Sprite Studio', {
            'File': self.selected.filename,
            'Resource group': self.selected.resource_group,
            'Displayed source': str(self.current_source_path),
            'Source layer': self.current_source_kind,
            'Original reference': self.selected.source_path,
            'Working replacement': str(self.overlay_root / self.selected.relative_path),
        })


    def _resolve_current_source(self):
        """Return the currently active monster image using layered project priority.

        Priority is the writable Studio overlay, then the currently deployed
        Crystal Legacy mod, then the untouched MagiciteExport reference.
        """
        if not self.selected:
            return None, 'Original reference'
        relative = Path(self.selected.relative_path)
        candidates = (
            (self.overlay_root / relative, 'Working edit'),
            (self.active_mod_root / relative, 'Active deployed mod'),
            (Path(self.selected.source_path), 'Original reference'),
        )
        for candidate, label in candidates:
            if candidate.is_file():
                return candidate, label
        return Path(self.selected.source_path), 'Original reference'

    def _paint(self, canvas, rgb):
        canvas.delete('all'); canvas.create_rectangle(1,1,42,23,fill=_rgb_hex(rgb),outline='#aab0b8')

    def _choose(self, index, target):
        values = self.targets if target else self.sources
        result = colorchooser.askcolor(color=_rgb_hex(values[index]), parent=self, title='Choose monster color')
        if not result or not result[0]: return
        values[index][:] = [int(v) for v in result[0]]
        if target:
            self.slider_base[index][:] = values[index]
            self.hue.set(0); self.saturation.set(100); self.brightness.set(100)
        self._paint(self.target_canvases[index] if target else self.source_canvases[index], values[index])
        self._render()

    def _auto(self):
        hd = self.hue.get() / 360.0; sm = self.saturation.get()/100.0; vm = self.brightness.get()/100.0
        for i in range(8):
            if not self.enabled[i].get(): continue
            r,g,b = self.slider_base[i]
            h,s,v = colorsys.rgb_to_hsv(r/255,g/255,b/255)
            rr,gg,bb = colorsys.hsv_to_rgb((h+hd)%1.0, max(0,min(1,s*sm)), max(.02,min(1,v*vm)))
            self.targets[i][:] = [round(rr*255),round(gg*255),round(bb*255)]
            self._paint(self.target_canvases[i], self.targets[i])
        self._render()

    def _theme_family(self, rng, style):
        base = rng.random()
        families = {
            'Balanced': ((base, (base + .09) % 1.0, (base + .50) % 1.0), .66, .88),
            'Dark': ((.72, .82, .10), .62, .50),
            'Bright': ((base, (base + .16) % 1.0, (base + .52) % 1.0), .74, 1.0),
            'Fire': ((.00, .055, .13), .88, .98),
            'Ice': ((.56, .62, .50), .66, .98),
            'Poison': ((.78, .36, .91), .78, .86),
            'Undead': ((.73, .25, .12), .38, .68),
            'Metallic': ((.58, .64, .13), .18, .92),
            'Royal': ((.72, .04, .13), .72, .88),
            'Wild': ((rng.random(), rng.random(), rng.random()), .90, .98),
        }
        return families.get(style, families['Balanced'])

    def _style_color(self, rng, style, source, index, family):
        h0, s0, v0 = colorsys.rgb_to_hsv(*(c / 255 for c in source))
        hues, sat_base, val_base = family
        # Rotate through primary/secondary/accent anchors. This is the key change
        # that prevents every enabled monster swatch becoming the same teal/blue.
        if s0 < .13:
            hue = hues[0]
            sat = min(.20, sat_base * .30)
        else:
            hue = hues[index % len(hues)]
            sat = max(.08, min(1.0, sat_base * rng.uniform(.86, 1.12)))
        hue = (hue + rng.uniform(-.018, .018)) % 1.0
        val = max(.06, min(1.0, val_base * (.46 + .64 * max(.10, v0))))
        return [round(c*255) for c in colorsys.hsv_to_rgb(hue, sat, val)]

    @staticmethod
    def _hue_distance(a, b):
        d = abs(a - b) % 1.0
        return min(d, 1.0 - d)

    def _shade_groups(self, indices):
        groups = []
        for i in indices:
            h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in self.sources[i]))
            neutral = sat < .16
            placed = False
            for group in groups:
                gh, gsat, _ = group['center']
                if neutral == group['neutral'] and (neutral or (self._hue_distance(h, gh) <= .075 and abs(sat - gsat) <= .34)):
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

    def _randomize(self, again=False):
        if not self.selected: return
        self.random_history.append([list(v) for v in self.targets])
        raw = self.random_seed.get().strip()
        if again or not raw:
            raw = str(random.SystemRandom().randrange(100000, 999999999))
            self.random_seed.set(raw)
        try: seed = int(raw)
        except ValueError: seed = sum((i+1)*ord(ch) for i,ch in enumerate(raw))
        rng = random.Random(seed)
        family = self._theme_family(rng, self.random_style.get())
        enabled_indices = [i for i in range(8) if self.enabled[i].get()]
        groups = self._shade_groups(enabled_indices)
        for group_index, group in enumerate(groups):
            # Shades from one material share one hue anchor and retain their value ramp.
            for i, _h, _sat, _val in group['items']:
                self.targets[i][:] = self._style_color(
                    rng, self.random_style.get(), self.sources[i], group_index, family
                )
                self.slider_base[i][:] = self.targets[i]
                self._paint(self.target_canvases[i], self.targets[i])
        # Sliders now begin from the randomized result instead of the original palette.
        self.hue.set(0); self.saturation.set(100); self.brightness.set(100)
        self._render()

    def _undo_random(self):
        if not self.random_history: return
        old = self.random_history.pop()
        for i, color in enumerate(old):
            self.targets[i][:] = color
            self.slider_base[i][:] = color
            self._paint(self.target_canvases[i], color)
        self.hue.set(0); self.saturation.set(100); self.brightness.set(100)
        self._render()

    def _mappings(self):
        return [(tuple(self.sources[i]), tuple(self.targets[i])) for i in range(8) if self.enabled[i].get()]

    def _render(self):
        if not self.selected: return
        try:
            temp = self.library_root / '.preview.png'
            source_path, source_kind = self._resolve_current_source()
            self.current_source_path, self.current_source_kind = source_path, source_kind
            _recolor(source_path, temp, self._mappings(), self.tolerance.get())
            with Image.open(temp) as opened:
                img = opened.convert('RGBA')
                # Keep monster art readable without consuming the palette workspace.
                scale = max(1, min(8, 220 // max(img.width, img.height)))
                img = img.resize((img.width*scale,img.height*scale), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(img); self.preview_ref = photo
            self.preview.configure(image=photo, text='')
        except Exception as exc:
            self.preview.configure(image='', text=f'Preview unavailable\n{exc}')

    def _reset(self):
        self.hue.set(0); self.saturation.set(100); self.brightness.set(100)
        for i in range(8):
            self.targets[i][:] = self.sources[i]
            self.slider_base[i][:] = self.sources[i]
            self._paint(self.target_canvases[i], self.targets[i])
        self._render()

    def save_as(self):
        if not self.selected:
            messagebox.showinfo('Monster Recolor', 'Select a monster sprite first.', parent=self); return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror('Monster Recolor', 'Enter a name for the recolored appearance.', parent=self); return
        safe = ''.join(c if c.isalnum() or c in ' -_.' else '_' for c in name).strip().rstrip('.')
        folder = self.library_root / safe
        if folder.exists():
            replace = messagebox.askyesno('Replace saved appearance?', f'“{name}” already exists. Replace it?', parent=self)
            if not replace: return
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        output = folder / self.selected.filename
        source_path, source_kind = self._resolve_current_source()
        self.current_source_path, self.current_source_kind = source_path, source_kind
        _recolor(source_path, output, self._mappings(), self.tolerance.get())
        manifest = {
            'name': name, 'type': 'monster-recolor', 'sourceRelativePath': self.selected.relative_path,
            'sourceLayer': self.current_source_kind, 'sourceImagePath': str(self.current_source_path),
            'sourceResourceGroup': self.selected.resource_group, 'image': output.name,
            'matchRange': self.tolerance.get(),
            'palette': [{'source': list(s), 'target': list(t)} for s,t in self._mappings()],
        }
        (folder/'monster-appearance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        self.generated_path = output
        self.api.log('PASS', f'Saved reusable monster appearance “{name}”.')
        messagebox.showinfo('Monster recolor saved', f'Saved “{name}” to the Monster Sprite Library.', parent=self)

    def _materialize_resource_group(self, group_root: Path, overlay_group: Path):
        """Create a complete writable copy of a Magicite resource group.

        Magicite treats a resource-group folder as a replacement layer. Deploying
        only one PNG and Export.json can hide the untouched files from the base
        group, which makes monsters disappear in battle. We therefore seed every
        missing file from MagiciteExport before writing the recolored image.
        Existing working files are preserved.
        """
        if not group_root.is_dir():
            raise FileNotFoundError(f'Reference resource group not found: {group_root}')
        copied = 0
        preserved = 0
        for source_file in group_root.rglob('*'):
            if not source_file.is_file():
                continue
            relative = source_file.relative_to(group_root)
            target_file = overlay_group / relative
            if target_file.exists():
                preserved += 1
                continue
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied += 1
        return copied, preserved

    def apply_selected(self):
        if not self.selected:
            messagebox.showinfo('Monster Recolor', 'Select a monster sprite first.', parent=self); return

        source = self.generated_path
        if not source or not Path(source).exists():
            temp = self.library_root / '.apply.png'
            source_path, source_kind = self._resolve_current_source()
            self.current_source_path, self.current_source_kind = source_path, source_kind
            _recolor(source_path, temp, self._mappings(), self.tolerance.get())
            source = temp

        group_root = self.export_root / self.selected.resource_group
        overlay_group = self.overlay_root / self.selected.resource_group
        try:
            copied, preserved = self._materialize_resource_group(group_root, overlay_group)
        except Exception as exc:
            messagebox.showerror('Monster recolor not deployed',
                f'Studio could not build a complete writable monster resource group:\n\n{exc}', parent=self)
            self.api.log('ERROR', f'Monster resource-group materialization failed: {exc}')
            return

        # selected.relative_path already begins with the resource-group folder.
        target = self.overlay_root / self.selected.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

        key_file = overlay_group / 'keys' / 'Export.json'
        if not key_file.is_file():
            messagebox.showerror('Monster recolor not deployed',
                f'The complete resource group is missing its key map:\n{key_file}', parent=self)
            self.api.log('ERROR', f'Missing monster key map after materialization: {key_file}')
            return

        group_files = sum(1 for item in overlay_group.rglob('*') if item.is_file())
        self.api.log('PASS',
            f'Prepared complete monster resource group {self.selected.resource_group}: '
            f'{group_files} files ({copied} seeded, {preserved} preserved); replaced {self.selected.filename}.')
        try:
            self.api.host.deploy_live_files()
            messagebox.showinfo('Monster recolor deployed',
                'Studio deployed the complete monster resource group, not only the PNG.\n\n'
                f'Group: {self.selected.resource_group}\nFiles: {group_files}\n'
                f'Recolored image: {self.selected.filename}\n\n'
                'Close the current battle and begin a new encounter. If the game was already running when the group was first created, restart the game once.',
                parent=self)
        except Exception as exc:
            messagebox.showwarning('Monster recolor staged',
                f'The complete resource group is staged, but automatic deployment did not finish:\n\n{exc}\n\nUse the main Save button to deploy it.', parent=self)


def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error('Monster Sprite Studio', 'Open a project first.'); return
        key = 'monster-palette-studio'
        existing = api.host.tab_frames.get(f'plugin:{key}')
        if existing and str(existing) in api.host.workspace.tabs():
            api.host.workspace.select(existing); return
        frame = MonsterPaletteStudio(api.host.workspace, api, manifest)
        api.add_tab(key, 'Monster Sprite Studio', frame)
        api.log('PLUGIN', 'Monster Palette Studio opened.')
        api.inspect('Monster Sprite Studio', {'Plugin': manifest.get('name'), 'Version': manifest.get('version'), 'Scope': 'Monster preview, reusable palette recolors, replacement staging'})
    return {'open': open_editor}
