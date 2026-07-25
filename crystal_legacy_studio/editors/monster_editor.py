from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
import shutil, datetime

from PIL import Image, ImageTk
from crystal_legacy_studio.assets.catalog import MagiciteAssetCatalog

from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.ui.widgets.field_labels import friendly_label
from crystal_legacy_studio.editors.monster_profiles import BOOST_FIELDS, boosted_rows, save_profile, activate_profile
from crystal_legacy_studio.editors.linked_assets import LinkedAssetPanel

SECTIONS = {
    "Identity": ["id", "mes_id_name", "lv", "boss", "monster_asset_id"],
    "Combat Stats": ["hp", "mp", "attack_count", "strength", "vitality", "agility", "intelligence", "spirit", "magic", "attack", "ability_attack", "defense", "ability_defense", "accuracy_rate", "evasion_rate", "magic_evasion_rate", "critical_rate", "luck"],
    "Rewards & Drops": ["exp", "gill", "drop_rate", "drop_content_id1", "drop_content_id1_value"],
    "AI & Runtime": ["script_id"],
}
PRESETS={
    "Monster+":{"hp":1.5,"attack":1.25,"defense":1.25,"magic":1.25,"ability_attack":1.25,"ability_defense":1.25,"exp":1.5,"gill":1.5},
    "Monster++":{"hp":2.0,"attack":1.5,"defense":1.5,"magic":1.5,"ability_attack":1.5,"ability_defense":1.5,"exp":2.0,"gill":2.0},
    "Monster+++":{"hp":3.0,"attack":2.0,"defense":2.0,"magic":2.0,"ability_attack":2.0,"ability_defense":2.0,"exp":3.0,"gill":3.0},
}

class MonsterEditor(ttk.Frame):
    def __init__(self, parent, document, messages, on_dirty, on_status, on_inspect, export_root=None, working_overlays=None, on_saved=None):
        super().__init__(parent);self.document=document;self.messages=messages;self.on_dirty=on_dirty;self.on_status=on_status;self.on_inspect=on_inspect;self.export_root=export_root;self.working_overlays=working_overlays;self.on_saved=on_saved
        self.current=None;self.indices=[];self.loading=False;self.vars={};self.project_root=document.path.parents[2]
        self._build();self.refresh()
        if self.indices:self.list.selection_set(0);self.select(0)
    def _build(self):
        h=ttk.Frame(self,padding=12);h.pack(fill='x');ttk.Label(h,text='Monster Designer',style='Title.TLabel').pack(side='left');ttk.Button(h,text='Save Monster Data',command=self.save).pack(side='right');ttk.Button(h,text='Validate',command=self.validate).pack(side='right',padx=6)
        pane=ttk.Panedwindow(self,orient='horizontal');pane.pack(fill='both',expand=True,padx=10,pady=10);left=ttk.Frame(pane,padding=8);right=ttk.Frame(pane,padding=8);pane.add(left,weight=1);pane.add(right,weight=6)
        self.search=tk.StringVar();self.search.trace_add('write',lambda *_:self.refresh());ttk.Entry(left,textvariable=self.search).pack(fill='x',pady=(0,8))
        self.list=tk.Listbox(left,bg=DARK['panel'],fg=DARK['fg'],selectbackground=DARK['selection'],relief='flat',exportselection=False);self.list.pack(fill='both',expand=True);self.list.bind('<<ListboxSelect>>',self._selected)
        b=ttk.Frame(left);b.pack(fill='x',pady=6);ttk.Button(b,text='Duplicate',command=self.duplicate).pack(side='left');ttk.Button(b,text='Delete',command=self.delete).pack(side='left',padx=4)
        self.monster_preview_ref=None
        preview_box=ttk.LabelFrame(left,text='Active battle sprite',padding=5);preview_box.pack(fill='x',pady=(3,5))
        self.monster_preview=ttk.Label(preview_box,text='Select a monster',anchor='center');self.monster_preview.pack(fill='both',expand=True)
        pvbuttons=ttk.Frame(preview_box);pvbuttons.pack(fill='x',pady=(4,0))
        ttk.Button(pvbuttons,text='Refresh',command=self.refresh_monster_preview).pack(side='left')
        ttk.Button(pvbuttons,text='Open Sprites',command=self.open_sprite_tab).pack(side='left',padx=4)
        restore=ttk.LabelFrame(left,text='Safety / Restore',padding=5);restore.pack(fill='x',pady=(3,0))
        for i,(label,cmd) in enumerate((('Undo Unsaved',self.undo_unsaved),('Restore Selected',self.restore_selected),('Restore All',self.restore_all),('Import Original',self.import_original_table),('Create Backup',self.create_backup))):
            ttk.Button(restore,text=label,command=cmd).grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=2)
        restore.columnconfigure(0,weight=1);restore.columnconfigure(1,weight=1)
        self.tabs=ttk.Notebook(right);self.tabs.pack(fill='both',expand=True)
        for section,fields in SECTIONS.items():
            tab=ttk.Frame(self.tabs);self.tabs.add(tab,text=section);self._build_section(tab,fields)
        boost=ttk.Frame(self.tabs);self.tabs.add(boost,text='Global Boost & Profiles');self._build_boost(boost)
        sprites=ttk.Frame(self.tabs);self.tabs.add(sprites,text='Sprites & Bestiary')
        self.sprite_assets=None
        if self.export_root and self.working_overlays:
            self.sprite_assets=LinkedAssetPanel(sprites,self.export_root,self.working_overlays,('Monster Sprites','Bestiary Assets'),title='Monster Battle Sprites & Bestiary Images',on_status=self.on_status,on_dirty=self.on_dirty)
            self.sprite_assets.pack(fill='both',expand=True)
        else:
            ttk.Label(sprites,text='MagiciteExport asset catalog is unavailable.').pack(padx=12,pady=12)
    def _build_section(self,parent,fields):
        f=ttk.Frame(parent,padding=14);f.pack(fill='both',expand=True)
        for row,field in enumerate(fields):
            if field not in self.document.fieldnames:continue
            ttk.Label(f,text=friendly_label(field)).grid(row=row,column=0,sticky='w',padx=5,pady=6);v=tk.StringVar();v.trace_add('write',lambda *_a,key=field:self.changed(key));self.vars[field]=v
            if field=='boss':w=ttk.Combobox(f,textvariable=v,state='readonly',values=['0','1'],width=12)
            else:w=ttk.Entry(f,textvariable=v)
            w.grid(row=row,column=1,sticky='ew',padx=5,pady=6)
        f.columnconfigure(1,weight=1)
    def _build_boost(self,parent):
        outer=ttk.Frame(parent,padding=14);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Global Monster Boost',style='Heading.TLabel').grid(row=0,column=0,columnspan=4,sticky='w')
        ttk.Label(outer,text='Profiles are generated from the untouched original export by default, so Monster++ never accidentally stacks on Monster+.',style='Muted.TLabel',wraplength=850).grid(row=1,column=0,columnspan=4,sticky='w',pady=(4,10))
        self.baseline=tk.StringVar(value='Original game data');ttk.Label(outer,text='Baseline').grid(row=2,column=0,sticky='w');ttk.Combobox(outer,textvariable=self.baseline,state='readonly',values=['Original game data','Current project monsters'],width=24).grid(row=2,column=1,sticky='w')
        self.include_normal=tk.BooleanVar(value=True);self.include_bosses=tk.BooleanVar(value=True);self.preserve_zero=tk.BooleanVar(value=True)
        ttk.Checkbutton(outer,text='Include normal monsters',variable=self.include_normal).grid(row=2,column=2,sticky='w');ttk.Checkbutton(outer,text='Include bosses',variable=self.include_bosses).grid(row=2,column=3,sticky='w')
        ttk.Checkbutton(outer,text='Preserve zero values',variable=self.preserve_zero).grid(row=3,column=2,sticky='w')
        self.boost_vars={};row=4
        labels=[('hp','HP'),('attack','Attack'),('defense','Defense'),('agility','Agility / Speed'),('magic','Magic'),('ability_attack','Magic Attack'),('ability_defense','Magic Defense'),('accuracy_rate','Accuracy'),('evasion_rate','Evasion'),('magic_evasion_rate','Magic Evasion'),('exp','EXP'),('gill','Gil'),('drop_rate','Drop Rate')]
        for i,(field,label) in enumerate(labels):
            r=row+i//2;c=(i%2)*2;ttk.Label(outer,text=label+' ×').grid(row=r,column=c,sticky='w',padx=(0,5),pady=3);v=tk.StringVar(value='1.0');self.boost_vars[field]=v;ttk.Entry(outer,textvariable=v,width=10).grid(row=r,column=c+1,sticky='w',pady=3)
        actions=ttk.Frame(outer);actions.grid(row=row+7,column=0,columnspan=4,sticky='ew',pady=(12,6))
        ttk.Button(actions,text='Preview Changes',command=self.preview_boost).pack(side='left');ttk.Button(actions,text='Apply to Active Monsters',command=self.apply_boost).pack(side='left',padx=5);ttk.Button(actions,text='Save Custom Profile',command=self.save_custom_profile).pack(side='left')
        presets=ttk.LabelFrame(outer,text='Generate named profiles from baseline',padding=8);presets.grid(row=row+8,column=0,columnspan=4,sticky='ew')
        for name in PRESETS:ttk.Button(presets,text=f'Generate {name}',command=lambda n=name:self.generate_preset(n)).pack(side='left',padx=4)
        self.profile_name=tk.StringVar(value='Monster+');ttk.Entry(presets,textvariable=self.profile_name,width=18).pack(side='left',padx=(15,4));ttk.Button(presets,text='Activate Profile',command=self.activate_named_profile).pack(side='left')
        self.preview=tk.Text(outer,height=12,bg=DARK['panel'],fg=DARK['fg'],relief='flat',wrap='none');self.preview.grid(row=row+9,column=0,columnspan=4,sticky='nsew',pady=(8,0));outer.rowconfigure(row+9,weight=1);outer.columnconfigure(3,weight=1)
    def name(self,row):return self.messages.display(row.get('mes_id_name','')) or row.get('mes_id_name','')
    def refresh(self):
        q=self.search.get().strip().lower();self.indices=[];self.list.delete(0,'end')
        for i,row in enumerate(self.document.rows):
            if not q or q in (' '.join(row.values())+' '+self.name(row)).lower():self.indices.append(i);self.list.insert('end',f"{row.get('id','')} — {self.name(row)}")
    def _selected(self,_=None):
        s=self.list.curselection();
        if s:self.select(s[0])
    def select(self,v):
        self.current=self.indices[v];row=self.document.rows[self.current];self.loading=True
        for f,x in self.vars.items():x.set(row.get(f,''))
        self.loading=False
        if self.sprite_assets:
            self.sprite_assets.set_entity(self.name(row), [row.get('id',''), row.get('monster_asset_id',''), row.get('mes_id_name','')])
        self.refresh_monster_preview()
        self.update_inspector()
    def open_sprite_tab(self):
        try:
            self.tabs.select(self.tabs.tabs()[-1])
        except Exception:
            pass

    def _monster_preview_path(self):
        if self.current is None or not self.export_root:
            return None
        row=self.document.rows[self.current]
        raw=str(row.get('monster_asset_id','') or row.get('id','')).strip()
        try: asset_id=f"{int(raw):03d}"
        except ValueError: asset_id=raw.zfill(3)
        group=f'mn_ff1_{asset_id}'
        layers=[]
        if self.working_overlays:
            overlay=Path(self.working_overlays)/group
            layers.append((overlay, 'WORKING EDIT'))
        export_root=Path(self.export_root)
        try:
            active_mod=export_root.parent/'Magicite'/'Crystal Legacy'/group
            layers.append((active_mod, 'ACTIVE MOD'))
        except Exception:
            pass
        layers.append((export_root/group, 'ORIGINAL'))
        for layer_root, label in layers:
            if not layer_root.exists():
                continue
            candidates=sorted(p for p in layer_root.rglob('*.png') if 'shadow' not in p.name.lower())
            preferred=[p for p in candidates if p.stem.lower().endswith('_c00')]
            chosen=(preferred or candidates or [None])[0]
            if chosen:
                self._monster_preview_layer=label
                return chosen
        self._monster_preview_layer='ORIGINAL'
        return None

    def refresh_monster_preview(self):
        if not hasattr(self,'monster_preview'): return
        path=self._monster_preview_path()
        if not path:
            self.monster_preview.configure(image='',text='No linked sprite found');return
        try:
            with Image.open(path) as opened:
                img=opened.convert('RGBA')
                scale=max(1,min(7,165//max(img.width,img.height)))
                img=img.resize((img.width*scale,img.height*scale),Image.Resampling.NEAREST)
            self.monster_preview_ref=ImageTk.PhotoImage(img)
            state=getattr(self,'_monster_preview_layer','ORIGINAL')
            self.monster_preview.configure(image=self.monster_preview_ref,text=f'\n{state}',compound='top')
        except Exception as exc:
            self.monster_preview.configure(image='',text=f'Preview unavailable\n{exc}')

    def changed(self,field):
        if self.loading or self.current is None:return
        self.document.rows[self.current][field]=self.vars[field].get();self.on_dirty(True);self.update_inspector()
    def update_inspector(self):
        if self.current is None:return
        r=self.document.rows[self.current];self.on_inspect('Monster Record',{'ID':r.get('id',''),'Name':self.name(r),'Level':r.get('lv',''),'HP / MP':f"{r.get('hp','')} / {r.get('mp','')}",'Attack / Defense':f"{r.get('attack','')} / {r.get('defense','')}",'EXP / Gil':f"{r.get('exp','')} / {r.get('gill','')}",'Drop':f"{r.get('drop_content_id1','')} × {r.get('drop_content_id1_value','')}",'AI script':r.get('script_id',''),'Asset':r.get('monster_asset_id','')})
    def duplicate(self):
        if self.current is None:return
        row=dict(self.document.rows[self.current]);ids=[]
        for r in self.document.rows:
            try:ids.append(int(r.get('id','0')))
            except ValueError:pass
        row['id']=str(max(ids,default=0)+1);self.document.rows.append(row);self.on_dirty(True);self.refresh()
    def delete(self):
        if self.current is not None and messagebox.askyesno('Delete monster',f"Delete {self.name(self.document.rows[self.current])}?",parent=self):del self.document.rows[self.current];self.current=None;self.on_dirty(True);self.refresh()
    def create_backup(self):
        folder=self.project_root/'Backups'/'Monsters';folder.mkdir(parents=True,exist_ok=True);dest=folder/f"monster-{datetime.datetime.now():%Y%m%d-%H%M%S}.csv";self.document.save();shutil.copy2(self.document.path,dest);self.on_status('PASS',f'Created monster backup: {dest}')
    def undo_unsaved(self):
        from crystal_legacy_studio.editors.csv_document import CsvDocument
        fresh=CsvDocument.load(self.document.path,source_path=self.document.source_path);self.document.rows=fresh.rows;self.current=None;self.on_dirty(False);self.refresh();self.on_status('PASS','Discarded unsaved monster changes.')
    def _original_doc(self):
        from crystal_legacy_studio.editors.csv_document import CsvDocument
        if not self.document.source_path or not Path(self.document.source_path).exists():raise FileNotFoundError('Original monster.csv source is unavailable.')
        return CsvDocument.load(Path(self.document.source_path))
    def restore_selected(self):
        if self.current is None:return
        mid=str(self.document.rows[self.current].get('id',''));orig=next((r for r in self._original_doc().rows if str(r.get('id',''))==mid),None)
        if not orig:messagebox.showwarning('Restore monster',f'Monster ID {mid} was not found in original data.',parent=self);return
        self.document.rows[self.current]=dict(orig);self.on_dirty(True);self.select(self.indices.index(self.current));self.on_status('PASS',f'Restored {self.name(orig)} from original data.')
    def restore_all(self):
        if not messagebox.askyesno('Restore all monsters','Replace every active monster row with the untouched original game table?',parent=self):return
        self.create_backup();orig=self._original_doc();self.document.rows=[dict(r) for r in orig.rows];self.current=None;self.on_dirty(True);self.refresh();self.on_status('PASS','Restored all monster defaults from the original export.')

    def import_original_table(self):
        if not messagebox.askyesno('Import original monster table','Replace the active project monster.csv with the complete untouched MagiciteExport table and save it now? A backup will be created first.',parent=self):return
        self.create_backup();orig=self._original_doc();self.document.rows=[dict(r) for r in orig.rows];self.document.fieldnames=list(orig.fieldnames);self.document.save();self.current=None;self.on_dirty(False);self.refresh();self.on_status('PASS','Imported and saved the complete original monster.csv table.')

    def _multipliers(self):
        out={}
        for f,v in self.boost_vars.items():
            try:out[f]=float(v.get())
            except ValueError:raise ValueError(f'{friendly_label(f)} multiplier is not numeric.')
        return out
    def _baseline_rows(self):return self._original_doc().rows if self.baseline.get().startswith('Original') else self.document.rows
    def _calculate(self,multipliers=None):
        return boosted_rows(self._baseline_rows(),multipliers or self._multipliers(),include_bosses=self.include_bosses.get(),include_normal=self.include_normal.get(),preserve_zero=self.preserve_zero.get())
    def preview_boost(self):
        try:rows,result=self._calculate()
        except Exception as e:messagebox.showerror('Monster boost',str(e),parent=self);return
        base=self._baseline_rows();lines=[f'Processed {result.processed} monsters; {result.changed} would change.','']
        for old,new in zip(base,rows):
            diffs=[f"{friendly_label(f)} {old.get(f,'')}→{new.get(f,'')}" for f in BOOST_FIELDS if old.get(f)!=new.get(f)]
            if diffs:lines.append(f"{self.name(old)}: "+', '.join(diffs[:8]))
            if len(lines)>=28:lines.append('... preview truncated ...');break
        self.preview.delete('1.0','end');self.preview.insert('end','\n'.join(lines));self.on_status('PASS',f'Previewed global boost for {result.processed} monsters.')
    def apply_boost(self):
        try:rows,result=self._calculate()
        except Exception as e:messagebox.showerror('Monster boost',str(e),parent=self);return
        if not messagebox.askyesno('Apply global boost',f'Apply changes to {result.changed} active monsters? A backup will be created first.',parent=self):return
        self.create_backup();self.document.rows=rows;self.current=None;self.on_dirty(True);self.refresh();self.on_status('PASS',f'Applied global boost to {result.changed} monsters.')
    def _save_profile(self,name,multipliers):
        rows,result=self._calculate(multipliers);path=save_profile(self.project_root,name,self.document.fieldnames,rows,{'baseline':self.baseline.get(),'multipliers':multipliers,'include_normal':self.include_normal.get(),'include_bosses':self.include_bosses.get(),'preserve_zero':self.preserve_zero.get()});self.on_status('PASS',f'Saved {name} profile with {result.changed} boosted monsters: {path}');return path
    def save_custom_profile(self):
        name=simpledialog.askstring('Custom monster profile','Profile name:',parent=self)
        if name:
            try:self._save_profile(name,self._multipliers())
            except Exception as e:messagebox.showerror('Monster profile',str(e),parent=self)
    def generate_preset(self,name):
        try:
            for f,v in self.boost_vars.items():v.set(str(PRESETS[name].get(f,1.0)))
            self._save_profile(name,PRESETS[name]);self.profile_name.set(name)
        except Exception as e:messagebox.showerror('Monster profile',str(e),parent=self)
    def activate_named_profile(self):
        name=self.profile_name.get().strip();path=self.project_root/'Profiles'/'Monsters'/name/'monster.csv'
        if not path.exists():messagebox.showwarning('Activate profile',f'Profile not found: {path}',parent=self);return
        self.create_backup();activate_profile(path,self.document.path)
        from crystal_legacy_studio.editors.csv_document import CsvDocument
        fresh=CsvDocument.load(self.document.path,source_path=self.document.source_path);self.document.rows=fresh.rows;self.current=None;self.on_dirty(True);self.refresh();self.on_status('PASS',f'Activated monster profile: {name}')
    def validate(self):
        issues=self.document.validate()
        for n,r in enumerate(self.document.rows,start=2):
            for f in ('lv','hp','mp','attack','defense','exp','gill'):
                if f not in r:continue
                try:
                    if int(r.get(f,'0') or 0)<0:issues.append(f'Row {n}: {friendly_label(f)} cannot be negative.')
                except ValueError:issues.append(f'Row {n}: {friendly_label(f)} is not numeric.')
        self.on_status('PASS' if not issues else 'ERROR','Monster data passed validation.' if not issues else f'{len(issues)} monster issue(s).')
        if issues:messagebox.showwarning('Monster validation','\n'.join(issues[:20]),parent=self)
        return issues
    def save(self):
        self.document.save();self.messages.save();self.on_dirty(False);self.on_status('PASS','Saved monster.csv and monster assets.')
        if self.on_saved:self.on_saved()
        return True
    def save_changes(self):return self.save()
