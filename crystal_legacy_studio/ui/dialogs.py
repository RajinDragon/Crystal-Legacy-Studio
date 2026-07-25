import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from crystal_legacy_studio.project.models import ProjectService
from crystal_legacy_studio.packaging.builder import PackageBuilder,PackageOptions
from crystal_legacy_studio.game.detection import GameDetector

class SetupWizard(tk.Toplevel):
    """Manage one saved installation path for each Pixel Remaster game."""
    def __init__(self,parent,settings,on_complete):
        super().__init__(parent); self.title('Crystal Legacy Studio — Game Installations'); self.geometry('820x590'); self.transient(parent); self.grab_set()
        self.settings=settings; self.on_complete=on_complete; self.detector=GameDetector()
        from crystal_legacy_studio.game.profiles import GAME_PROFILES, PROFILE_BY_DISPLAY, get_profile
        self.profiles=GAME_PROFILES; self.profile_by_display=PROFILE_BY_DISPLAY
        active=get_profile(settings.active_game_profile)
        self.profile=tk.StringVar(value=active.display_name)
        self.game=tk.StringVar(value=settings.game_installations.get(active.profile_id, settings.game_root))
        f=ttk.Frame(self,padding=22); f.pack(fill='both',expand=True)
        ttk.Label(f,text='Pixel Remaster Game Installations',style='Title.TLabel').pack(anchor='w')
        ttk.Label(f,text='Save a separate game-root path for Final Fantasy I–VI. Only the active game is shown in Project Explorer.',style='Muted.TLabel').pack(anchor='w',pady=(2,18))
        top=ttk.LabelFrame(f,text='Active game profile',padding=14); top.pack(fill='x',pady=6)
        row=ttk.Frame(top); row.pack(fill='x')
        ttk.Label(row,text='Game').pack(side='left')
        combo=ttk.Combobox(row,textvariable=self.profile,state='readonly',values=[p.display_name for p in self.profiles],width=38)
        combo.pack(side='left',padx=(10,0)); combo.bind('<<ComboboxSelected>>',self.profile_changed)
        g=ttk.LabelFrame(f,text='Selected game root',padding=14); g.pack(fill='x',pady=6)
        r=ttk.Frame(g); r.pack(fill='x'); ttk.Entry(r,textvariable=self.game).pack(side='left',fill='x',expand=True)
        ttk.Button(r,text='Browse…',command=self.browse_game).pack(side='left',padx=6); ttk.Button(r,text='Auto Detect',command=self.auto).pack(side='left')
        self.diag=tk.Text(g,height=10,relief='flat'); self.diag.pack(fill='x',pady=(10,0))
        self.saved=tk.Text(f,height=7,relief='flat'); self.saved.pack(fill='x',pady=(10,0))
        ttk.Label(f,text='Required for each configured game: game executable, BepInEx, StreamingAssets\\Magicite, and StreamingAssets\\MagiciteExport.',style='Muted.TLabel',wraplength=760).pack(anchor='w',pady=10)
        b=ttk.Frame(f); b.pack(side='bottom',fill='x',pady=(12,0)); ttk.Button(b,text='Cancel',command=self.destroy).pack(side='right'); ttk.Button(b,text='Save and Use This Game',command=self.finish).pack(side='right',padx=8)
        self.refresh()
    def current_profile(self): return self.profile_by_display[self.profile.get()]
    def profile_changed(self,_event=None):
        p=self.current_profile(); self.game.set(self.settings.game_installations.get(p.profile_id,'')); self.refresh()
    def browse_game(self):
        p=self.current_profile(); x=filedialog.askdirectory(parent=self,title=f'Select {p.display_name} game root',initialdir=self.game.get() or None)
        if x:self.game.set(x); self.refresh()
    def auto(self):
        p=self.current_profile(); x=self.detector.auto_detect(p.profile_id)
        if x:self.game.set(str(x.root)); self.refresh()
        else:messagebox.showinfo('Auto Detect',f'A complete {p.display_name} + BepInEx + Magicite installation was not found automatically.',parent=self)
    def refresh(self):
        p=self.current_profile(); self.diag.config(state='normal'); self.diag.delete('1.0','end')
        x=self.detector.inspect(Path(self.game.get()),p.profile_id) if self.game.get().strip() else None
        rows=[('Game executable',bool(x and x.executable)),('Game data folder',bool(x and x.data_dir)),('StreamingAssets',bool(x and x.streaming_assets)),('StreamingAssets\\Magicite',bool(x and x.magicite_dir)),('StreamingAssets\\MagiciteExport (read-only)',bool(x and x.magicite_export)),('BepInEx',bool(x and x.bepinex_dir))]
        for n,ok in rows:self.diag.insert('end',f"{'✓' if ok else '○'} {n}\n")
        self.diag.config(state='disabled')
        self.saved.config(state='normal'); self.saved.delete('1.0','end'); self.saved.insert('end','Saved installations:\n')
        for profile in self.profiles:
            root=self.settings.game_installations.get(profile.profile_id,'Not configured')
            active='  [ACTIVE]' if profile.profile_id==self.settings.active_game_profile else ''
            self.saved.insert('end',f'{profile.roman}: {root}{active}\n')
        self.saved.config(state='disabled')
    def finish(self):
        p=self.current_profile(); raw=self.game.get().strip()
        if not raw:messagebox.showerror('Setup incomplete','Browse to the game root first.',parent=self); return
        x=self.detector.inspect(Path(raw),p.profile_id)
        if not x.is_valid_crystal_legacy_root:
            messagebox.showerror('Setup incomplete',f'Select the {p.display_name} root containing its executable, BepInEx, StreamingAssets\\Magicite, and StreamingAssets\\MagiciteExport.',parent=self); return
        self.settings.game_installations[p.profile_id]=str(x.root); self.settings.active_game_profile=p.profile_id
        self.settings.game_root=str(x.root); self.settings.workspace_root=str(x.root/'BepInEx'/'Crystal Legacy'/'Working'); self.settings.setup_completed=True
        self.destroy(); self.on_complete(x)

class NewProjectDialog(tk.Toplevel):
    def __init__(self,parent,settings,on_created):
        super().__init__(parent); self.title('Initialize Crystal Legacy Project'); self.transient(parent); self.grab_set(); self.settings=settings; self.on_created=on_created
        from crystal_legacy_studio.game.profiles import get_profile
        self.name=tk.StringVar(value='Crystal Legacy'); self.author=tk.StringVar(value='RajinDragon'); self.root=tk.StringVar(value=settings.game_root)
        self.profile_id=settings.active_game_profile; self.profile=get_profile(self.profile_id)
        f=ttk.Frame(self,padding=18); f.grid(sticky='nsew'); f.columnconfigure(1,weight=1)
        for i,(n,v) in enumerate((('Project name',self.name),('Author',self.author))):
            ttk.Label(f,text=n).grid(row=i,column=0,sticky='w',pady=6); ttk.Entry(f,textvariable=v,width=60).grid(row=i,column=1,columnspan=2,sticky='ew',padx=10,pady=6)
        ttk.Label(f,text='Game profile').grid(row=2,column=0,sticky='w',pady=6); ttk.Label(f,text=self.profile.display_name).grid(row=2,column=1,sticky='w',padx=10)
        ttk.Label(f,text='Game root').grid(row=3,column=0,sticky='w',pady=6); ttk.Entry(f,textvariable=self.root,width=60).grid(row=3,column=1,sticky='ew',padx=10,pady=6); ttk.Button(f,text='Browse…',command=self.browse).grid(row=3,column=2,pady=6)
        ttk.Label(f,text='Working files: BepInEx\\Crystal Legacy\\Working\nPackages: Crystal Legacy\\Import and Crystal Legacy\\Export',style='Muted.TLabel').grid(row=4,column=0,columnspan=3,sticky='w',pady=8)
        b=ttk.Frame(f); b.grid(row=5,column=0,columnspan=3,sticky='e',pady=10); ttk.Button(b,text='Cancel',command=self.destroy).pack(side='right'); ttk.Button(b,text='Initialize Project',command=self.create).pack(side='right',padx=8)
    def browse(self):
        x=filedialog.askdirectory(parent=self,title=f'Select {self.profile.display_name} game root',initialdir=self.root.get() or None)
        if x:self.root.set(x)
    def create(self):
        try:
            root=Path(self.root.get().strip()); installation=GameDetector().inspect(root,self.profile_id)
            if not installation.is_valid_crystal_legacy_root: raise RuntimeError(f'Select a complete {self.profile.display_name} root containing BepInEx, Magicite, and MagiciteExport.')
            self.settings.game_installations[self.profile_id]=str(installation.root); self.settings.game_root=str(installation.root)
            p=ProjectService().create(installation.root,self.name.get(),self.author.get(),game_profile=self.profile_id); self.destroy(); self.on_created(p)
        except Exception as e: messagebox.showerror('Project creation failed',str(e),parent=self)
class ExportPackageDialog(tk.Toplevel):
    def __init__(self,parent,project,on_complete):
        super().__init__(parent); self.title('Export / Share Package'); self.transient(parent); self.grab_set(); self.project=project; self.on_complete=on_complete
        self.titlev=tk.StringVar(value=project.manifest.name); self.author=tk.StringVar(value=project.manifest.author); self.version=tk.StringVar(value=project.manifest.version); self.type=tk.StringVar(value='CompleteMod'); self.desc=tk.StringVar(); self.newsave=tk.BooleanVar(); self.runtime=tk.BooleanVar(); self.output=tk.StringVar(value=str(project.layout.export_dir))
        f=ttk.Frame(self,padding=18); f.grid()
        for i,(n,v) in enumerate((('Package title',self.titlev),('Author',self.author),('Version',self.version),('Description',self.desc),('Output folder',self.output))): ttk.Label(f,text=n).grid(row=i,column=0,sticky='w',pady=5); ttk.Entry(f,textvariable=v,width=58).grid(row=i,column=1,padx=10,pady=5)
        ttk.Button(f,text='Browse…',command=self.browse).grid(row=4,column=2); ttk.Label(f,text='Package type').grid(row=5,column=0,sticky='w'); ttk.Combobox(f,textvariable=self.type,state='readonly',values=['CompleteMod','ProjectPackage','ContentPack','RandomizerSeed','RulesetPackage','AssetPack']).grid(row=5,column=1,sticky='ew',padx=10)
        ttk.Checkbutton(f,text='Requires a new save',variable=self.newsave).grid(row=6,column=1,sticky='w'); ttk.Checkbutton(f,text='Includes runtime plugin',variable=self.runtime).grid(row=7,column=1,sticky='w')
        ttk.Label(f,text='Package identity, keys, checksums, signature, and verification are generated automatically.',wraplength=520).grid(row=8,column=0,columnspan=3,sticky='w',pady=12)
        b=ttk.Frame(f); b.grid(row=9,column=0,columnspan=3,sticky='e'); ttk.Button(b,text='Cancel',command=self.destroy).pack(side='right'); ttk.Button(b,text='Build Verified Package',command=self.build).pack(side='right',padx=8)
    def browse(self):
        x=filedialog.askdirectory(parent=self); self.output.set(x or self.output.get())
    def build(self):
        try:
            r=PackageBuilder().build(self.project,PackageOptions(self.titlev.get(),self.author.get(),self.version.get(),self.desc.get(),self.type.get(),self.newsave.get(),self.runtime.get()),Path(self.output.get())); self.destroy(); self.on_complete(r)
        except Exception as e: messagebox.showerror('Package build failed',str(e),parent=self)
