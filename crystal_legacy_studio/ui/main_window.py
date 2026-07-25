import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
try:
    from tkinterdnd2 import TkinterDnD
    _StudioTkBase = TkinterDnD.Tk
except Exception:
    _StudioTkBase = tk.Tk
from pathlib import Path
import datetime
import json
import os
import subprocess
import sys
import shutil

from crystal_legacy_studio import __version__
from crystal_legacy_studio.core.settings import SettingsStore
from crystal_legacy_studio.core.capabilities import CapabilityRegistry, StudioModule
from crystal_legacy_studio.core.logging_service import StudioLogger
from crystal_legacy_studio.project.models import ProjectService, Project
from crystal_legacy_studio.project.layout import GameProjectLayout
from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.ui.dialogs import SetupWizard, NewProjectDialog, ExportPackageDialog
from crystal_legacy_studio.game.detection import GameDetector
from crystal_legacy_studio.game.profiles import GAME_PROFILES, PROFILE_BY_DISPLAY, get_profile
from crystal_legacy_studio.core.workspace_tabs import WorkspaceTabPolicy, TabRecord
from crystal_legacy_studio.editors.csv_document import CsvDocument, locate_csv, ensure_project_copy
from crystal_legacy_studio.editors.job_editor import JobEditor
from crystal_legacy_studio.localization.catalog import MessageCatalog, locate_message_file, ensure_project_message_copy
from crystal_legacy_studio.editors.reference_choices import command_choices
from crystal_legacy_studio.editors.growth_model import load_growth
from crystal_legacy_studio.editors.monster_editor import MonsterEditor
from crystal_legacy_studio.build.deployer import MagiciteDeployer
from crystal_legacy_studio.editors.table_editor import TableEditor
from crystal_legacy_studio.editors.encounter_editor import EncounterEditor
from crystal_legacy_studio.editors.ability_editor import AbilityEditor
from crystal_legacy_studio.editors.item_editor import ItemDesigner
from crystal_legacy_studio.packaging.importer import PackageImporter
from crystal_legacy_studio.editors.asset_browser import AssetBrowser
from crystal_legacy_studio.editors.bundle_workbench import BundleWorkbench
from crystal_legacy_studio.assets.catalog import CATEGORY_ORDER
from crystal_legacy_studio.core.plugin_system import PluginManager

class MainWindow(_StudioTkBase):
    def __init__(self):
        super().__init__()
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.project: Project | None = None
        self.registry = CapabilityRegistry()
        self.tab_policy = WorkspaceTabPolicy()
        self.tab_frames: dict[str, tk.Widget] = {}
        self.frame_keys: dict[str, str] = {}
        self.editor_objects: dict[str, object] = {}
        self.logger = StudioLogger(Path.home() / ".crystal-legacy-studio" / "logs")
        self.title(f"Crystal Legacy Studio — Plugin Platform Preview ({__version__})")
        self.geometry(self.settings.window_geometry)
        self.minsize(1100, 700)
        self.configure(bg=DARK["bg"])
        self._configure_styles()
        self.plugin_manager = PluginManager(Path(__file__).resolve().parents[2] / "Plugins", self)
        self._register_modules()
        self._load_plugins()
        self._build_menu()
        self._build_toolbar()
        self._build_layout()
        self._show_welcome()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.logger.info("Studio started")

        self.after(250, self._maybe_run_setup)
        if self.settings.last_project:
            root = Path(self.settings.last_project)
            manifest = GameProjectLayout(root, self.settings.active_game_profile).working_root / "crystal-project.json"
            if manifest.exists():
                try:
                    self.open_project(root)
                except Exception as exc:
                    self.write_output("ERROR", f"Could not reopen the last project: {exc}")

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=DARK["panel"], foreground=DARK["fg"],
                        fieldbackground=DARK["panel2"], bordercolor=DARK["border"],
                        lightcolor=DARK["border"], darkcolor=DARK["border"])
        style.configure("TFrame", background=DARK["panel"])
        style.configure("Toolbar.TFrame", background=DARK["panel2"])
        style.configure("TLabel", background=DARK["panel"], foreground=DARK["fg"])
        style.configure("Muted.TLabel", foreground=DARK["muted"])
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", background=DARK["panel2"], foreground=DARK["fg"], padding=(10, 6))
        style.map("TButton", background=[("active", DARK["selection"])])
        style.configure("Treeview", background=DARK["panel"], fieldbackground=DARK["panel"],
                        foreground=DARK["fg"], rowheight=24, borderwidth=0)
        style.map("Treeview", background=[("selected", DARK["selection"])])
        style.configure("TNotebook", background=DARK["panel"], borderwidth=0)
        style.configure("TNotebook.Tab", background=DARK["panel2"], foreground=DARK["fg"], padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", DARK["selection"])])
        style.configure("TPanedwindow", background=DARK["border"])

    def _register_modules(self):
        # The shell owns only stable platform services. Feature editors are discovered
        # from the Plugins folder so they can be installed, removed, and developed independently.
        modules = [
            ("project", "Project", "Core", {"search", "validation"}),
            ("settings", "Settings", "Core", set()),
            ("runtime", "Runtime", "Systems", {"diagnostics"}),
            ("logs", "Logs", "Distribution", {"search"}),
        ]
        for module_id, name, category, capabilities in modules:
            self.registry.register(StudioModule(module_id, name, category, capabilities))


    def _load_plugins(self):
        plugins = self.plugin_manager.discover()
        for plugin in plugins:
            category = plugin.explorer_path[0] if plugin.explorer_path else "Plugins"
            self.registry.register(StudioModule(f"plugin.{plugin.plugin_id}", plugin.label, category, {"plugin"}))
        for error in self.plugin_manager.errors:
            self.logger.error(f"Plugin load failed: {error}")

    def _build_menu(self):
        bar = tk.Menu(self, bg=DARK["panel2"], fg=DARK["fg"], tearoff=False)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="New Project…", command=self.new_project)
        file_menu.add_command(label="Open Project…", command=self.choose_open_project)
        file_menu.add_command(label="Save Project", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Export / Share Package…", command=self.export_package)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        bar.add_cascade(label="File", menu=file_menu)

        build_menu = tk.Menu(bar, tearoff=False)
        build_menu.add_command(label="Validate Project", command=self.validate_project)
        build_menu.add_command(label="Build Verified Package…", command=self.export_package)
        bar.add_cascade(label="Build", menu=build_menu)

        view_menu = tk.Menu(bar, tearoff=False)
        view_menu.add_command(label="Welcome", command=self._show_welcome)
        view_menu.add_command(label="Game Installations & Active Profile…", command=self.configure_game)
        view_menu.add_command(label="Show Active Game Paths", command=self.show_active_game_paths)
        view_menu.add_separator()
        view_menu.add_command(label="Clear Output", command=self.clear_output)
        bar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        bar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=bar)
        self.bind_all("<Control-s>", lambda _: self.save_project())

    def _build_toolbar(self):
        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=(8, 6))
        toolbar.pack(side="top", fill="x")
        for text, command in [
            ("New", self.new_project), ("Open", self.choose_open_project),
            ("Save", self.save_project), ("Validate", self.validate_project),
            ("Build Package", self.export_package),
        ]:
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=3)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Launch Game", command=self.launch_game).pack(side="left")
        ttk.Button(toolbar, text="Runtime", command=lambda: self.open_module("runtime")).pack(side="left", padx=3)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(toolbar, text="Game:").pack(side="left", padx=(0,4))
        self.active_profile_var = tk.StringVar(value=get_profile(self.settings.active_game_profile).display_name)
        self.active_profile_combo = ttk.Combobox(toolbar, textvariable=self.active_profile_var, state="readonly", width=31,
                                                 values=[p.display_name for p in GAME_PROFILES])
        self.active_profile_combo.pack(side="left", padx=(0,8))
        self.active_profile_combo.bind("<<ComboboxSelected>>", self._active_profile_changed)
        self.project_label = ttk.Label(toolbar, text="No project open", style="Muted.TLabel")
        self.project_label.pack(side="right", padx=8)

    def _build_layout(self):
        outer = ttk.Panedwindow(self, orient="vertical")
        outer.pack(fill="both", expand=True)

        # Use the classic Tk PanedWindow for the three-column workspace. Unlike
        # ttk.Panedwindow, it supports hard minimum pane sizes, so neither the
        # Project Explorer nor the editor area can silently start at zero width.
        upper = tk.PanedWindow(
            outer,
            orient="horizontal",
            bg=DARK["border"],
            bd=0,
            sashwidth=5,
            sashrelief="flat",
            showhandle=False,
        )
        outer.add(upper, weight=5)

        left = ttk.Frame(upper, padding=6, width=280)
        center = ttk.Frame(upper, padding=0)
        right = ttk.Frame(upper, padding=6, width=230)
        upper.add(left, minsize=225, stretch="never")
        upper.add(center, minsize=560, stretch="always")
        upper.add(right, minsize=185, stretch="never")
        left.pack_propagate(False)
        right.pack_propagate(False)

        ttk.Label(left, text="PROJECT EXPLORER", style="Heading.TLabel").pack(anchor="w", padx=4, pady=(2, 6))
        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self._populate_tree()

        self.workspace = ttk.Notebook(center)
        self.workspace.pack(fill="both", expand=True)
        self.workspace.bind("<Button-2>", self._middle_click_close)
        self.workspace.bind("<Button-3>", self._show_tab_menu)
        self.workspace.bind("<Double-Button-1>", self._double_click_pin)
        self.bind_all("<Control-w>", lambda _event: self.close_current_tab())
        self.tab_menu = tk.Menu(self, tearoff=False)
        self.tab_menu.add_command(label="Close", command=self.close_current_tab)
        self.tab_menu.add_command(label="Close Other Tabs", command=self.close_other_tabs)
        self.tab_menu.add_separator()
        self.tab_menu.add_command(label="Pin / Unpin", command=self.toggle_current_tab_pin)

        ttk.Label(right, text="INSPECTOR", style="Heading.TLabel").pack(anchor="w", padx=4, pady=(2, 6))
        self.inspector_title = ttk.Label(right, text="Nothing selected", font=("Segoe UI", 12, "bold"))
        self.inspector_title.pack(anchor="w", padx=4)
        self.inspector_text = tk.Text(right, wrap="word", bg=DARK["panel"], fg=DARK["fg"],
                                      insertbackground=DARK["fg"], relief="flat", padx=6, pady=8)
        self.inspector_text.pack(fill="both", expand=True)
        self.inspector_text.configure(state="disabled")

        # Open the Project Explorer wide enough to show its longest visible
        # entry and keep the Inspector compact on every startup. The hard pane
        # minimums above also prevent either side from ever disappearing.
        self._workspace_panes_initialized = False

        def _desired_explorer_width():
            tree_font = tkfont.nametofont("TkDefaultFont")
            widest = tree_font.measure("PROJECT EXPLORER") + 38

            def measure_node(item, depth=0):
                nonlocal widest
                label = self.tree.item(item, "text") or ""
                widest = max(widest, tree_font.measure(label) + 38 + depth * 18)
                for child in self.tree.get_children(item):
                    measure_node(child, depth + 1)

            for item in self.tree.get_children(""):
                measure_node(item)
            return max(225, min(380, widest))

        def _apply_workspace_panes(force=False):
            try:
                self.update_idletasks()
                total = upper.winfo_width()
                if total < 900:
                    return
                explorer_width = _desired_explorer_width()
                inspector_width = 230
                first = upper.sash_coord(0)[0]
                second = upper.sash_coord(1)[0]

                # Force the intended startup layout. Afterwards, only repair a
                # pane if it has somehow collapsed below its safe minimum.
                if force or not self._workspace_panes_initialized:
                    upper.sash_place(0, explorer_width, 1)
                    upper.sash_place(1, max(explorer_width + 560, total - inspector_width), 1)
                    self._workspace_panes_initialized = True
                else:
                    if first < 225:
                        upper.sash_place(0, explorer_width, 1)
                    if second - first < 560:
                        upper.sash_place(1, min(total - 185, first + 560), 1)
                    if total - second < 185:
                        upper.sash_place(1, total - inspector_width, 1)
            except (tk.TclError, IndexError):
                pass

        # Some Tk builds finish restoring/maximizing the window after idle.
        # Reapply the intended layout at several mapping stages, then retain a
        # configure guard that repairs only accidental complete collapses.
        self.after_idle(lambda: _apply_workspace_panes(True))
        self.after(100, lambda: _apply_workspace_panes(True))
        self.after(350, lambda: _apply_workspace_panes(True))
        self.after(800, lambda: _apply_workspace_panes(True))
        upper.bind("<Configure>", lambda _event: self.after_idle(_apply_workspace_panes), add="+")

        bottom = ttk.Frame(outer, padding=4)
        outer.add(bottom, weight=2)
        ttk.Label(bottom, text="OUTPUT", style="Heading.TLabel").pack(anchor="w", padx=4, pady=(0, 4))
        self.output = tk.Text(bottom, height=10, bg="#17181a", fg=DARK["fg"],
                              insertbackground=DARK["fg"], relief="flat", padx=8, pady=6)
        self.output.pack(fill="both", expand=True)

        self.status = ttk.Label(self, text="Ready", anchor="w", padding=(8, 4))
        self.status.pack(side="bottom", fill="x")

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        profile = get_profile(self.settings.active_game_profile)
        game_node = self.tree.insert("", "end", iid="active-game", text=f"FF{profile.roman} — {profile.display_name}", open=True)
        categories = {}
        for module in self.registry.all():
            parent = categories.get(module.category)
            if not parent:
                parent = self.tree.insert(game_node, "end", text=module.category, open=True)
                categories[module.category] = parent
            self.tree.insert(parent, "end", iid=f"module:{module.module_id}", text=module.display_name)

    def _tree_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        if item.startswith("module:"):
            self.open_module(item.split(":", 1)[1])

    def _show_welcome(self):
        frame = ttk.Frame(self.workspace, padding=30)
        title = ttk.Label(frame, text="Crystal Legacy Studio", style="Title.TLabel")
        title.pack(anchor="w", pady=(10, 4))
        ttk.Label(frame, text="The integrated development environment for Final Fantasy I Pixel Remaster modding.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 24))
        ttk.Button(frame, text="Create a New Project", command=self.new_project).pack(anchor="w", pady=4)
        ttk.Button(frame, text="Open an Existing Project", command=self.choose_open_project).pack(anchor="w", pady=4)
        ttk.Separator(frame).pack(fill="x", pady=24)
        ttk.Label(frame, text="Plugin Platform Workspace", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(frame, text=(
            "The Job Editor is now active. It creates a safe project copy of job.csv, supports search, "
            "dynamic field editing, additions, duplication, deletion, validation, and tracked saves."
        ), wraplength=760, justify="left").pack(anchor="w", pady=(6, 0))
        self._add_managed_tab("welcome", "Welcome", frame, kind="system", pinned=True)

    def _add_managed_tab(self, key: str, title: str, frame, *, kind: str = "module", pinned: bool = False):
        existing = self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():
            self.workspace.select(existing)
            return existing
        record = TabRecord(key=key, title=title, kind=kind, pinned=pinned)
        self.tab_policy.register(record)
        self.tab_frames[key] = frame
        self.frame_keys[str(frame)] = key
        self.workspace.add(frame, text=self.tab_policy.display_title(record))
        self.workspace.select(frame)
        return frame

    def _tab_key_at(self, x: int, y: int) -> str | None:
        try:
            index = self.workspace.index(f"@{x},{y}")
            tab_id = self.workspace.tabs()[index]
            return self.frame_keys.get(str(tab_id))
        except (tk.TclError, IndexError):
            return None

    def _current_tab_key(self) -> str | None:
        selected = self.workspace.select()
        return self.frame_keys.get(str(selected)) if selected else None

    def _refresh_tab_title(self, key: str) -> None:
        frame = self.tab_frames.get(key)
        record = self.tab_policy.get(key)
        if frame and record and str(frame) in self.workspace.tabs():
            self.workspace.tab(frame, text=self.tab_policy.display_title(record))

    def _close_tab_key(self, key: str, *, force: bool = False) -> bool:
        record = self.tab_policy.get(key)
        frame = self.tab_frames.get(key)
        if not record or not frame:
            return False
        if record.kind == "system" and not force:
            return False
        if record.dirty and not force:
            answer = messagebox.askyesnocancel(
                "Unsaved changes",
                f"Save changes to {record.title} before closing?",
                parent=self,
            )
            if answer is None:
                return False
            if answer:
                editor = self.editor_objects.get(key)
                if editor and hasattr(editor, "save_changes"):
                    if not editor.save_changes():
                        return False
                else:
                    self.save_project()
                record.dirty = False
        try:
            self.workspace.forget(frame)
            frame.destroy()
        except tk.TclError:
            pass
        self.frame_keys.pop(str(frame), None)
        self.tab_frames.pop(key, None)
        self.tab_policy.remove(key)
        self.editor_objects.pop(key, None)
        return True

    def close_current_tab(self):
        key = self._current_tab_key()
        if key:
            self._close_tab_key(key)

    def close_other_tabs(self):
        keep = self._current_tab_key()
        for key in list(self.tab_frames):
            if key != keep and self.tab_policy.get(key) and self.tab_policy.get(key).kind != "system":
                self._close_tab_key(key)

    def toggle_current_tab_pin(self):
        key = self._current_tab_key()
        record = self.tab_policy.get(key) if key else None
        if not record or record.kind == "system" or record.dirty:
            return
        self.tab_policy.toggle_pin(key)
        self._refresh_tab_title(key)
        self.status.config(text=f"{record.title} {'pinned' if record.pinned else 'set as navigation preview'}")

    def mark_editor_dirty(self, key: str, dirty: bool = True):
        if self.tab_policy.get(key):
            self.tab_policy.mark_dirty(key, dirty)
            self._refresh_tab_title(key)

    def _middle_click_close(self, event):
        key = self._tab_key_at(event.x, event.y)
        if key:
            self.workspace.select(self.tab_frames[key])
            self._close_tab_key(key)

    def _show_tab_menu(self, event):
        key = self._tab_key_at(event.x, event.y)
        if not key:
            return
        self.workspace.select(self.tab_frames[key])
        self.tab_menu.tk_popup(event.x_root, event.y_root)

    def _double_click_pin(self, event):
        key = self._tab_key_at(event.x, event.y)
        if key:
            self.workspace.select(self.tab_frames[key])
            self.toggle_current_tab_pin()

    def open_module(self, module_id: str):
        module = self.registry.get(module_id)
        if not module:
            return
        if module_id.startswith("plugin."):
            plugin_id = module_id.split(".", 1)[1]
            try:
                self.plugin_manager.open(plugin_id)
            except Exception as exc:
                self.write_output("ERROR", f"Plugin {plugin_id} failed to open: {exc}")
                messagebox.showerror("Plugin Error", f"The plugin could not open.\n\n{exc}", parent=self)
            return
        if module_id == "bundle_workbench":
            self.open_bundle_workbench()
            return
        asset_categories = {
            "assets": None,
            "monster_sprites": "Monster Sprites",
            "character_battle_sprites": "Character Battle Sprites",
            "character_field_sprites": "Character Field Sprites",
            "weapon_images": "Weapon Images",
            "armor_item_icons": "Armor & Item Icons",
            "bestiary_assets": "Bestiary Assets",
            "backgrounds": "Battle Backgrounds",
            "effects": "Spell & Battle Effects",
            "maps_field": "Maps & Field Assets",
            "ui_common": "UI & Common Graphics",
            "audio_assets": "Audio",
            "raw_resources": "Other Resources",
        }
        if module_id in asset_categories:
            return self.open_asset_browser(module_id, asset_categories[module_id])
        if module_id == "monsters":
            try:
                self.open_monster_editor()
            except Exception as exc:
                self.write_output("ERROR", f"Monster Editor failed to open: {exc}")
                messagebox.showerror("Monster Editor", str(exc), parent=self)
            return
        table_modules = {
            "weapons": ("weapon.csv", "Weapon Editor"),
            "armor": ("armor.csv", "Armor Editor"),

            "encounters": ("encount_area.csv", "Encounter Editor"),
        }
        if module_id == 'magic':
            try: return self.open_ability_editor()
            except Exception as exc: self.write_output('ERROR',f'Magic & Ability Designer failed: {exc}');messagebox.showerror('Magic & Ability Designer',str(exc),parent=self);return
        if module_id == 'items':
            try: return self.open_item_designer()
            except Exception as exc: self.write_output('ERROR',f'Item Designer failed: {exc}');messagebox.showerror('Item Designer',str(exc),parent=self);return
        if module_id in table_modules:
            filename, title = table_modules[module_id]
            try:
                self.open_table_editor(module_id, filename, title)
            except Exception as exc:
                self.write_output("ERROR", f"{title} failed to open: {exc}")
                messagebox.showerror(title, str(exc), parent=self)
            return
            return
        if module_id == "jobs":
            try:
                self.open_job_editor()
            except Exception as exc:
                self.write_output("ERROR", f"Job Editor failed to open: {exc}")
                messagebox.showerror("Job Editor", f"The Job Editor could not open.\n\n{exc}", parent=self)
            return
        key = f"module:{module_id}"
        existing = self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():
            self.workspace.select(existing)
        else:
            replace_key = self.tab_policy.replacement_candidate(exclude_key=key)
            if replace_key:
                self._close_tab_key(replace_key, force=True)
            frame = ttk.Frame(self.workspace, padding=18)
            ttk.Label(frame, text=module.display_name, style="Title.TLabel").pack(anchor="w")
            ttk.Label(frame, text=f"Category: {module.category}", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
            caps = ", ".join(sorted(module.capabilities)) or "None"
            ttk.Label(frame, text=f"Registered capabilities: {caps}", wraplength=760).pack(anchor="w")
            if module_id == "packages":
                ttk.Button(frame, text="Import Package…", command=self.import_package).pack(anchor="w", pady=(20, 4))
                ttk.Button(frame, text="Export / Share Package…", command=self.export_package).pack(anchor="w", pady=4)
            else:
                ttk.Label(frame, text="This module is registered and ready for its editor implementation.",
                          style="Muted.TLabel").pack(anchor="w", pady=20)
            self._add_managed_tab(key, module.display_name, frame, kind="module")
        caps = ", ".join(sorted(module.capabilities)) or "None"
        self._set_inspector(module.display_name, {
            "Module ID": module.module_id,
            "Category": module.category,
            "Capabilities": caps,
            "Status": "Registered",
        })


    def open_bundle_workbench(self):
        if not self.project:
            messagebox.showinfo("Bundle Workbench", "Open or create a Crystal Legacy project first.", parent=self)
            return
        key = "editor:bundle_workbench"
        existing = self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():
            self.workspace.select(existing); return
        replace_key = self.tab_policy.replacement_candidate(exclude_key=key)
        if replace_key: self._close_tab_key(replace_key, force=True)
        editor = BundleWorkbench(self.workspace, self.project.layout, self.write_output, self._set_inspector)
        self.editor_objects[key] = editor
        self._add_managed_tab(key, "Direct Game Bundles", editor, kind="editor")

    def open_asset_browser(self, module_id: str = "assets", category: str | None = None):
        if not self.project:
            messagebox.showinfo("Magicite Assets", "Open or create a Crystal Legacy project first.", parent=self)
            return
        export_root = self._magicite_export_root()
        if not export_root or not export_root.is_dir():
            messagebox.showerror("Magicite Assets", "The configured game does not contain StreamingAssets\\MagiciteExport.", parent=self)
            return
        key = f"asset:{module_id}"
        existing = self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():
            self.workspace.select(existing)
            return
        replace_key = self.tab_policy.replacement_candidate(exclude_key=key)
        if replace_key:
            self._close_tab_key(replace_key, force=True)
        editor = AssetBrowser(
            self.workspace,
            export_root,
            self.project.layout.working_overlays,
            initial_category=category,
            on_status=self.write_output,
            on_inspect=self._set_inspector,
            on_dirty=lambda dirty: self.mark_editor_dirty(key, dirty),
            on_saved=self.deploy_live_files,
        )
        self.editor_objects[key] = editor
        title = category or "All Magicite Assets"
        self._add_managed_tab(key, title, editor, kind="editor")
        self.write_output("PASS", f"Magicite Asset Catalog loaded {len(editor.records):,} files from {export_root}")

    def _magicite_export_root(self) -> Path | None:
        if not self.settings.game_root:
            return None
        return GameDetector().inspect(Path(self.settings.game_root), self.settings.active_game_profile).magicite_export

    def _current_data_source_root(self) -> Path | None:
        """Return the preferred overall source root for compatibility with older helpers."""
        if self.project and self.project.layout.active_has_mod_data():
            return self.project.layout.active_mod
        return self._magicite_export_root()

    def _csv_source_roots(self) -> list[tuple[str, Path]]:
        """Layered FFPR data sources, highest priority first.

        A live mod is commonly partial, so the presence of *some* live files must never
        prevent a missing table from falling back to the complete read-only export.
        """
        roots: list[tuple[str, Path]] = []
        if self.project:
            roots.append(("working copy", self.project.working_root / "Data" / "Master"))
            roots.append(("active Crystal Legacy mod", self.project.layout.active_mod))
        export = self._magicite_export_root()
        if export:
            roots.append(("read-only MagiciteExport", export))
        return roots

    def _locate_csv_source(self, filename: str) -> tuple[Path | None, str | None]:
        for label, root in self._csv_source_roots():
            found = locate_csv(root, filename)
            if found:
                return found, label
        return None, None

    def _locate_message_source(self, language: str = "en") -> tuple[Path | None, str | None]:
        roots: list[tuple[str, Path]] = []
        if self.project:
            roots.append(("working copy", self.project.working_root / "Data" / "Message"))
            roots.append(("active Crystal Legacy mod", self.project.layout.active_mod))
        export = self._magicite_export_root()
        if export:
            roots.append(("read-only MagiciteExport", export))
        for label, root in roots:
            found = locate_message_file(root, language)
            if found:
                return found, label
        return None, None

    def open_job_editor(self):
        if not self.project:
            messagebox.showinfo(
                "Job Editor",
                "Open or create a Crystal Legacy project first.",
                parent=self,
            )
            return
        key = "editor:jobs"
        existing = self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():
            self.workspace.select(existing)
            return

        source, source_label = self._locate_csv_source("job.csv")
        project_csv = self.project.working_root / "Data" / "Master" / "job.csv"
        if not project_csv.exists():
            if not source:
                messagebox.showerror(
                    "Job Editor",
                    "job.csv could not be found in MagiciteExport.\n\n"
                    "Verify the FF1PR setup path or place job.csv under Data\\Master in the project.",
                    parent=self,
                )
                self.write_output("ERROR", "Job Editor could not locate job.csv.")
                return
            project_csv = ensure_project_copy(self.project.working_root, source, "job.csv")
            self.write_output("INFO", f"Created editable project copy of job.csv from {source}")

        try:
            document = CsvDocument.load(project_csv, source_path=source)
        except Exception as exc:
            messagebox.showerror("Job Editor", str(exc), parent=self)
            self.write_output("ERROR", f"Could not load job.csv: {exc}")
            return

        replace_key = self.tab_policy.replacement_candidate(exclude_key=key)
        if replace_key:
            self._close_tab_key(replace_key, force=True)

        original_message_path, message_source_label = self._locate_message_source("en")
        project_message_path = self.project.working_root / "Data" / "Message" / "system_en.txt"
        if not project_message_path.exists() and original_message_path:
            project_message_path = ensure_project_message_copy(self.project.working_root, original_message_path, "en")
            self.write_output("INFO", f"Created editable project copy of system_en.txt from {original_message_path}")
        if project_message_path.exists():
            try:
                message_catalog = MessageCatalog.load(project_message_path, "en")
                self.write_output("PASS", f"Loaded {len(message_catalog.entries)} editable English translations from {project_message_path}")
            except Exception as exc:
                message_catalog = MessageCatalog(source_path=project_message_path)
                self.write_output("WARNING", f"Could not load project system_en.txt: {exc}")
        else:
            message_catalog = MessageCatalog(source_path=project_message_path)
            self.write_output("WARNING", "system_en.txt was not found; a project translation file will be created when text is saved.")

        status_source, status_source_label = self._locate_csv_source("character_status.csv")
        status_document = None
        if status_source:
            try:
                status_project = ensure_project_copy(self.project.working_root, status_source, "character_status.csv")
                status_document = CsvDocument.load(status_project, source_path=status_source)
                self.write_output("PASS", f"Loaded {len(status_document.rows)} character-status records from {status_project}")
            except Exception as exc:
                self.write_output("WARNING", f"Could not load character_status.csv: {exc}")
        else:
            self.write_output("WARNING", "character_status.csv was not found; real starting stats cannot be edited.")

        def load_related_csv(filename):
            source_path, source_label = self._locate_csv_source(filename)
            if not source_path:
                self.write_output("WARNING", f"{filename} was not found; related features are unavailable.")
                return None
            try:
                project_path = ensure_project_copy(self.project.working_root, source_path, filename)
                return CsvDocument.load(project_path, source_path=source_path)
            except Exception as exc:
                self.write_output("WARNING", f"Could not load {filename}: {exc}")
                return None

        weapon_document = load_related_csv("weapon.csv")
        armor_document = load_related_csv("armor.csv")
        job_group_document = load_related_csv("job_group.csv")

        editor = JobEditor(
            self.workspace,
            document,
            on_dirty=lambda dirty: self.mark_editor_dirty(key, dirty),
            on_status=self.write_output,
            on_inspect=self._set_inspector,
            message_catalog=message_catalog,
            command_choices=command_choices(self._current_data_source_root(), message_catalog),
            growth_provider=lambda job_id: load_growth(self.project.working_root, self._current_data_source_root(), job_id),
            status_document=status_document,
            weapon_document=weapon_document,
            armor_document=armor_document,
            job_group_document=job_group_document,
            on_saved=self.deploy_live_files,
            export_root=self._magicite_export_root(),
            working_overlays=self.project.working_root / "Overlays",
            bundle_root=self.project.root / "FINAL FANTASY_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64",
        )
        self.editor_objects[key] = editor
        self._add_managed_tab(key, "Job Editor", editor, kind="editor")
        self._set_inspector("Job Editor", {
            "Rows": len(document.rows),
            "Fields": len(document.fieldnames),
            "Project CSV": document.path,
            "Original source": source or "Project copy only",
            "Safety": "MagiciteExport remains read-only",
            "Project translation file": project_message_path,
            "Original translation source": original_message_path or "Not found",
            "Translation entries": len(message_catalog.entries),
        })
        self.write_output("PASS", f"Job Editor loaded {len(document.rows)} rows.")

    def open_monster_editor(self):
        if not self.project:
            messagebox.showinfo("Monster Editor","Open a project first.",parent=self); return
        key="editor:monsters"
        if key in self.tab_frames and str(self.tab_frames[key]) in self.workspace.tabs():
            self.workspace.select(self.tab_frames[key]); return
        source, source_label=self._locate_csv_source("monster.csv")
        if not source: raise FileNotFoundError("monster.csv was not found.")
        doc=CsvDocument.load(ensure_project_copy(self.project.working_root,source,"monster.csv"),source_path=source)
        original, original_label=self._locate_message_source("en")
        msgpath=ensure_project_message_copy(self.project.working_root,original,"en") if original else self.project.working_root/"Data"/"Message"/"system_en.txt"
        messages=MessageCatalog.load(msgpath,"en") if msgpath.exists() else MessageCatalog(source_path=msgpath)
        rep=self.tab_policy.replacement_candidate(exclude_key=key)
        if rep:self._close_tab_key(rep,force=True)
        editor=MonsterEditor(self.workspace,doc,messages,lambda d:self.mark_editor_dirty(key,d),self.write_output,self._set_inspector,
                             export_root=self._magicite_export_root(), working_overlays=self.project.working_root / "Overlays", on_saved=self.deploy_live_files)
        self.editor_objects[key]=editor;self._add_managed_tab(key,"Monster Editor",editor,kind="editor")
        self.write_output("PASS",f"Monster Editor loaded {len(doc.rows)} rows.")



    def open_encounter_editor(self):
        if not self.project:
            messagebox.showinfo("Encounter Designer", "Open a project first.", parent=self); return
        key="editor:encounters"
        if key in self.tab_frames and str(self.tab_frames[key]) in self.workspace.tabs():
            self.workspace.select(self.tab_frames[key]); return
        def load(name):
            source, source_label=self._locate_csv_source(name)
            if not source: raise FileNotFoundError(f"{name} was not found.")
            return CsvDocument.load(ensure_project_copy(self.project.working_root,source,name),source_path=source)
        area=load("encount_area.csv"); sets=load("monster_set.csv"); parties=load("monster_party.csv"); monsters=load("monster.csv"); area_names=load("area.csv"); maps=load("map.csv")
        original, original_label=self._locate_message_source("en")
        msgpath=ensure_project_message_copy(self.project.working_root,original,"en") if original else self.project.working_root/"Data"/"Message"/"system_en.txt"
        messages=MessageCatalog.load(msgpath,"en") if msgpath.exists() else MessageCatalog(source_path=msgpath)
        rep=self.tab_policy.replacement_candidate(exclude_key=key)
        if rep:self._close_tab_key(rep,force=True)
        editor=EncounterEditor(self.workspace,area,sets,parties,monsters,messages,lambda d:self.mark_editor_dirty(key,d),self.write_output,self._set_inspector,area_names,maps)
        self.editor_objects[key]=editor;self._add_managed_tab(key,"Encounter Designer",editor,kind="editor")
        self.write_output("PASS",f"Encounter Designer loaded {len(area.rows)} areas, {len(sets.rows)} sets, and {len(parties.rows)} formations.")


    def _load_project_csv(self, name):
        source, source_label = self._locate_csv_source(name)
        if not source:
            searched = "\n".join(f"- {root}" for _, root in self._csv_source_roots())
            raise FileNotFoundError(
                f"{name} was not found in the working copy, active mod, or MagiciteExport.\n\nSearched:\n{searched}"
            )
        project_path = ensure_project_copy(self.project.working_root, source, name)
        if source_label == "read-only MagiciteExport" and project_path == self.project.working_root / "Data" / "Master" / name:
            self.write_output("INFO", f"Created missing editable {name} from read-only MagiciteExport: {source}")
        return CsvDocument.load(project_path, source_path=source)

    def _project_messages(self):
        original, original_label=self._locate_message_source('en');path=self.project.working_root/'Data'/'Message'/'system_en.txt'
        if not path.exists() and original:path=ensure_project_message_copy(self.project.working_root,original,'en')
        return MessageCatalog.load(path,'en') if path.exists() else MessageCatalog(source_path=path)

    def open_ability_editor(self):
        if not self.project: messagebox.showinfo('Magic & Ability Designer','Open a project first.',parent=self);return
        key='editor:magic';existing=self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():self.workspace.select(existing);return
        ability=self._load_project_csv('ability.csv');jobs=self._load_project_csv('job.csv');groups=self._load_project_csv('job_group.csv');messages=self._project_messages();rep=self.tab_policy.replacement_candidate(exclude_key=key)
        if rep:self._close_tab_key(rep,force=True)
        editor=AbilityEditor(self.workspace,ability,jobs,groups,messages,lambda d:self.mark_editor_dirty(key,d),self.write_output,self._set_inspector,on_saved=self.deploy_live_files);self.editor_objects[key]=editor;self._add_managed_tab(key,'Magic & Ability Designer',editor,kind='editor');self.write_output('PASS',f'Magic & Ability Designer loaded {len(ability.rows)} abilities.')

    def open_item_designer(self):
        if not self.project: messagebox.showinfo('Item Designer','Open a project first.',parent=self);return
        key='editor:items';existing=self.tab_frames.get(key)
        if existing and str(existing) in self.workspace.tabs():self.workspace.select(existing);return
        item=self._load_project_csv('item.csv');messages=self._project_messages();rep=self.tab_policy.replacement_candidate(exclude_key=key)
        if rep:self._close_tab_key(rep,force=True)
        editor=ItemDesigner(self.workspace,item,messages,self.project.working_root,lambda d:self.mark_editor_dirty(key,d),self.write_output,self._set_inspector);self.editor_objects[key]=editor;self._add_managed_tab(key,'Item & Key Item Designer',editor,kind='editor');self.write_output('PASS',f'Item Designer loaded {len(item.rows)} consumables and 17 key-item labels.')

    def open_table_editor(self, module_id: str, filename: str, title: str):
        if not self.project:
            messagebox.showinfo(title, "Open a project first.", parent=self)
            return
        if module_id == "encounters":
            return self.open_encounter_editor()
        key = f"editor:{module_id}"
        if key in self.tab_frames and str(self.tab_frames[key]) in self.workspace.tabs():
            self.workspace.select(self.tab_frames[key])
            return
        source, source_label = self._locate_csv_source(filename)
        if not source:
            raise FileNotFoundError(f"{filename} was not found in the working copy, active mod, or MagiciteExport.")
        document = CsvDocument.load(
            ensure_project_copy(self.project.working_root, source, filename),
            source_path=source,
        )
        replace_key = self.tab_policy.replacement_candidate(exclude_key=key)
        if replace_key:
            self._close_tab_key(replace_key, force=True)
        message_catalog = None
        prefix = {"weapons": "MSG_WEAPON_NAME_", "armor": "MSG_ARMOR_NAME_", "items": "MSG_ITEM_NAME_"}.get(module_id)
        if prefix:
            msg_path = self.project.working_root / "Data" / "Message" / "system_en.txt"
            if not msg_path.exists():
                original, original_label = self._locate_message_source("en")
                if original:
                    msg_path = ensure_project_message_copy(self.project.working_root, original, "en")
            if msg_path.exists():
                message_catalog = MessageCatalog.load(msg_path, "en")
        editor = TableEditor(
            self.workspace,
            title,
            document,
            lambda dirty: self.mark_editor_dirty(key, dirty),
            self.write_output,
            self._set_inspector,
            message_catalog=message_catalog,
            message_prefix=prefix,
            on_saved=self.deploy_live_files,
        )
        self.editor_objects[key] = editor
        self._add_managed_tab(key, title, editor, kind="editor")
        self.write_output("PASS", f"{title} loaded {len(document.rows)} rows from {filename}.")

    def deploy_live_files(self):
        """Deploy already-saved project files to the active Magicite folder.

        This method deliberately does not call save_project, so editor Save buttons
        can save their documents and immediately deploy without recursion.
        """
        if not self.project:
            return None
        try:
            result = MagiciteDeployer().deploy(self.project.working_root, self.project.root, self.project.manifest.game_profile)
            self.write_output("PASS", f"Directly wrote and verified {len(result.files)} files to {result.destination}")
            self.write_output("INFO", f"Live Master path: {result.destination / MagiciteDeployer.MASTER_REL}")
            for live_file in result.files:
                self.write_output("WRITE", str(live_file))
            for notice in result.notices:
                self.write_output("WARNING", notice)
            self.write_output("INFO", f"Deployment report: {result.report}")
            self.status.config(text="Saved and deployed to game")
            return result
        except Exception as exc:
            self.write_output("ERROR", f"Live deployment failed: {exc}")
            messagebox.showerror("Deploy to Game", str(exc), parent=self)
            return None

    def deploy_project(self):
        if not self.project:
            return None
        if not self.save_project(deploy=False):
            return None
        return self.deploy_live_files()

    def launch_game(self):
        try:
            if not self.deploy_project():return
            MagiciteDeployer().launch(Path(self.settings.game_root), self.settings.active_game_profile)
            self.write_output("PASS","FINAL FANTASY launched.")
        except Exception as exc:
            self.write_output("ERROR",f"Launch failed: {exc}")
            messagebox.showerror("Launch Game",str(exc),parent=self)

    def _set_inspector(self, title: str, fields: dict):
        self.inspector_title.config(text=title)
        self.inspector_text.configure(state="normal")
        self.inspector_text.delete("1.0", "end")
        for key, value in fields.items():
            self.inspector_text.insert("end", f"{key}\n", ("heading",))
            self.inspector_text.insert("end", f"{value}\n\n")
        self.inspector_text.tag_configure("heading", foreground=DARK["accent"], font=("Segoe UI", 9, "bold"))
        self.inspector_text.configure(state="disabled")

    def _maybe_run_setup(self):
        if not self.settings.setup_completed: SetupWizard(self,self.settings,self._setup_complete)

    def _setup_complete(self,installation):
        self.settings_store.save(self.settings)
        profile=get_profile(installation.profile_id)
        self.active_profile_var.set(profile.display_name)
        self._populate_tree()
        self.write_output("PASS",f"{profile.display_name} game root configured: {installation.root}")
        self.write_output("PASS",f"BepInEx working root: {Path(installation.root) / 'BepInEx' / 'Crystal Legacy' / 'Working'}")
        self.write_output("PASS",f"Read-only reference root: {installation.magicite_export}")
        self.write_output("PASS",f"Live deployment root: {installation.magicite_dir / 'Crystal Legacy'}")

    def configure_game(self): SetupWizard(self,self.settings,self._setup_complete)

    def new_project(self):
        if not self.settings.setup_completed:
            SetupWizard(self,self.settings,lambda installation: NewProjectDialog(self,self.settings,self._project_loaded)); return
        NewProjectDialog(self,self.settings,self._project_loaded)

    def choose_open_project(self):
        profile=get_profile(self.settings.active_game_profile)
        chosen = filedialog.askdirectory(title=f"Select {profile.display_name} game root", initialdir=self.settings.game_installations.get(profile.profile_id) or None)
        if chosen:
            try:self.open_project(Path(chosen), profile.profile_id)
            except Exception as exc:messagebox.showerror("Open Project", str(exc), parent=self)

    def open_project(self, root: Path, profile_id: str | None = None):
        profile_id=profile_id or self.settings.active_game_profile
        installation = GameDetector().inspect(root, profile_id)
        if not installation.is_valid_crystal_legacy_root:
            profile=get_profile(profile_id)
            raise RuntimeError(f"The selected folder must be a complete {profile.display_name} root containing its executable, BepInEx, StreamingAssets\\Magicite, and StreamingAssets\\MagiciteExport.")
        self.settings.active_game_profile=profile_id
        self.settings.game_installations[profile_id]=str(installation.root)
        self.settings.game_root = str(installation.root)
        self.settings.workspace_root = str(installation.root / "BepInEx" / "Crystal Legacy" / "Working")
        project = ProjectService().open(installation.root)
        if project.manifest.game_profile != profile_id:
            raise RuntimeError(f"This working project belongs to {get_profile(project.manifest.game_profile).display_name}, not {get_profile(profile_id).display_name}.")
        self._project_loaded(project)

    def _active_profile_changed(self,_event=None):
        profile=PROFILE_BY_DISPLAY[self.active_profile_var.get()]
        self.settings.active_game_profile=profile.profile_id
        root=self.settings.game_installations.get(profile.profile_id,'')
        self.settings.game_root=root
        self.settings.workspace_root=str(Path(root)/'BepInEx'/'Crystal Legacy'/'Working') if root else ''
        self.settings_store.save(self.settings)
        self.project=None
        self.project_label.config(text=f"{profile.display_name} — no project open")
        self.title(f"Crystal Legacy Studio — {profile.display_name}")
        self._populate_tree()
        self.write_output("INFO",f"Active game profile changed to {profile.display_name}.")
        if root:
            manifest=GameProjectLayout(Path(root),profile.profile_id).working_root/'crystal-project.json'
            if manifest.exists():
                try:self.open_project(Path(root),profile.profile_id)
                except Exception as exc:self.write_output('ERROR',f'Could not open saved {profile.display_name} project: {exc}')
        else:
            messagebox.showinfo('Game path not configured',f'Use View > Game Installations & Active Profile to browse to the {profile.display_name} root.',parent=self)

    def show_active_game_paths(self):
        profile=get_profile(self.settings.active_game_profile); root=self.settings.game_installations.get(profile.profile_id,'Not configured')
        if root=='Not configured':
            messagebox.showinfo('Active Game Paths',f'{profile.display_name} is not configured.',parent=self); return
        layout=GameProjectLayout(Path(root),profile.profile_id)
        messagebox.showinfo('Active Game Paths',f"Active profile: {profile.display_name}\n\nGame root:\n{layout.game_root}\n\nRead-only references:\n{layout.magicite_export}\n\nWorking copy:\n{layout.working_root}\n\nLive deployment:\n{layout.active_mod}\n\nImport packages:\n{layout.import_dir}\n\nExport packages:\n{layout.export_dir}",parent=self)

    def _project_loaded(self, project: Project):
        self.project = project
        self.settings.active_game_profile=project.manifest.game_profile
        self.settings.game_installations[project.manifest.game_profile]=str(project.root)
        self.settings.game_root=str(project.root)
        self.active_profile_var.set(get_profile(project.manifest.game_profile).display_name)
        self._populate_tree()
        self.settings.last_project = str(project.root)
        self.settings.recent_projects=([str(project.root)]+[p for p in self.settings.recent_projects if p != str(project.root)])[:10]
        self.settings_store.save(self.settings)
        self.project_label.config(text=f"{project.manifest.name}  {project.manifest.version}")
        self.title(f"{project.manifest.name} — Crystal Legacy Studio")
        self.write_output("INFO", f"Opened project: {project.root}")
        if project.layout.active_has_mod_data():
            self.write_output("PASS", f"Current project state loaded from live mod: {project.layout.active_mod}")
        else:
            self.write_output("INFO", f"No live Crystal Legacy mod found; untouched references will be read from {project.layout.magicite_export}")
        self._set_inspector(project.manifest.name, {
            "Project ID": project.manifest.project_id,
            "Version": project.manifest.version,
            "Game Profile": project.manifest.game_profile,
            "Game root": project.root,
            "Working copy": project.working_root,
            "Read-only references": project.layout.magicite_export,
            "Live deployment": project.layout.active_mod,
            "Package import": project.layout.import_dir,
            "Package export": project.layout.export_dir,
        })
        self.after(100, self._verify_active_against_working)

    def _verify_active_against_working(self):
        """Check live Magicite deployment against the BepInEx working copy on open."""
        if not self.project:
            return
        try:
            result = self.project.layout.compare_working_to_active()
            if result["matches"]:
                self.write_output("PASS", f"Startup integrity check passed: working copy matches {self.project.layout.active_mod}")
                return
            missing = len(result["missingActive"])
            extra = len(result["extraActive"])
            changed = len(result["changed"])
            self.write_output("WARNING", f"Startup integrity mismatch: {missing} missing, {extra} extra, {changed} changed live file(s).")
            details = (
                f"The active Crystal Legacy mod differs from the BepInEx working copy.\n\n"
                f"Missing live files: {missing}\nChanged live files: {changed}\nExtra live files: {extra}\n\n"
                "Yes: back up the active mod and restore it from the working copy.\n"
                "No: back up the working copy and adopt the active mod as the new working copy.\n"
                "Cancel: leave both unchanged."
            )
            answer = messagebox.askyesnocancel("Crystal Legacy integrity check", details, parent=self)
            if answer is True:
                backup = self.project.layout.timestamped_backup(self.project.layout.active_mod, "StartupMismatch/Active")
                deployed = self.deploy_live_files()
                if deployed:
                    self.write_output("PASS", f"Restored active mod from working copy. Backup: {backup}")
            elif answer is False:
                backup = self.project.layout.timestamped_backup(self.project.working_root, "StartupMismatch/Working")
                self._adopt_active_as_working()
                self.write_output("PASS", f"Adopted active mod as working copy. Backup: {backup}")
            else:
                self.write_output("WARNING", "Integrity mismatch left unresolved by user.")
        except Exception as exc:
            self.write_output("ERROR", f"Startup integrity check failed: {exc}")

    def _adopt_active_as_working(self):
        if not self.project:
            return
        counts = self.project.layout.adopt_active_as_working()
        self.write_output(
            "PASS",
            f"Loaded current live mod into working copy: {counts['master']} Master, "
            f"{counts['message']} Message, {counts['overlays']} overlay file(s).",
        )

    def save_project(self, deploy=True):
        if not self.project:
            self.write_output("WARNING", "No project is open.")
            return False
        try:
            # Suppress editor-level deploy callbacks during a toolbar-wide save.
            callbacks = []
            for editor in self.editor_objects.values():
                if hasattr(editor, "on_saved"):
                    callbacks.append((editor, editor.on_saved))
                    editor.on_saved = None
            try:
                for key, editor in list(self.editor_objects.items()):
                    record = self.tab_policy.get(key)
                    if record and record.dirty and hasattr(editor, "save_changes"):
                        if not editor.save_changes():
                            self.write_output("WARNING", f"Save cancelled for {record.title}.")
                            return False
            finally:
                for editor, callback in callbacks:
                    editor.on_saved = callback
            self.project.save()
            self.write_output("INFO", "Project saved.")
            if deploy:
                return bool(self.deploy_live_files())
            self.status.config(text="Project saved")
            return True
        except Exception as exc:
            self.write_output("ERROR", f"Save failed: {exc}")
            messagebox.showerror("Save Project", str(exc), parent=self)
            return False

    def validate_project(self):
        if not self.project:
            self.write_output("WARNING", "No project is open.")
            return
        issues = []
        if not self.project.manifest_path.exists():
            issues.append("Project manifest is missing.")
        if self.project.root != Path(self.settings.game_installations.get(self.project.manifest.game_profile, self.settings.game_root)).expanduser().resolve():
            issues.append("Project root must match the configured root for its active Pixel Remaster game profile.")
        if issues:
            for issue in issues:
                self.write_output("ERROR", issue)
            self.status.config(text=f"Validation failed: {len(issues)} issue(s)")
        else:
            self.write_output("PASS", "Project validation completed successfully.")
            self.status.config(text="Validation passed")

    def _choose_import_conflicts(self, analysis):
        """Return approved conflict IDs, or None when the user cancels."""
        if not analysis.conflicts:
            return set()
        dialog = tk.Toplevel(self)
        dialog.title("Review import conflicts")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("940x600")
        dialog.minsize(760, 460)
        result = {"value": None}

        ttk.Label(dialog, text="Choose which existing data the imported mod may replace.",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(14, 3))
        ttk.Label(dialog, text=(
            "New items, monsters, text and assets are imported automatically. "
            "Only checked conflicts overwrite your current project."
        )).pack(anchor="w", padx=14, pady=(0, 10))

        outer = ttk.Frame(dialog)
        outer.pack(fill="both", expand=True, padx=14)
        tree = ttk.Treeview(outer, columns=("use", "type", "name", "current", "incoming"), show="headings", selectmode="extended")
        widths = {"use": 55, "type": 95, "name": 275, "current": 220, "incoming": 220}
        labels = {"use": "Import", "type": "Type", "name": "Affected data", "current": "Current", "incoming": "Incoming"}
        for col in tree["columns"]:
            tree.heading(col, text=labels[col])
            tree.column(col, width=widths[col], minwidth=45, stretch=col in {"name", "current", "incoming"})
        scroll = ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        approved = set()
        by_item = {}
        for index, conflict in enumerate(analysis.conflicts):
            item = tree.insert("", "end", values=("No", conflict.kind, conflict.display_name,
                                                  conflict.current_summary, conflict.incoming_summary))
            by_item[item] = conflict

        def set_items(items, value):
            for item in items:
                conflict = by_item[item]
                values = list(tree.item(item, "values"))
                values[0] = "Yes" if value else "No"
                tree.item(item, values=values)
                if value:
                    approved.add(conflict.conflict_id)
                else:
                    approved.discard(conflict.conflict_id)

        def toggle(event=None):
            items = tree.selection()
            if not items:
                item = tree.focus()
                items = (item,) if item else ()
            for item in items:
                conflict = by_item[item]
                set_items((item,), conflict.conflict_id not in approved)

        tree.bind("<Double-1>", toggle)
        tree.bind("<space>", toggle)

        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=14, pady=12)
        ttk.Button(actions, text="Approve Selected", command=lambda: set_items(tree.selection(), True)).pack(side="left")
        ttk.Button(actions, text="Ignore Selected", command=lambda: set_items(tree.selection(), False)).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Approve All", command=lambda: set_items(tuple(by_item), True)).pack(side="left", padx=(18, 0))
        ttk.Button(actions, text="Ignore All", command=lambda: set_items(tuple(by_item), False)).pack(side="left", padx=(6, 0))

        def finish():
            result["value"] = set(approved)
            dialog.destroy()

        def cancel():
            result["value"] = None
            dialog.destroy()

        ttk.Button(actions, text="Cancel", command=cancel).pack(side="right")
        ttk.Button(actions, text="Continue Import", command=finish).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(dialog)
        return result["value"]

    def import_package(self):
        if not self.project:
            messagebox.showinfo("Import Mod", "Open or create a project first.", parent=self)
            return
        chosen = filedialog.askopenfilename(
            parent=self,
            title="Import a Crystal Legacy or Nexus Magicite mod",
            initialdir=str(self.project.layout.import_dir),
            filetypes=[("Supported mods", "*.crystalpackage *.zip"), ("Crystal Legacy packages", "*.crystalpackage"), ("Nexus / Magicite ZIP mods", "*.zip"), ("All files", "*.*")],
        )
        if not chosen:
            return
        try:
            importer = PackageImporter()
            analysis = importer.analyze_any(self.project, Path(chosen))
            approved = self._choose_import_conflicts(analysis)
            if approved is None:
                self.write_output("INFO", "Mod import cancelled.")
                return
            summary = (
                f"New files: {len(analysis.new_files)}\n"
                f"New data records: {analysis.new_records}\n"
                f"Already identical: {len(analysis.identical_files) + analysis.identical_records}\n"
                f"Approved replacements: {len(approved)}\n"
                f"Ignored replacements: {len(analysis.conflicts) - len(approved)}\n\n"
                "Create a complete backup before merging?"
            )
            backup = messagebox.askyesnocancel("Import mod", summary, parent=self)
            if backup is None:
                self.write_output("INFO", "Mod import cancelled.")
                return
            result = importer.import_any(self.project, Path(chosen), backup=bool(backup), approved_conflicts=approved)
            self.write_output("PASS", f"Imported {len(result.imported_files)} working file(s) and added {result.records_added} data record(s).")
            self.write_output("INFO", f"Approved replacements: {result.conflicts_overwritten}; ignored conflicts: {result.conflicts_ignored}.")
            if result.backup:
                self.write_output("INFO", f"Pre-import backup: {result.backup}")
            self.deploy_live_files()
        except Exception as exc:
            self.write_output("ERROR", f"Mod import failed: {exc}")
            messagebox.showerror("Import Mod", str(exc), parent=self)

    def export_package(self):
        if not self.project:
            messagebox.showinfo("Export Package", "Open or create a project first.", parent=self)
            return
        ExportPackageDialog(self, self.project, self._package_complete)

    def _package_complete(self, result):
        self.write_output("PASS", f"Verified package created: {result.package_path}")
        self.write_output("INFO", f"Package ID: {result.package_id}")
        self.write_output("INFO", f"Files: {result.file_count}")
        self.write_output("INFO", f"SHA-256: {result.package_sha256}")
        self.status.config(text="Verified package created")
        messagebox.showinfo("Package Complete", f"Verified package created:\n{result.package_path}", parent=self)

    def write_output(self, level: str, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.output.insert("end", f"{timestamp} [{level}] {message}\n")
        self.output.see("end")
        getattr(self.logger, "error" if level == "ERROR" else "warning" if level == "WARNING" else "info")(message)

    def clear_output(self):
        self.output.delete("1.0", "end")

    def show_about(self):
        messagebox.showinfo("About Crystal Legacy Studio",
                            f"Crystal Legacy Studio\nVersion {__version__}\n\n"
                            "An extensible IDE for Final Fantasy I Pixel Remaster modding.",
                            parent=self)

    def _on_close(self):
        self.settings.window_geometry = self.geometry()
        self.settings_store.save(self.settings)
        self.logger.info("Studio closed")
        self.destroy()
