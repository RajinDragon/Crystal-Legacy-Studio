from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from crystal_legacy_studio.assets.game_bundles import GameBundleCatalog, DirectGameFileManager

class BundleWorkbench(ttk.Frame):
    def __init__(self,parent,layout,on_status=lambda *_:None,on_inspect=lambda *_:None):
        super().__init__(parent,padding=12); self.layout=layout; self.on_status=on_status; self.on_inspect=on_inspect
        self.catalog=GameBundleCatalog(layout.game_root); self.manager=DirectGameFileManager(layout.game_root,layout.backup_dir,layout.working_root/'DirectGameFiles')
        self.records=[]; self.filtered=[]; self.selected=None
        top=ttk.Frame(self); top.pack(fill='x'); ttk.Label(top,text='Direct Game Bundle Workbench',style='Title.TLabel').pack(side='left')
        ttk.Button(top,text='Rescan',command=self.scan).pack(side='right',padx=3)
        ttk.Button(top,text='Export Inventory',command=self.export_inventory).pack(side='right',padx=3)
        ttk.Label(self,text='Experimental direct-file mode. Studio always backs up the untouched live file before replacement. CSV/gameplay data remains on the safe Magicite/BepInEx path until a bundle is proven rebuildable.',style='Muted.TLabel',wraplength=900).pack(fill='x',pady=(4,10))
        filters=ttk.Frame(self); filters.pack(fill='x'); ttk.Label(filters,text='Family').pack(side='left')
        self.family=tk.StringVar(value='All'); self.combo=ttk.Combobox(filters,textvariable=self.family,state='readonly',width=30); self.combo.pack(side='left',padx=5); self.combo.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        ttk.Label(filters,text='Search').pack(side='left',padx=(10,0)); self.search=tk.StringVar(); e=ttk.Entry(filters,textvariable=self.search); e.pack(side='left',fill='x',expand=True,padx=5); self.search.trace_add('write',lambda *_:self.refresh())
        self.tree=ttk.Treeview(self,columns=('family','subject','size','unity'),show='headings');
        for c,w in [('family',180),('subject',220),('size',90),('unity',180)]: self.tree.heading(c,text=c.title()); self.tree.column(c,width=w,anchor='w')
        self.tree.pack(fill='both',expand=True,pady=8); self.tree.bind('<<TreeviewSelect>>',self.select)
        actions=ttk.Frame(self); actions.pack(fill='x'); ttk.Button(actions,text='Stage Replacement…',command=self.stage).pack(side='left'); ttk.Button(actions,text='Deploy Selected (Backup First)…',command=self.deploy).pack(side='left',padx=5); ttk.Button(actions,text='Open Live Folder',command=self.open_folder).pack(side='left')
        self.detail=tk.Text(self,height=7,wrap='word'); self.detail.pack(fill='x',pady=(8,0)); self.detail.configure(state='disabled')
        self.scan()
    def scan(self):
        self.records=self.catalog.scan(); families=['All']+sorted({r.family for r in self.records}); self.combo['values']=families; self.refresh(); self.on_status('PASS',f'Direct game-file inventory mapped {len(self.records):,} bundle/asset/support files.')
    def refresh(self):
        fam=self.family.get(); q=self.search.get().lower().strip(); self.filtered=[r for r in self.records if (fam=='All' or r.family==fam) and (not q or q in (r.filename+' '+r.relative_path+' '+r.subject).lower())]
        self.tree.delete(*self.tree.get_children())
        for i,r in enumerate(self.filtered): self.tree.insert('', 'end', iid=str(i), values=(r.family,r.subject,f'{r.size_bytes:,}',r.unity_version or r.unity_signature))
    def select(self,_=None):
        sel=self.tree.selection();
        if not sel:return
        self.selected=self.filtered[int(sel[0])]; r=self.selected
        text=f'{r.filename}\n{r.relative_path}\nFamily: {r.family}\nSubject: {r.subject}\nType: {r.file_kind}\nUnity: {r.unity_signature} {r.unity_version}\nSHA-256: {r.sha256}'
        self.detail.configure(state='normal'); self.detail.delete('1.0','end'); self.detail.insert('1.0',text); self.detail.configure(state='disabled')
        self.on_inspect('Game Bundle',{'Family':r.family,'Subject':r.subject,'Live file':r.source_path,'Unity':f'{r.unity_signature} {r.unity_version}','SHA-256':r.sha256})
    def stage(self):
        if not self.selected:return
        p=filedialog.askopenfilename(parent=self,title='Select replacement game file');
        if not p:return
        try:
            target=self.manager.stage_replacement(self.selected,Path(p)); self.on_status('PASS',f'Staged direct replacement: {target}'); messagebox.showinfo('Staged',f'Staged safely at:\n{target}\n\nThe live game file has not been changed.',parent=self)
        except Exception as e: messagebox.showerror('Rejected',str(e),parent=self); self.on_status('ERROR',str(e))
    def staged_path(self): return self.layout.working_root/'DirectGameFiles'/self.selected.relative_path if self.selected else None
    def deploy(self):
        if not self.selected:return
        staged=self.staged_path()
        if not staged or not staged.is_file(): messagebox.showerror('No staged file','Stage a replacement first.',parent=self); return
        if not messagebox.askyesno('Direct game-file replacement','This changes an original installed game file. Studio will first create a byte-for-byte backup and verify the write. Continue?',parent=self): return
        try:
            live,backup=self.manager.deploy_one(self.selected,staged); self.on_status('WRITE',str(live)); self.on_status('PASS',f'Original backed up to {backup}'); messagebox.showinfo('Deployed',f'Written and verified:\n{live}\n\nBackup:\n{backup}',parent=self)
        except Exception as e: messagebox.showerror('Deployment failed',str(e),parent=self); self.on_status('ERROR',str(e))
    def export_inventory(self):
        path=self.catalog.write_manifest(self.layout.metadata_dir/'direct-game-file-inventory.json'); self.on_status('PASS',f'Bundle inventory saved: {path}'); messagebox.showinfo('Inventory',str(path),parent=self)
    def open_folder(self):
        if self.selected:
            import os; os.startfile(str((self.layout.game_root/self.selected.relative_path).parent))
