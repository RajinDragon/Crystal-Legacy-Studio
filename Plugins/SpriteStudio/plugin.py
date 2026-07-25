def register(api, manifest):
    def open_sprite_studio(_api):
        if not api.project:
            api.show_error("Sprite Studio", "Open or create a Crystal Legacy project first."); return
        api.host.open_job_editor()
        editor=api.host.editor_objects.get("editor:jobs")
        if editor is not None and hasattr(editor,"tabs"):
            try: editor.tabs.select(editor.tabs.tabs()[-1])
            except Exception: pass
        api.log("PLUGIN","Sprite Studio opened the sprite appearance workspace.")
        api.inspect("Sprite Studio",{"Plugin":manifest.get("name"),"Version":manifest.get("version"),"Install folder":r"Plugins\SpriteStudio","Scope":"Character battle/map models, saved pairs, bundle extraction, preview, recolor"})
    return {"open":open_sprite_studio}
