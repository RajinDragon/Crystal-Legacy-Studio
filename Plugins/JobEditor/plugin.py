def register(api, manifest):
    def open_editor(_api):
        if not api.project:
            api.show_error("Job Editor", "Open or create a Crystal Legacy project first."); return
        api.host.open_job_editor()
        api.log("PLUGIN", "Job Editor opened.")
    return {"open": open_editor}
