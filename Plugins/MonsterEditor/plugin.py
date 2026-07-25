def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error("Monster Editor", "Open or create a Crystal Legacy project first."); return
        api.host.open_monster_editor()
        api.log("PLUGIN", "Monster Editor opened.")
    return {"open": open_editor}
