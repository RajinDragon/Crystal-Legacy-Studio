import os
import tkinter as tk
from tkinter import ttk, messagebox

def register(api, manifest):
    def open_manager(_api):
        key = "installed-plugins"
        existing = api.host.tab_frames.get(f"plugin:{key}")
        if existing and str(existing) in api.workspace.tabs():
            api.workspace.select(existing); return
        frame = ttk.Frame(api.workspace, padding=22)
        ttk.Label(frame, text="Installed Plugins", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Drop a plugin folder into Plugins and restart Studio. Remove the folder and restart to uninstall.", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        tree = ttk.Treeview(frame, columns=("version", "category", "folder"), show="tree headings")
        for col,title,width in [("#0","Plugin",220),("version","Version",90),("category","Explorer Area",150),("folder","Folder",430)]:
            tree.heading(col,text=title); tree.column(col,width=width)
        tree.pack(fill="both", expand=True)
        items={}
        for item in sorted(api.host.plugin_manager.contributions.values(), key=lambda x:x.label.lower()):
            iid=tree.insert("","end",text=item.label,values=(item.version,item.explorer_path[0] if item.explorer_path else "Plugins",str(item.folder)))
            items[iid]=item
        row=ttk.Frame(frame); row.pack(fill="x",pady=(12,0))
        def open_folder():
            sel=tree.selection()
            if not sel:return
            item=items.get(sel[0])
            if item and item.folder: os.startfile(str(item.folder))
        ttk.Button(row,text="Open Plugin Folder",command=open_folder).pack(side="left")
        ttk.Button(row,text="Refresh List",command=lambda: messagebox.showinfo("Plugins","Plugin discovery occurs safely at startup. Restart Studio after adding or removing folders.",parent=api.host)).pack(side="left",padx=6)
        ttk.Button(row,text="Close Page",command=lambda: api.host._close_tab_key(f"plugin:{key}", force=True)).pack(side="right")
        api.add_tab(key,"Installed Plugins",frame)
    return {"open": open_manager}
