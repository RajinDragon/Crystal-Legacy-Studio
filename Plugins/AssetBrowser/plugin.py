def register(api, manifest):
    def open_editor(_api):
        if not api.project: api.show_error("Asset Library","Open a project first."); return
        api.host.open_asset_browser("assets",None)
    return {"open":open_editor}
