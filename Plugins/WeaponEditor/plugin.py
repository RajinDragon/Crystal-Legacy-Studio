def register(api, manifest):
    def open_editor(_api):
        if not api.project: api.show_error("Weapon Editor","Open a project first."); return
        api.host.open_table_editor("weapons","weapon.csv","Weapon Editor")
    return {"open":open_editor}
