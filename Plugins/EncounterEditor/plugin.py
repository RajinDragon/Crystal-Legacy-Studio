def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error("Encounter Designer", "Open or create a Crystal Legacy project first."); return
        api.host.open_encounter_editor()
        api.log("PLUGIN", "Encounter Designer opened.")
    return {"open": open_editor}
