from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.ui.widgets.field_labels import friendly_label

class EncounterEditor(ttk.Frame):
    """Readable encounter-area editor that resolves set -> formation -> monster names."""
    def __init__(self,parent,document,set_document,party_document,monster_document,messages,on_dirty,on_status,on_inspect,area_document=None,map_document=None):
        super().__init__(parent); self.document=document; self.set_document=set_document; self.party_document=party_document; self.monster_document=monster_document; self.messages=messages
        self.area_document=area_document;self.map_document=map_document;self.area_names={str(r.get('id','')):(messages.display(r.get('area_name','')) or r.get('area_name','')) for r in (area_document.rows if area_document else [])};self.map_rows=(map_document.rows if map_document else []);self.on_dirty=on_dirty;self.on_status=on_status;self.on_inspect=on_inspect;self.current=None;self.loading=False;self.vars={};self.indices=[]
        self.monsters={str(r.get('id','')):(messages.display(r.get('mes_id_name','')) or r.get('mes_id_name','')) for r in monster_document.rows}
        self.parties={str(r.get('id','')):r for r in party_document.rows};self.sets={str(r.get('id','')):r for r in set_document.rows}
        self._build();self.refresh();
        if self.indices:self.list.selection_set(0);self.select(0)
    def _build(self):
        h=ttk.Frame(self,padding=12);h.pack(fill='x');ttk.Label(h,text='Encounter Designer',style='Title.TLabel').pack(side='left');ttk.Button(h,text='Save',command=self.save).pack(side='right');ttk.Button(h,text='Validate',command=self.validate).pack(side='right',padx=6)
        p=ttk.Panedwindow(self,orient='horizontal');p.pack(fill='both',expand=True,padx=10,pady=10);left=ttk.Frame(p,padding=8);right=ttk.Frame(p,padding=8);p.add(left,weight=1);p.add(right,weight=4)
        self.search=tk.StringVar();self.search.trace_add('write',lambda *_:self.refresh());ttk.Entry(left,textvariable=self.search).pack(fill='x',pady=(0,8))
        self.list=tk.Listbox(left,bg=DARK['panel'],fg=DARK['fg'],selectbackground=DARK['selection'],relief='flat',exportselection=False);self.list.pack(fill='both',expand=True);self.list.bind('<<ListboxSelect>>',self._selected)
        canvas=tk.Canvas(right,bg=DARK['panel'],highlightthickness=0);scroll=ttk.Scrollbar(right,orient='vertical',command=canvas.yview);self.form=ttk.Frame(canvas,padding=12);self.form.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.create_window((0,0),window=self.form,anchor='nw');canvas.configure(yscrollcommand=scroll.set);canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        row=0
        for field in self.document.fieldnames:
            ttk.Label(self.form,text=friendly_label(field)).grid(row=row,column=0,sticky='nw',padx=5,pady=5)
            v=tk.StringVar();v.trace_add('write',lambda *_a,key=field:self.changed(key));self.vars[field]=v;ttk.Entry(self.form,textvariable=v,width=12).grid(row=row,column=1,sticky='nw',padx=5,pady=5)
            if field.endswith('_monster_set'):
                label=ttk.Label(self.form,text='',wraplength=620,justify='left');label.grid(row=row,column=2,sticky='w',padx=8,pady=5);v.trace_add('write',lambda *_a,key=field,l=label:self._update_resolution(key,l))
            row+=1
        self.form.columnconfigure(2,weight=1)
    def _formation_label(self,pid):
        party=self.parties.get(str(pid));
        if not party:return f'Formation {pid} (not found)'
        names=[]
        for i in range(1,10):
            mid=str(party.get(f'monster{i}','0'))
            if mid not in ('','0'):names.append(self.monsters.get(mid,f'Monster {mid}'))
        return f"Formation {pid}: " + (', '.join(names) if names else '(empty)')
    def resolve_set(self,sid):
        s=self.sets.get(str(sid));
        if not s:return 'No encounter set' if str(sid) in ('','0') else f'Set {sid} not found'
        forms=[]
        for i in range(1,17):
            pid=str(s.get(f'monster_set{i}','0'));rate=str(s.get(f'monster_set{i}_rate','0'))
            if pid not in ('','0'):forms.append(f"{rate}% {self._formation_label(pid)}")
        return f"Set {sid}: " + (' | '.join(forms) if forms else '(empty)')
    def _update_resolution(self,field,label):label.config(text=self.resolve_set(self.vars[field].get()))
    def refresh(self):
        q=self.search.get().lower().strip();self.indices=[];self.list.delete(0,'end')
        for i,r in enumerate(self.document.rows):
            text=self._area_label(r)
            if not q or q in (text+' '+' '.join(r.values())).lower():self.indices.append(i);self.list.insert('end',text)

    def _area_label(self,r):
        aid=str(r.get('id','')); grid=str(r.get('encount_area_grid_number',''))
        set_ids={str(v) for k,v in r.items() if k.endswith('_monster_set') and str(v) not in ('','0')}
        candidates=[]
        for m in self.map_rows:
            if str(m.get('monster_set_id','')) in set_ids:
                area=self.area_names.get(str(m.get('area_id','')),f"Area {m.get('area_id','')}")
                floor=self.messages.display(m.get('map_title','')) if m.get('map_title','') not in ('','None') else ''
                label=f"{area}{' '+floor if floor else ''}"
                if label not in candidates:candidates.append(label)
        hint=' / '.join(candidates[:3]) if candidates else 'Unmapped area'
        return f"{hint} — Area {aid}, Grid {grid}"

    def _selected(self,_=None):
        s=self.list.curselection();
        if s:self.select(s[0])
    def select(self,v):
        self.current=self.indices[v];r=self.document.rows[self.current];self.loading=True
        for k,x in self.vars.items():x.set(r.get(k,''))
        self.loading=False;self.on_inspect('Encounter Area',{'ID':r.get('id',''),'Grid':r.get('encount_area_grid_number',''),'Resolved sets':sum(1 for k,v in r.items() if k.endswith('_monster_set') and v not in ('','0'))})
    def changed(self,k):
        if self.loading or self.current is None:return
        self.document.rows[self.current][k]=self.vars[k].get();self.on_dirty(True)
    def validate(self):
        issues=self.document.validate();self.on_status('PASS' if not issues else 'ERROR','Encounter data passed validation.' if not issues else f'{len(issues)} issue(s).');return issues
    def save(self):self.document.save();self.on_dirty(False);self.on_status('PASS','Saved encount_area.csv.');return True
    def save_changes(self):return self.save()
