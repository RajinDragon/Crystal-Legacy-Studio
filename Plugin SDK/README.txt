CRYSTAL LEGACY STUDIO PLUGIN SDK

INSTALL
Copy one complete plugin folder into Crystal Legacy Studio\Plugins and restart Studio.
Remove that folder and restart to uninstall.

PLUGIN CONTRACT
Each plugin folder needs plugin.json and an entry module (normally plugin.py).
register(api, manifest) must return {"open": callable}.

STABLE HOST API
api.project       Current Project or None
api.workspace     Managed ttk.Notebook
api.log(level,message)
api.inspect(title,dict)
api.add_tab(key,title,frame,pinned=False)
api.show_error(title,message)

SAFETY
Plugins should write only through the current project working directory or host deployment services.
MagiciteExport is read-only reference data.

CURRENT LIMITATION
The preview still exposes selected host editor entry methods for migrated first-party plugins. A later SDK revision will replace these with formal document/deployment services so third-party plugins never need api.host internals.
