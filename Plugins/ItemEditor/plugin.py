def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error("Item & Key Item Designer", "Open or create a Crystal Legacy project first."); return
        api.host.open_item_designer()
        api.log("PLUGIN", "Item & Key Item Designer opened.")
    return {"open": open_editor}
