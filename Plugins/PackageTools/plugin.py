import tkinter as tk
from tkinter import ttk

def register(api, manifest):
    def open_editor(_api):
        if not api.project: api.show_error("Package Manager","Open a project first."); return
        key="package-manager"
        existing=api.host.tab_frames.get(f"plugin:{key}")
        if existing and str(existing) in api.workspace.tabs(): api.workspace.select(existing); return
        frame=ttk.Frame(api.workspace,padding=24)
        ttk.Label(frame,text="Package Manager",style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame,text="Import, merge, validate, and export Crystal Legacy or Nexus-style packages.",style="Muted.TLabel").pack(anchor="w",pady=(0,18))
        ttk.Button(frame,text="Import Package…",command=api.host.import_package).pack(anchor="w",pady=4)
        ttk.Button(frame,text="Export / Share Package…",command=api.host.export_package).pack(anchor="w",pady=4)
        api.add_tab(key,"Package Manager",frame)
    return {"open":open_editor}
