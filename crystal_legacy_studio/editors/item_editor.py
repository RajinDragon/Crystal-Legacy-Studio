from __future__ import annotations
import json, tkinter as tk
from tkinter import ttk, messagebox
from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.core.atomic import atomic_write_text

KEY_COUNT=17
VEHICLES={'Canoe':17,'Ship':-1,'Airship':-2}
class ItemDesigner(ttk.Frame):
    def __init__(self,parent,document,messages,project_root,on_dirty,on_status,on_inspect):
        super().__init__(parent);self.document=document;self.messages=messages;self.project_root=project_root;self.on_dirty=on_dirty;self.on_status=on_status;self.on_inspect=on_inspect;self.current=None;self.indices=[];self.vars={};self.loading=False
        self.config_path=project_root/'Data'/'Runtime'/'starting_world_state.json';self.start_state=self._load_state();self._build();self.refresh()
    def _load_state(self):
        try:return json.loads(self.config_path.read_text(encoding='utf-8'))
        except Exception:return {'key_items':{},'vehicles':{'Canoe':False,'Ship':False,'Airship':False},'status':'research-staged'}
    def _build(self):
        h=ttk.Frame(self,padding=12);h.pack(fill='x');ttk.Label(h,text='Item & Key Item Designer',style='Title.TLabel').pack(side='left');ttk.Button(h,text='Save',command=self.save).pack(side='right')
        nb=ttk.Notebook(self);nb.pack(fill='both',expand=True,padx=10,pady=10);items=ttk.Frame(nb,padding=8);keys=ttk.Frame(nb,padding=8);world=ttk.Frame(nb,padding=12);nb.add(items,text='Consumable Items');nb.add(keys,text='Key Items');nb.add(world,text='Starting World State')
        p=ttk.Panedwindow(items,orient='horizontal');p.pack(fill='both',expand=True);left=ttk.Frame(p);right=ttk.Frame(p);p.add(left,weight=1);p.add(right,weight=3)
        self.search=tk.StringVar();self.search.trace_add('write',lambda *_:self.refresh());ttk.Entry(left,textvariable=self.search).pack(fill='x');self.list=tk.Listbox(left,bg=DARK['panel'],fg=DARK['fg'],selectbackground=DARK['selection'],relief='flat',exportselection=False);self.list.pack(fill='both',expand=True,pady=6);self.list.bind('<<ListboxSelect>>',self._selected)
        canvas=tk.Canvas(right,bg=DARK['panel'],highlightthickness=0);scroll=ttk.Scrollbar(right,orient='vertical',command=canvas.yview);form=ttk.Frame(canvas,padding=8);form.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.create_window((0,0),window=form,anchor='nw');canvas.configure(yscrollcommand=scroll.set);canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        for n,f in enumerate(self.document.fieldnames):ttk.Label(form,text=f.replace('_',' ').title()).grid(row=n,column=0,sticky='w',padx=4,pady=3);v=tk.StringVar();v.trace_add('write',lambda *_a,k=f:self.changed(k));self.vars[f]=v;ttk.Entry(form,textvariable=v).grid(row=n,column=1,sticky='ew',padx=4,pady=3)
        form.columnconfigure(1,weight=1)
        ttk.Label(keys,text='Key items are message-backed quest/world-state objects, not normal item.csv rows.',style='Muted.TLabel',wraplength=700).pack(anchor='w',pady=(0,8));self.key_tree=ttk.Treeview(keys,columns=('start',),show='tree headings');self.key_tree.heading('#0',text='Key Item');self.key_tree.heading('start',text='Owned');self.key_tree.pack(fill='both',expand=True);self.key_tree.bind('<Double-1>',self.toggle_key);self.refresh_keys()
        ttk.Label(world,text='EXPERIMENTAL — these switches currently save a manifest only. They do not yet spawn the ship, canoe, or airship in-game. FF1PR uses runtime release flags (Ship 516, Canoe 517, Airship 518), and a verified runtime hook is still required.',style='Muted.TLabel',wraplength=760).pack(anchor='w',pady=(0,12));self.vehicle_vars={}
        for name in ('Canoe','Ship','Airship'):
            v=tk.BooleanVar(value=bool(self.start_state.get('vehicles',{}).get(name,False)));self.vehicle_vars[name]=v;ttk.Checkbutton(world,text=f'Start with {name}',variable=v,command=self.world_changed).pack(anchor='w',pady=4)
        ttk.Button(world,text='Save Starting World Manifest',command=self.save_state).pack(anchor='w',pady=12)
    def item_name(self,r):
        key=f"MSG_ITEM_NAME_{int(r.get('id','0') or 0):02d}";name=self.messages.display(key);return name if name and name!=key else f"Item {r.get('id','')} (unlocalized/placeholder)"
    def refresh(self):
        q=self.search.get().lower().strip();self.indices=[];self.list.delete(0,'end')
        for i,r in enumerate(self.document.rows):
            text=f"{r.get('id','')} {self.item_name(r)}"
            if not q or q in text.lower():self.indices.append(i);self.list.insert('end',f"{r.get('id','')} — {self.item_name(r)}")
    def _selected(self,_=None):
        s=self.list.curselection();
        if s:self.select(s[0])
    def select(self,v):
        self.current=self.indices[v];r=self.document.rows[self.current];self.loading=True
        for k,x in self.vars.items():x.set(r.get(k,''))
        self.loading=False;self.on_inspect('Item',{'ID':r.get('id',''),'Name':self.item_name(r),'Type':r.get('type_id',''),'Buy':r.get('buy',''),'Sell':r.get('sell','')})
    def changed(self,k):
        if self.loading or self.current is None:return
        self.document.rows[self.current][k]=self.vars[k].get();self.on_dirty(True)
    def refresh_keys(self):
        for x in self.key_tree.get_children():self.key_tree.delete(x)
        owned=self.start_state.setdefault('key_items',{})
        for i in range(1,KEY_COUNT+1):
            key=f'MSG_KEY_NAME_{i:02d}';name=self.messages.display(key);self.key_tree.insert('', 'end', iid=str(i), text=name if name!=key else f'Key Item {i}', values=('☑' if owned.get(str(i),False) else '☐',))
    def toggle_key(self,_=None):
        s=self.key_tree.selection();
        if not s:return
        k=s[0];d=self.start_state.setdefault('key_items',{});d[k]=not d.get(k,False);self.on_dirty(True);self.refresh_keys()
    def world_changed(self):
        self.start_state['vehicles']={k:v.get() for k,v in self.vehicle_vars.items()};self.on_dirty(True)
    def save_state(self):
        self.world_changed();self.config_path.parent.mkdir(parents=True,exist_ok=True);atomic_write_text(self.config_path,json.dumps(self.start_state,indent=2)+'\n',encoding='utf-8');self.on_status('PASS',f'Saved starting-world research manifest: {self.config_path}')
    def save(self):self.document.save();self.save_state();self.on_dirty(False);self.on_status('PASS','Saved item.csv and starting-world manifest.');return True
    def save_changes(self):return self.save()
