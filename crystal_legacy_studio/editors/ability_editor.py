from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.editors.permission_slots import permission_field_for_job, permission_slot_for_job

class AbilityEditor(ttk.Frame):
    """Readable ability editor using FF1PR native permission groups."""
    def __init__(self,parent,document,job_document,job_group_document,messages,on_dirty,on_status,on_inspect,on_saved=None):
        super().__init__(parent); self.document=document; self.jobs=job_document; self.groups=job_group_document; self.messages=messages
        self.on_dirty=on_dirty; self.on_status=on_status; self.on_inspect=on_inspect; self.current=None; self.loading=False; self.indices=[]; self.vars={}
        self._build(); self.refresh();
        if self.indices:self.list.selection_set(0);self.select(0)
    def _build(self):
        h=ttk.Frame(self,padding=12);h.pack(fill='x');ttk.Label(h,text='Magic & Ability Designer',style='Title.TLabel').pack(side='left');ttk.Button(h,text='Save',command=self.save).pack(side='right');ttk.Button(h,text='Validate',command=self.validate).pack(side='right',padx=6)
        p=ttk.Panedwindow(self,orient='horizontal');p.pack(fill='both',expand=True,padx=10,pady=10);left=ttk.Frame(p,padding=8);right=ttk.Frame(p,padding=8);p.add(left,weight=1);p.add(right,weight=4)
        self.search=tk.StringVar();self.search.trace_add('write',lambda *_:self.refresh());ttk.Entry(left,textvariable=self.search).pack(fill='x',pady=(0,8))
        self.list=tk.Listbox(left,bg=DARK['panel'],fg=DARK['fg'],selectbackground=DARK['selection'],relief='flat',exportselection=False);self.list.pack(fill='both',expand=True);self.list.bind('<<ListboxSelect>>',self._selected)
        nb=ttk.Notebook(right);nb.pack(fill='both',expand=True);details=ttk.Frame(nb,padding=12);perm=ttk.Frame(nb,padding=12);nb.add(details,text='Ability Details');nb.add(perm,text='Job Permissions')
        canvas=tk.Canvas(details,bg=DARK['panel'],highlightthickness=0);scroll=ttk.Scrollbar(details,orient='vertical',command=canvas.yview);self.form=ttk.Frame(canvas,padding=8);self.form.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.create_window((0,0),window=self.form,anchor='nw');canvas.configure(yscrollcommand=scroll.set);canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        for row,field in enumerate(self.document.fieldnames):
            ttk.Label(self.form,text=field.replace('_',' ').title()).grid(row=row,column=0,sticky='w',padx=4,pady=3);v=tk.StringVar();v.trace_add('write',lambda *_a,k=field:self.changed(k));self.vars[field]=v;ttk.Entry(self.form,textvariable=v).grid(row=row,column=1,sticky='ew',padx=4,pady=3)
        self.form.columnconfigure(1,weight=1)
        ttk.Label(perm,text='Edits the existing FF1PR job_group.csv permission row directly. Items or spells sharing a native group will change together.',style='Muted.TLabel',wraplength=700).pack(anchor='w',pady=(0,8))
        self.permission_tree=ttk.Treeview(perm,columns=('allowed',),show='tree headings');self.permission_tree.heading('#0',text='Job');self.permission_tree.heading('allowed',text='Allowed');self.permission_tree.column('#0',width=260);self.permission_tree.column('allowed',width=70,anchor='center');self.permission_tree.pack(fill='both',expand=True);self.permission_tree.bind('<ButtonRelease-1>',self.permission_click)
    def ability_name(self,row):
        aid=int(row.get('id','0') or 0); key=f'MSG_MAGIC_NAME_{aid:02d}'; name=self.messages.display(key)
        return name if name and name!=key else f'Ability {aid}'
    def job_name(self,row):
        key=row.get('mes_id_name',''); return self.messages.display(key) or key or f"Job {row.get('id','')}"
    def refresh(self):
        q=self.search.get().lower().strip();self.indices=[];self.list.delete(0,'end')
        for i,r in enumerate(self.document.rows):
            text=f"{r.get('id','')} {self.ability_name(r)}"
            if not q or q in (text+' '+' '.join(r.values())).lower():self.indices.append(i);self.list.insert('end',f"{r.get('id','')} — {self.ability_name(r)}")
    def _selected(self,_=None):
        s=self.list.curselection();
        if s:self.select(s[0])
    def select(self,v):
        self.current=self.indices[v];r=self.document.rows[self.current];self.loading=True
        for k,x in self.vars.items():x.set(r.get(k,''))
        self.loading=False;self.refresh_permissions();self.on_inspect('Ability',{'ID':r.get('id',''),'Name':self.ability_name(r),'Level':r.get('ability_lv',''),'Permission group':r.get('use_job_group_id','')})
    def changed(self,k):
        if self.loading or self.current is None:return
        self.document.rows[self.current][k]=self.vars[k].get();self.on_dirty(True)
        if k=='use_job_group_id':self.refresh_permissions()
    def _group(self,gid):return next((r for r in self.groups.rows if str(r.get('id',''))==str(gid)),None)
    def refresh_permissions(self):
        for x in self.permission_tree.get_children():self.permission_tree.delete(x)
        if self.current is None:return
        row=self.document.rows[self.current];g=self._group(row.get('use_job_group_id',''))
        for job in self.jobs.rows:
            jid=str(job.get('id',''));allowed=(g or {}).get(permission_field_for_job(jid),'0')=='1';self.permission_tree.insert('', 'end', iid=jid, text=self.job_name(job), values=('☑' if allowed else '☐',))
    def permission_click(self,event=None):
        if event is not None:
            item=self.permission_tree.identify_row(event.y)
            if not item:return
            self.permission_tree.selection_set(item)
        self.toggle_permission()
    def toggle_permission(self,event=None):
        if self.current is None:return
        sel=self.permission_tree.selection();
        if not sel:return
        jid=sel[0];ability=self.document.rows[self.current];gid=str(ability.get('use_job_group_id','0'));group=self._group(gid)
        if group is None:
            messagebox.showwarning('Ability permission',f'Ability references missing native job group {gid}. Restore job_group.csv from MagiciteExport before editing.',parent=self)
            return
        field=permission_field_for_job(jid)
        if field not in group:
            messagebox.showwarning('Ability permission',f'Native permission column {field} is missing.',parent=self)
            return
        group[field]='0' if str(group.get(field,'0')).strip()=='1' else '1'
        self.on_dirty(True);self.on_status('INFO',f"Updated native ability group {gid} for {self.ability_name(ability)}; toggled {self.permission_tree.item(jid,'text')}. Shared abilities using group {gid} are affected together.");self.refresh_permissions()
    def validate(self):
        issues=self.document.validate()+self.groups.validate();self.on_status('PASS' if not issues else 'ERROR','Ability data passed validation.' if not issues else f'{len(issues)} issue(s).');return issues
    def save(self):
        self.document.save();self.groups.save();self.on_dirty(False);self.on_status('PASS','Saved ability.csv and job_group.csv.')
        if self.on_saved:self.on_saved()
        return True
    def save_changes(self):return self.save()
