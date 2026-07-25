from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.ui.widgets.field_labels import friendly_label


class TableEditor(ttk.Frame):
    """Reusable safe CSV editor for every Master table not yet given a designer."""
    def __init__(self, parent, title, document, on_dirty, on_status, on_inspect, message_catalog=None, message_prefix=None, on_saved=None):
        super().__init__(parent)
        self.title_text = title
        self.document = document
        self.on_dirty = on_dirty
        self.on_status = on_status
        self.on_inspect = on_inspect
        self.message_catalog = message_catalog
        self.message_prefix = message_prefix
        self.on_saved = on_saved
        self.name_var = tk.StringVar()
        self.current = None
        self.indices = []
        self.loading = False
        self.vars = {}
        self._build()
        self.refresh()
        if self.indices:
            self.list.selection_set(0)
            self.select(0)

    def _build(self):
        header = ttk.Frame(self, padding=12); header.pack(fill="x")
        ttk.Label(header, text=self.title_text, style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Save", command=self.save).pack(side="right")
        ttk.Button(header, text="Validate", command=self.validate).pack(side="right", padx=6)
        pane = ttk.Panedwindow(self, orient="horizontal"); pane.pack(fill="both", expand=True, padx=10, pady=10)
        left = ttk.Frame(pane, padding=8); right = ttk.Frame(pane, padding=8)
        pane.add(left, weight=1); pane.add(right, weight=4)
        self.search = tk.StringVar(); self.search.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=(0,8))
        self.list = tk.Listbox(left, bg=DARK["panel"], fg=DARK["fg"], selectbackground=DARK["selection"], relief="flat", exportselection=False)
        self.list.pack(fill="both", expand=True); self.list.bind("<<ListboxSelect>>", self._selected)
        buttons=ttk.Frame(left); buttons.pack(fill="x", pady=6)
        ttk.Button(buttons,text="Duplicate",command=self.duplicate).pack(side="left")
        ttk.Button(buttons,text="Delete",command=self.delete).pack(side="left",padx=4)
        canvas=tk.Canvas(right,bg=DARK["panel"],highlightthickness=0)
        scroll=ttk.Scrollbar(right,orient="vertical",command=canvas.yview)
        self.form=ttk.Frame(canvas,padding=14); self.form.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=self.form,anchor="nw"); canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
        start_row = 0
        if self.message_catalog and self.message_prefix:
            ttk.Label(self.form, text="Display Name").grid(row=0, column=0, sticky="w", padx=5, pady=4)
            self.name_var.trace_add("write", lambda *_: self.localized_name_changed())
            ttk.Entry(self.form, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=5, pady=4)
            ttk.Label(self.form, text="Saved in system_en.txt and deployed with the table.", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=(0,8))
            start_row = 2
        for offset, field in enumerate(self.document.fieldnames):
            row = start_row + offset
            ttk.Label(self.form,text=friendly_label(field)).grid(row=row,column=0,sticky="w",padx=5,pady=4)
            var=tk.StringVar(); var.trace_add("write",lambda *_a,key=field:self.changed(key)); self.vars[field]=var
            ttk.Entry(self.form,textvariable=var).grid(row=row,column=1,sticky="ew",padx=5,pady=4)
        self.form.columnconfigure(1,weight=1)

    def _message_key(self, row):
        if not (self.message_catalog and self.message_prefix):
            return None
        explicit = row.get("mes_id_name")
        if explicit and str(explicit).startswith("MSG_"):
            return str(explicit)
        try:
            return f"{self.message_prefix}{int(row.get('id','0')):02d}"
        except Exception:
            return None

    def _label(self,row):
        explicit = row.get("mes_id_name") or row.get("name")
        if explicit:
            if self.message_catalog and str(explicit).startswith("MSG_"):
                return self.message_catalog.display(explicit) or explicit
            return explicit
        if self.message_catalog and self.message_prefix:
            try:
                key = f"{self.message_prefix}{int(row.get('id','0')):02d}"
                name = self.message_catalog.display(key)
                if name and name != key:
                    return name
            except Exception:
                pass
        return row.get("id","")
    def refresh(self, preserve_current=False):
        selected_row = self.current if preserve_current else None
        q=self.search.get().strip().lower(); self.indices=[]; self.list.delete(0,"end")
        for i,row in enumerate(self.document.rows):
            if not q or q in " ".join(row.values()).lower():
                self.indices.append(i); self.list.insert("end",f"{row.get('id','')} — {self._label(row)}")
        if selected_row is not None and selected_row in self.indices:
            pos = self.indices.index(selected_row); self.list.selection_set(pos); self.list.see(pos)
    def _selected(self,_event=None):
        s=self.list.curselection()
        if s:self.select(s[0])
    def select(self,visible):
        self.current=self.indices[visible]; row=self.document.rows[self.current]; self.loading=True
        for field,var in self.vars.items():var.set(row.get(field,""))
        key = self._message_key(row)
        self.name_var.set(self.message_catalog.display(key) if key else "")
        self.loading=False; self.update_inspector()
    def localized_name_changed(self):
        if self.loading or self.current is None or not self.message_catalog:
            return
        key = self._message_key(self.document.rows[self.current])
        if key:
            self.message_catalog.set_text(key, self.name_var.get())
            self.on_dirty(True)
            self.refresh(preserve_current=True)

    def changed(self,field):
        if self.loading or self.current is None:return
        self.document.rows[self.current][field]=self.vars[field].get(); self.on_dirty(True); self.update_inspector()
    def update_inspector(self):
        if self.current is None:return
        row=self.document.rows[self.current]
        self.on_inspect(self.title_text,{field:row.get(field,"") for field in self.document.fieldnames[:14]})
    def duplicate(self):
        if self.current is None:return
        row=dict(self.document.rows[self.current])
        try: row["id"]=str(max(int(r.get("id","0") or 0) for r in self.document.rows)+1)
        except Exception: pass
        self.document.rows.append(row); self.on_dirty(True); self.refresh()
    def delete(self):
        if self.current is not None and messagebox.askyesno("Delete record","Delete the selected record?",parent=self):
            del self.document.rows[self.current]; self.current=None; self.on_dirty(True); self.refresh()
    def validate(self):
        issues=self.document.validate(); self.on_status("PASS" if not issues else "ERROR", "Table passed validation." if not issues else f"{len(issues)} issue(s).")
        if issues:messagebox.showwarning("Validation","\n".join(issues[:30]),parent=self)
        return issues
    def save(self):
        self.document.save()
        if self.message_catalog:
            self.message_catalog.save()
        self.on_dirty(False); self.on_status("PASS",f"Saved {self.document.path.name} and localized names.")
        if self.on_saved:
            self.on_saved()
        return True
    def save_changes(self):return self.save()
