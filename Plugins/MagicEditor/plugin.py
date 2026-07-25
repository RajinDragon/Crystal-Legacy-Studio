def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error("Magic & Ability Designer", "Open or create a Crystal Legacy project first."); return
        api.host.open_ability_editor()
        api.log("PLUGIN", "Magic & Ability Designer opened.")
    return {"open": open_editor}
