from tkinter import ttk

def register(api, manifest):
    def open_tool(_api):
        frame=ttk.Frame(api.workspace,padding=24)
        ttk.Label(frame,text="Example Plugin",style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame,text="This page came from a removable plugin folder.").pack(anchor="w",pady=12)
        api.add_tab("example-tool","Example Tool",frame)
        api.log("PLUGIN","Example Plugin opened.")
    return {"open":open_tool}
