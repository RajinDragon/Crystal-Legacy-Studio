from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from crystal_legacy_studio.ui.theme import DARK
from crystal_legacy_studio.ui.widgets.field_labels import friendly_label
from crystal_legacy_studio.ui.widgets.growth_graph import GrowthGraph
from crystal_legacy_studio.localization.catalog import MessageCatalog
from crystal_legacy_studio.editors.reference_choices import Choice
from crystal_legacy_studio.editors.growth_model import CALC_FIELDS, apply_generated_curve
from crystal_legacy_studio.editors.curve_profiles import CURVE_TYPES, CurveRequest, generate_curve
from crystal_legacy_studio.editors.growth_profiles import GrowthDesign, GrowthProfileStore
from crystal_legacy_studio.editors.permission_slots import permission_field_for_job, permission_slot_for_job
from crystal_legacy_studio.editors.hp_growth import (
    flags_for_target, project_hp, write_strong_hp_flags
)
from crystal_legacy_studio.editors.archetype_builder import (
    ROLE_WEIGHTS, build_archetype_plan
)
from crystal_legacy_studio.editors.linked_assets import LinkedAssetPanel
from crystal_legacy_studio.editors.sprite_sets import SpriteSetLibrary, SpriteSetSelector

class JobEditor(ttk.Frame):
    COMMAND_FIELDS = [f"change_command_{index}" for index in range(1, 6)]

    def __init__(
        self, parent, document, *, on_dirty, on_status, on_inspect,
        message_catalog=None, command_choices=None, growth_provider=None, status_document=None,
        weapon_document=None, armor_document=None, job_group_document=None, on_saved=None,
        export_root=None, working_overlays=None, bundle_root=None
    ):
        super().__init__(parent)
        self.document = document
        self.on_dirty = on_dirty
        self.on_status = on_status
        self.on_inspect = on_inspect
        self.messages = message_catalog or MessageCatalog()
        self.commands = command_choices or [Choice("0", "None / No command")]
        self.command_by_value = {choice.value: choice for choice in self.commands}
        self.growth_provider = growth_provider
        self.status_document = status_document
        self.weapon_document = weapon_document
        self.armor_document = armor_document
        self.job_group_document = job_group_document
        self.on_saved = on_saved
        self.export_root = export_root
        self.working_overlays = working_overlays
        self.bundle_root = bundle_root
        self.equipment_trees = {}
        self.current_status = None
        self.status_vars = {}
        self.status_widgets = {}
        self.growth = None
        self.current = None
        self.indices = []
        self.loading = False
        self.vars = {}
        self.texts = {}
        self.role_vars = {role: tk.BooleanVar(value=False) for role in ROLE_WEIGHTS}
        self.budget_var = tk.IntVar(value=420)
        self.project_root = self.document.path.parents[2]
        self.growth_profiles = GrowthProfileStore(self.project_root)
        self._build()
        self.refresh()
        if self.indices:
            self.list.selection_set(0)
            self.select(0)

    def _build(self):
        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Job Designer", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Save All Job Changes", command=self.save).pack(side="right")
        ttk.Button(header, text="Validate", command=self.validate).pack(side="right", padx=6)

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(pane, padding=8)
        right = ttk.Frame(pane, padding=8)
        pane.add(left, weight=1)
        pane.add(right, weight=4)

        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=(0, 8))

        self.list = tk.Listbox(
            left, bg=DARK["panel"], fg=DARK["fg"],
            selectbackground=DARK["selection"], relief="flat", exportselection=False
        )
        self.list.pack(fill="both", expand=True)
        self.list.bind("<<ListboxSelect>>", self._selected)

        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Add", command=self.add).pack(side="left")
        ttk.Button(buttons, text="Duplicate", command=self.duplicate).pack(side="left", padx=4)
        ttk.Button(buttons, text="Delete", command=self.delete).pack(side="left")

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.bind('<<NotebookTabChanged>>', self._tab_changed)
        self.details_tab = ttk.Frame(self.tabs)
        self.base_stats_tab = ttk.Frame(self.tabs)
        self.battle_stats_tab = ttk.Frame(self.tabs)
        self.magic_tab = ttk.Frame(self.tabs)
        self.equipment_tab = ttk.Frame(self.tabs)
        self.commands_tab = ttk.Frame(self.tabs)
        self.class_tab = ttk.Frame(self.tabs)
        self.graph_tab = ttk.Frame(self.tabs)
        self.advanced_tab = ttk.Frame(self.tabs)
        self.sprite_sets_tab = ttk.Frame(self.tabs)
        self.battle_sprites_tab = ttk.Frame(self.tabs)
        self.field_sprites_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.details_tab, text="Identity")
        self.tabs.add(self.base_stats_tab, text="Base Stats")
        self.tabs.add(self.battle_stats_tab, text="Battle & Defense")
        self.tabs.add(self.magic_tab, text="Magic & Starting Kit")
        self.tabs.add(self.equipment_tab, text="Equipment")
        self.tabs.add(self.commands_tab, text="Job Commands")
        self.tabs.add(self.class_tab, text="Class Designer")
        self.tabs.add(self.graph_tab, text="Growth Graph")
        self.tabs.add(self.advanced_tab, text="Advanced Growth Table")
        self.tabs.add(self.sprite_sets_tab, text="Sprite Set")

        self._build_details()
        self._build_status_tabs()
        self._build_equipment_tab()
        self._build_commands()
        self._build_class_designer()
        self.battle_assets = None
        self.field_assets = None
        self.sprite_selector = None
        if self.export_root and self.working_overlays:
            library = SpriteSetLibrary(self.project_root, self.export_root, self.working_overlays, self.bundle_root)
            self.sprite_selector = SpriteSetSelector(
                self.sprite_sets_tab, library, on_status=self.on_status, on_dirty=self.on_dirty)
            self.sprite_selector.pack(fill='both', expand=True)
        else:
            ttk.Label(self.sprite_sets_tab, text='MagiciteExport sprite references are unavailable.').pack(padx=12,pady=12)


    def _tab_changed(self, _event=None):
        if getattr(self, 'sprite_selector', None) and self.current is not None:
            # Leaving the Sprite Set tab commits the pending appearance without
            # immediately deploying the whole project.
            selected = self.tabs.select()
            if selected and self.tabs.tab(selected, 'text') != 'Sprite Set':
                try:
                    self.sprite_selector.commit_pending()
                except Exception as exc:
                    self.on_status('ERROR', f'Could not stage pending sprite selection: {exc}')

    def _scroll_form(self, parent):
        canvas = tk.Canvas(parent, bg=DARK["panel"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return form

    def _build_details(self):
        form = self._scroll_form(self.details_tab)
        # These zero-filled compatibility fields exist in job.csv but the real
        # starting values live in character_status.csv. Hide them here so the
        # class designer does not present misleading blank/zero stats.
        excluded = set(self.COMMAND_FIELDS) | {"initial_condition", "strength", "vitality", "agility", "magic"}
        row_index = 0
        for field in self.document.fieldnames:
            if field in excluded:
                continue
            ttk.Label(form, text=friendly_label(field)).grid(
                row=row_index, column=0, sticky="w", padx=5, pady=4
            )
            variable = tk.StringVar()
            variable.trace_add("write", lambda *_args, key=field: self.changed(key))
            self.vars[field] = variable
            ttk.Entry(form, textvariable=variable).grid(
                row=row_index, column=1, sticky="ew", padx=5, pady=4
            )
            row_index += 1

            if field.startswith("mes_id"):
                ttk.Label(form, text="English text", foreground=DARK["accent"]).grid(
                    row=row_index, column=0, sticky="nw", padx=5, pady=4
                )
                text = tk.Text(
                    form, height=4 if "description" in field else 2, wrap="word",
                    bg=DARK["panel2"], fg=DARK["fg"], insertbackground=DARK["fg"]
                )
                text.grid(row=row_index, column=1, sticky="ew", padx=5, pady=4)
                text.bind("<<Modified>>", lambda event, key=field: self.text_changed(key, event.widget))
                self.texts[field] = text
                row_index += 1
        form.columnconfigure(1, weight=1)


    STATUS_GROUPS = {
        "base": [
            "lv", "exp", "growth_curve_group_id", "hp", "mp",
            "strength", "vitality", "agility", "intelligence",
            "spirit", "magic", "luck",
        ],
        "battle": [
            "attack", "defense", "accuracy_rate", "dodge_times",
            "evasion_rate", "ability_defense", "magic_evasion_rate",
            "initial_condition_group", "corps",
        ],
        "magic": [
            "magical_times1", "magical_times2", "magical_times3", "magical_times4",
            "magical_times5", "magical_times6", "magical_times7", "magical_times8",
            "command_id1", "command_id2", "command_id3", "command_id4",
            "command_id5", "command_id6", "content_id1", "content_id2",
            "content_id3", "content_id4", "content_id5", "content_id6",
            "ability_random_group_id", "character_asset_id",
        ],
    }

    def _build_status_form(self, parent, fields, intro):
        outer = ttk.Frame(parent, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=intro, style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(0, 10))
        form = self._scroll_form(outer)
        row_index = 0
        available = set(self.status_document.fieldnames) if self.status_document else set()
        for field in fields:
            if field not in available:
                continue
            ttk.Label(form, text=friendly_label(field)).grid(row=row_index, column=0, sticky="w", padx=5, pady=4)
            variable = tk.StringVar()
            variable.trace_add("write", lambda *_args, key=field: self.status_changed(key))
            self.status_vars[field] = variable
            entry = ttk.Entry(form, textvariable=variable)
            entry.grid(row=row_index, column=1, sticky="ew", padx=5, pady=4)
            self.status_widgets[field] = entry
            row_index += 1
        form.columnconfigure(1, weight=1)
        if not self.status_document:
            ttk.Label(form, text="character_status.csv was not found.", foreground="#ff8080").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=8)

    def _build_status_tabs(self):
        self._build_status_form(
            self.base_stats_tab, self.STATUS_GROUPS["base"],
            "Real starting class values from character_status.csv. These fields replace the misleading zero placeholders in job.csv."
        )
        self._build_status_form(
            self.battle_stats_tab, self.STATUS_GROUPS["battle"],
            "Starting battle, accuracy, evasion, defense, and condition values from character_status.csv."
        )
        self._build_status_form(
            self.magic_tab, self.STATUS_GROUPS["magic"],
            "Starting spell charges, commands, content, and character asset references from character_status.csv. Unknown IDs are preserved exactly."
        )

    def _build_equipment_tab(self):
        outer = ttk.Frame(self.equipment_tab, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Equipment Compatibility", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(outer, text=(
            "Double-click an item to allow or deny the selected job. Permissions are stored in "
            "job_group.csv through each item's equip_job_group_id. The editor changes the existing native group directly. "
            "Weapons and armor sharing that group will change together, matching the last confirmed working editor."
        ), style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=(6,10))
        self.equipment_summary = ttk.Label(outer, text="Select a job.", wraplength=850)
        self.equipment_summary.pack(anchor="w", pady=(0,8))
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        for kind, title, doc in (("weapon", "Weapons", self.weapon_document), ("armor", "Armor", self.armor_document)):
            frame = ttk.Frame(panes, padding=6); panes.add(frame, weight=1)
            ttk.Label(frame, text=title, style="Heading.TLabel").pack(anchor="w")
            tree = ttk.Treeview(frame, columns=("allowed",), show="tree headings", selectmode="browse")
            tree.heading("#0", text="Item"); tree.heading("allowed", text="Allowed")
            tree.column("#0", width=270); tree.column("allowed", width=70, anchor="center")
            tree.pack(fill="both", expand=True, pady=(5,0))
            tree.bind("<ButtonRelease-1>", lambda e, k=kind: self._equipment_click(e, k))
            self.equipment_trees[kind] = tree

    def _equipment_name(self, kind, row):
        prefix = "MSG_WEAPON_NAME_" if kind == "weapon" else "MSG_ARMOR_NAME_"
        try:
            key = f"{prefix}{int(row.get('id','0')):02d}"
            value = self.messages.display(key)
            return value if value and value != key else f"{kind.title()} {row.get('id','')} ({key})"
        except Exception:
            return str(row.get("id", ""))

    def _group_row(self, group_id):
        if not self.job_group_document:
            return None
        group_id = str(group_id).strip()
        return next((r for r in self.job_group_document.rows if str(r.get("id","")).strip() == group_id), None)

    def refresh_equipment_permissions(self):
        if self.current is None:
            return
        job_id = str(self.document.rows[self.current].get("id", "")).strip()
        field = permission_field_for_job(job_id)
        for kind, doc in (("weapon", self.weapon_document), ("armor", self.armor_document)):
            tree = self.equipment_trees.get(kind)
            if not tree:
                continue
            tree.delete(*tree.get_children())
            if not doc or not self.job_group_document or field not in self.job_group_document.fieldnames:
                continue
            for index, row in enumerate(doc.rows):
                gid = str(row.get("equip_job_group_id", "0"))
                group = self._group_row(gid)
                allowed = bool(group and str(group.get(field,"0")).strip() not in {"", "0", "False", "false"})
                tree.insert("", "end", iid=str(index), text=self._equipment_name(kind,row), values=("☑" if allowed else "☐",))
        slot = permission_slot_for_job(job_id)
        self.equipment_summary.config(text=f"Job {job_id} uses native permission slot {slot}: click the checkbox column to edit the existing native permission group.")


    def _equipment_click(self, event, kind):
        tree = self.equipment_trees.get(kind)
        if not tree or tree.identify_region(event.x, event.y) not in {"cell", "tree"}:
            return
        item = tree.identify_row(event.y)
        if not item:
            return
        tree.selection_set(item)
        self._toggle_equipment_permission(kind)

    def _toggle_equipment_permission(self, kind):
        if self.current is None:
            return
        tree = self.equipment_trees.get(kind); doc = self.weapon_document if kind == "weapon" else self.armor_document
        if not tree or not doc:
            return
        selected = tree.selection()
        if not selected:
            return
        row = doc.rows[int(selected[0])]
        group = self._group_row(row.get("equip_job_group_id", "0"))
        job_id = str(self.document.rows[self.current].get("id", "")).strip(); field=permission_field_for_job(job_id)
        if not group or field not in group:
            messagebox.showwarning("Equipment permission", "The referenced job group or selected job column does not exist.", parent=self)
            return
        current = str(group.get(field,"0")).strip() not in {"", "0", "False", "false"}
        group[field] = "0" if current else "1"
        self.on_dirty(True)
        self.on_status("INFO", f"Updated native equipment group {group.get('id','')} for {self._equipment_name(kind,row)}. Shared equipment using this group changes together.")
        self.refresh_equipment_permissions()

    def _status_row_for_job(self, job_row):
        if not self.status_document:
            return None
        job_id = str(job_row.get("id", "")).strip()
        # character_status.csv explicitly links its starting record through job_id.
        for row in self.status_document.rows:
            if str(row.get("job_id", "")).strip() == job_id:
                return row
        # Conservative fallback for exports where id and job_id are identical.
        for row in self.status_document.rows:
            if str(row.get("id", "")).strip() == job_id:
                return row
        return None

    def load_status_record(self):
        row = self.document.rows[self.current] if self.current is not None else {}
        self.current_status = self._status_row_for_job(row)
        self.loading = True
        for field, variable in self.status_vars.items():
            variable.set(self.current_status.get(field, "") if self.current_status else "")
            widget = self.status_widgets.get(field)
            if widget:
                widget.configure(state="normal" if self.current_status else "disabled")
        self.loading = False
        if hasattr(self, "equipment_summary"):
            if self.current_status:
                self.equipment_summary.configure(text=(
                    f"Job ID {row.get('id','')} uses character-status record {self.current_status.get('id','')} "
                    f"and growth group {self.current_status.get('growth_curve_group_id','')}. "
                    "Equipment permissions remain sourced from weapon.csv and armor.csv group references."
                ))
            else:
                self.equipment_summary.configure(text=(
                    "No character_status.csv starting record is linked to this job. Promoted jobs may inherit "
                    "the active character record instead of owning a separate starting row."
                ))

    def status_changed(self, field):
        if self.loading or not self.current_status:
            return
        self.current_status[field] = self.status_vars[field].get()
        self.on_dirty(True)
        self.update_inspector()

    def _build_commands(self):
        top = ttk.Frame(self.commands_tab, padding=14)
        top.pack(fill="both", expand=True)
        ttk.Label(top, text="Available Commands", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            top,
            text=("Select up to five commands. The Studio writes their real command IDs "
                  "into change_command_1 through change_command_5."),
            style="Muted.TLabel", wraplength=760
        ).pack(anchor="w", pady=(4, 10))

        self.command_filter = tk.StringVar()
        self.command_filter.trace_add("write", lambda *_: self.refresh_command_list())
        ttk.Entry(top, textvariable=self.command_filter).pack(fill="x", pady=(0, 8))

        self.command_list = tk.Listbox(
            top, selectmode="multiple", exportselection=False,
            bg=DARK["panel"], fg=DARK["fg"],
            selectbackground=DARK["selection"], relief="flat", height=16
        )
        self.command_list.pack(fill="both", expand=True)
        self.command_list.bind("<<ListboxSelect>>", lambda _event: self.command_selection_changed())

        self.command_summary = ttk.Label(top, text="No commands selected", style="Muted.TLabel")
        self.command_summary.pack(anchor="w", pady=(8, 0))
        self.filtered_commands = []
        self.refresh_command_list()

    def _build_class_designer(self):
        frame = ttk.Frame(self.class_tab, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Balanced Class Designer", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=("Combine roles without stacking unlimited power. The generator redistributes one "
                  "shared end-game budget and allows no more than two core stats at 90+."),
            style="Muted.TLabel", wraplength=760
        ).pack(anchor="w", pady=(4, 12))

        role_row = ttk.Frame(frame)
        role_row.pack(fill="x")
        for role, variable in self.role_vars.items():
            ttk.Checkbutton(
                role_row, text=role, variable=variable, command=self.preview_archetype
            ).pack(side="left", padx=(0, 18))

        settings = ttk.Frame(frame)
        settings.pack(fill="x", pady=(14, 8))
        ttk.Label(settings, text="Core end-game stat budget").pack(side="left")
        ttk.Spinbox(
            settings, from_=300, to=540, increment=10,
            textvariable=self.budget_var, width=8
        ).pack(side="left", padx=8)
        ttk.Button(settings, text="Preview", command=self.preview_archetype).pack(side="left")
        ttk.Button(
            settings, text="Generate Balanced Growth",
            command=self.apply_archetype
        ).pack(side="right")

        self.archetype_tree = ttk.Treeview(
            frame, columns=("stat", "target"), show="headings", height=10
        )
        self.archetype_tree.heading("stat", text="End-game target")
        self.archetype_tree.heading("target", text="Value")
        self.archetype_tree.column("stat", width=250)
        self.archetype_tree.column("target", width=120, anchor="center")
        self.archetype_tree.pack(fill="x", pady=12)

        self.archetype_note = ttk.Label(frame, text="", wraplength=780)
        self.archetype_note.pack(anchor="w")
        self.preview_archetype()

    def refresh_command_list(self):
        query = self.command_filter.get().strip().lower() if hasattr(self, "command_filter") else ""
        selected_values = self.current_command_values()
        self.command_list.delete(0, "end")
        self.filtered_commands = []
        for choice in self.commands:
            if choice.value == "0":
                continue
            if query and query not in choice.display.lower():
                continue
            self.filtered_commands.append(choice)
            self.command_list.insert("end", choice.display)
        for index, choice in enumerate(self.filtered_commands):
            if choice.value in selected_values:
                self.command_list.selection_set(index)

    def current_command_values(self):
        if self.current is None:
            return []
        row = self.document.rows[self.current]
        return [
            row.get(field, "0")
            for field in self.COMMAND_FIELDS
            if field in row and row.get(field, "0") not in ("", "0")
        ]

    def command_selection_changed(self):
        if self.loading or self.current is None:
            return
        selected = [
            self.filtered_commands[index]
            for index in self.command_list.curselection()
        ][:5]
        row = self.document.rows[self.current]
        for position, field in enumerate(self.COMMAND_FIELDS):
            if field in row:
                row[field] = selected[position].value if position < len(selected) else "0"
        self.command_summary.configure(
            text="Selected: " + (", ".join(choice.label for choice in selected) or "None")
        )
        self.on_dirty(True)
        self.update_inspector()

    def selected_roles(self):
        return [role for role, variable in self.role_vars.items() if variable.get()]

    def preview_archetype(self):
        plan = build_archetype_plan(self.selected_roles(), self.budget_var.get())
        self.archetype_tree.delete(*self.archetype_tree.get_children())
        for stat, value in plan.core_targets.items():
            self.archetype_tree.insert("", "end", values=(friendly_label(stat), value))
        self.archetype_tree.insert("", "end", values=("Derived HP at level 99", plan.hp_target_99))
        self.archetype_tree.insert("", "end", values=("Accuracy", plan.accuracy_target))
        self.archetype_tree.insert("", "end", values=("Evasion", plan.evasion_target))
        self.archetype_note.configure(
            text=(
                f"Roles: {' + '.join(plan.roles)}   |   Budget: {plan.stat_budget}\n"
                "Examples: Warrior + Ninja = Samurai; Warrior + Caster = Dark Knight; "
                "Warrior + Tank + Caster = Paladin."
            )
        )
        return plan

    def apply_archetype(self):
        if self.current is None or not self.growth:
            messagebox.showwarning(
                "Class Designer", "Select a job with an assigned growth curve first.", parent=self
            )
            return
        plan = self.preview_archetype()
        row = self.document.rows[self.current]
        levels = [int(item.get("lv", "0") or 0) for item in self.growth.rows]
        if not levels:
            return

        for stat, target in plan.core_targets.items():
            if stat not in self.growth.curves.fieldnames:
                continue
            try:
                base = int(row.get(stat, "0") or 0)
            except ValueError:
                base = 0
            apply_generated_curve(
                self.growth, stat, base, target,
                "Linear", 1.0, min(levels)
            )

        for stat, target in (
            ("accuracy_rate", plan.accuracy_target),
            ("evasion_rate", plan.evasion_target),
        ):
            if stat in self.growth.curves.fieldnames:
                apply_generated_curve(
                    self.growth, stat, 0, target,
                    "Linear", 1.0, min(levels)
                )

        if "hp_value1" in self.growth.curves.fieldnames:
            try:
                base_vitality = int(row.get("vitality", "0") or 0)
            except ValueError:
                base_vitality = 0
            hp_design = self.growth_profiles.get(row.get("id", ""), "hp_value1", plan.hp_target_99)
            hp_design.level_99_hp_target = plan.hp_target_99
            hp_design.final_target = plan.hp_target_99
            strong_levels = flags_for_target(
                base_hp=hp_design.base_hp,
                base_vitality=base_vitality,
                rows=self.growth.rows,
                target_hp=plan.hp_target_99,
                curve_type=hp_design.curve_type,
                slope=hp_design.slope,
            )
            write_strong_hp_flags(self.growth.rows, strong_levels)
            self.growth_profiles.set(row.get("id", ""), "hp_value1", hp_design)

        self.on_dirty(True)
        self.load_growth_views()
        self.on_status("PASS", f"Generated balanced {' + '.join(plan.roles)} growth.")
        messagebox.showinfo(
            "Growth generated",
            f"Applied {' + '.join(plan.roles)} using a shared budget of {plan.stat_budget}.",
            parent=self,
        )

    def display(self, row):
        key = row.get("mes_id_name", "")
        return self.messages.display(key) or key or f"Job {row.get('id', '')}"

    def refresh(self):
        query = self.search.get().strip().lower()
        self.indices = []
        self.list.delete(0, "end")
        for index, row in enumerate(self.document.rows):
            haystack = (" ".join(row.values()) + " " + self.display(row)).lower()
            if not query or query in haystack:
                self.indices.append(index)
                self.list.insert("end", f"{row.get('id', '')} — {self.display(row)}")

    def _selected(self, _event=None):
        selection = self.list.curselection()
        if selection:
            self.select(selection[0])

    def select(self, visible_index):
        self.current = self.indices[visible_index]
        row = self.document.rows[self.current]
        self.loading = True
        for field, variable in self.vars.items():
            variable.set(row.get(field, ""))
        for field, text in self.texts.items():
            text.delete("1.0", "end")
            text.insert("1.0", self.messages.resolve(row.get(field, ""), fallback_to_key=False))
            text.edit_modified(False)
        self.loading = False
        self.growth = (
            self.growth_provider(row.get("id", ""))
            if self.growth_provider else None
        )
        self.load_status_record()
        self.refresh_equipment_permissions()
        self.refresh_command_list()
        self.load_growth_views()
        label = self.messages.display(row.get('mes_id_name','')) or row.get('mes_id_name','') or f"Job {row.get('id','')}"
        asset_id = self.current_status.get('character_asset_id','') if self.current_status else ''
        tokens = [row.get('id',''), asset_id, row.get('mes_id_name','')]
        if self.battle_assets:
            self.battle_assets.set_entity(label, tokens)
        if self.field_assets:
            self.field_assets.set_entity(label, tokens)
        if self.sprite_selector:
            self.sprite_selector.set_job(row.get("id", ""), label)
        self.update_inspector()

    def changed(self, field):
        if self.loading or self.current is None:
            return
        self.document.rows[self.current][field] = self.vars[field].get()
        self.on_dirty(True)
        self.refresh()
        self.update_inspector()

    def text_changed(self, field, widget):
        if self.loading or not widget.edit_modified() or self.current is None:
            return
        key = self.document.rows[self.current].get(field, "").strip()
        if key:
            self.messages.set(key, widget.get("1.0", "end-1c"))
            self.on_dirty(True)
            self.refresh()
        widget.edit_modified(False)

    def cumulative_series(self, field):
        if not self.growth:
            return []
        row = self.document.rows[self.current]
        try:
            running = int(row.get(field, "0") or 0)
        except ValueError:
            running = 0
        result = [(1, running)]
        for curve_row in self.growth.rows:
            try:
                running += int(curve_row.get(field, "0") or 0)
            except ValueError:
                pass
            result.append((int(curve_row.get("lv", "0") or 0), running))
        return result


    def load_growth_views(self):
        for child in self.graph_tab.winfo_children():
            child.destroy()
        for child in self.advanced_tab.winfo_children():
            child.destroy()

        if not self.growth:
            ttk.Label(self.graph_tab, text="No growth mapping found.").pack(padx=12, pady=12)
            ttk.Label(self.advanced_tab, text="No growth mapping found.").pack(padx=12, pady=12)
            return

        graph_controls = ttk.Frame(self.graph_tab, padding=12)
        graph_controls.pack(fill="x")
        available = [field for field in CALC_FIELDS if field in self.growth.curves.fieldnames]
        default_field = available[0] if available else "strength"
        field_var = tk.StringVar(value=default_field)
        curve_var = tk.StringVar()
        target_var = tk.IntVar()
        slope_var = tk.DoubleVar()
        late_var = tk.IntVar()
        level_cap_var = tk.IntVar()
        base_hp_var = tk.IntVar()
        ng3_hp_var = tk.IntVar()
        restoring = {"active": False}

        ttk.Label(graph_controls, text="Stat").pack(side="left")
        ttk.Combobox(
            graph_controls, textvariable=field_var,
            state="readonly", values=available, width=18
        ).pack(side="left", padx=(5, 14))
        ttk.Label(graph_controls, text="Curve shape").pack(side="left")
        ttk.Combobox(
            graph_controls, textvariable=curve_var,
            state="readonly", values=CURVE_TYPES, width=16
        ).pack(side="left", padx=(5, 14))
        ttk.Label(graph_controls, text="Final target").pack(side="left")
        ttk.Spinbox(
            graph_controls, textvariable=target_var, from_=0, to=9999, width=8
        ).pack(side="left", padx=(5, 14))
        ttk.Label(graph_controls, text="Slope").pack(side="left")
        ttk.Spinbox(
            graph_controls, textvariable=slope_var,
            from_=0.2, to=5.0, increment=0.1, width=6
        ).pack(side="left", padx=(5, 14))

        second = ttk.Frame(self.graph_tab, padding=(12, 0, 12, 8))
        second.pack(fill="x")
        ttk.Label(second, text="Late-start level").pack(side="left")
        ttk.Spinbox(second, textvariable=late_var, from_=1, to=250, width=7).pack(
            side="left", padx=(5, 14)
        )
        ttk.Label(second, text="Preview cap").pack(side="left")
        ttk.Combobox(
            second, textvariable=level_cap_var, state="readonly",
            values=(99, 150, 200, 250), width=7
        ).pack(side="left", padx=(5, 14))
        ttk.Label(second, text="Base HP").pack(side="left")
        ttk.Spinbox(second, textvariable=base_hp_var, from_=1, to=999, width=7).pack(
            side="left", padx=(5, 14)
        )
        ttk.Label(second, text="NG+++ HP target").pack(side="left")
        ttk.Spinbox(second, textvariable=ng3_hp_var, from_=1, to=9999, width=8).pack(
            side="left", padx=(5, 14)
        )

        planner = ttk.LabelFrame(self.graph_tab, text="End-game Target Planner", padding=8)
        planner.pack(fill="x", padx=12, pady=(0, 8))
        planner_targets = {}
        planner_fields = [
            ("hp_value1", "HP", 999), ("strength", "Strength", 99),
            ("vitality", "Vitality", 99), ("agility", "Agility", 99),
            ("intelligence", "Intelligence", 99), ("luck", "Luck", 99),
            ("accuracy_rate", "Accuracy", 100), ("evasion_rate", "Evasion", 100),
        ]
        for col, (field, label, default) in enumerate(planner_fields):
            ttk.Label(planner, text=label).grid(row=(col // 4) * 2, column=col % 4, sticky="w", padx=4)
            var = tk.IntVar(value=default)
            planner_targets[field] = var
            ttk.Spinbox(planner, textvariable=var, from_=0, to=9999, width=8).grid(
                row=(col // 4) * 2 + 1, column=col % 4, sticky="w", padx=4, pady=(0, 5)
            )

        graph = GrowthGraph(self.graph_tab)
        graph.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        preview = ttk.Label(self.graph_tab, text="", style="Muted.TLabel", wraplength=900)
        preview.pack(anchor="w", padx=12, pady=(0, 8))

        def current_job_id():
            return self.document.rows[self.current].get("id", "") if self.current is not None else ""

        def base_for(field):
            # Starting stats live in character_status.csv, not job.csv.
            row = self.current_status or self.document.rows[self.current]
            try:
                return int(row.get(field, "0") or 0)
            except ValueError:
                return 0

        def restore_design(*_args):
            field = field_var.get()
            default_target = 980 if field == "hp_value1" else 90
            design = self.growth_profiles.get(current_job_id(), field, default_target)
            restoring["active"] = True
            curve_var.set(design.curve_type)
            slope_var.set(design.slope)
            late_var.set(design.late_start)
            target_var.set(
                design.level_99_hp_target if field == "hp_value1"
                else design.final_target
            )
            level_cap_var.set(design.preview_level_cap)
            base_hp_var.set(design.base_hp)
            ng3_hp_var.set(design.level_250_hp_target)
            restoring["active"] = False
            update_graph()

        def save_design():
            field = field_var.get()
            design = GrowthDesign(
                curve_type=curve_var.get() or "Linear",
                slope=float(slope_var.get()),
                late_start=int(late_var.get()),
                final_target=int(target_var.get()),
                preview_level_cap=int(level_cap_var.get()),
                base_hp=int(base_hp_var.get()),
                level_99_hp_target=int(target_var.get()) if field == "hp_value1" else 700,
                level_250_hp_target=int(ng3_hp_var.get()),
            )
            self.growth_profiles.set(current_job_id(), field, design)
            return design

        def update_graph(*_args):
            if restoring["active"] or self.current is None:
                return
            field = field_var.get()
            if not field:
                return
            design = save_design()
            row = self.document.rows[self.current]
            levels = [
                int(item.get("lv", "0") or 0)
                for item in self.growth.rows
                if str(item.get("lv", "")).isdigit()
            ]
            if not levels:
                return

            if field == "hp_value1":
                try:
                    vitality = int((self.current_status or row).get("vitality", "0") or 0)
                except ValueError:
                    vitality = 0
                strong_levels = {
                    int(item.get("lv", "0") or 0)
                    for item in self.growth.rows
                    if item.get("hp_value1", "0") not in ("", "0")
                    and str(item.get("lv", "")).isdigit()
                }
                projection = project_hp(
                    base_hp=design.base_hp,
                    base_vitality=vitality,
                    rows=self.growth.rows,
                    max_level=design.preview_level_cap,
                    strong_levels=strong_levels,
                    extended_target=(
                        design.level_250_hp_target
                        if design.preview_level_cap > max(levels) else None
                    ),
                )
                graph.set_series(
                    projection.points,
                    f"Derived HP — {design.curve_type} strong-growth pattern"
                )
                preview.configure(
                    text=(
                        f"Level {design.preview_level_cap}: {projection.final_hp} HP. "
                        f"Vitality drives the standard gain (floor(Vitality/4)+1); "
                        f"{len(strong_levels)} strong levels add 24 HP each. "
                        + (
                            "Levels above the base table are an NG+++ runtime projection and are not "
                            "written into growth_curve.csv."
                            if design.preview_level_cap > max(levels) else
                            f"Target at level {max(levels)}: {design.level_99_hp_target} HP."
                        )
                    )
                )
                return

            base = base_for(field)
            generated = generate_curve(
                CurveRequest(
                    min(levels), max(levels), base, design.final_target,
                    design.curve_type, design.slope, design.late_start
                )
            )
            running = base
            points = [(1, running)]
            for level in sorted(generated):
                running += generated[level]
                points.append((level, running))
            graph.set_series(points, f"{friendly_label(field)} — {design.curve_type}")
            preview.configure(
                text=f"Base {base} → calculated final {running}; {len(levels)} growth rows."
            )

        def apply_curve():
            field = field_var.get()
            design = save_design()
            row = self.document.rows[self.current]

            if field == "hp_value1":
                try:
                    vitality = int((self.current_status or row).get("vitality", "0") or 0)
                except ValueError:
                    vitality = 0
                strong_levels = flags_for_target(
                    base_hp=design.base_hp,
                    base_vitality=vitality,
                    rows=self.growth.rows,
                    target_hp=design.level_99_hp_target,
                    curve_type=design.curve_type,
                    slope=design.slope,
                )
                write_strong_hp_flags(self.growth.rows, strong_levels)
                self.on_status(
                    "PASS",
                    f"Applied {design.curve_type} strong-HP pattern targeting "
                    f"{design.level_99_hp_target} HP at the base-table cap."
                )
            else:
                apply_generated_curve(
                    self.growth, field, base_for(field), design.final_target,
                    design.curve_type, design.slope, design.late_start
                )
                self.on_status(
                    "PASS",
                    f"Applied {design.curve_type} {friendly_label(field)} curve "
                    f"ending at {design.final_target}."
                )
            self.on_dirty(True)
            # Keep the selected field and its persisted controls instead of
            # rebuilding them with Linear / 90 defaults.
            update_graph()

        field_var.trace_add("write", restore_design)
        for variable in (
            curve_var, target_var, slope_var, late_var,
            level_cap_var, base_hp_var, ng3_hp_var
        ):
            variable.trace_add("write", update_graph)

        def apply_all_targets():
            if self.current is None or not self.growth:
                return
            row = self.document.rows[self.current]
            style = curve_var.get() or "Linear"
            slope = float(slope_var.get())
            late = int(late_var.get())
            for field, var in planner_targets.items():
                if field not in self.growth.curves.fieldnames:
                    continue
                target = int(var.get())
                if field == "hp_value1":
                    vitality = base_for("vitality")
                    design = self.growth_profiles.get(current_job_id(), field, target)
                    design.curve_type = style
                    design.slope = slope
                    design.late_start = late
                    design.base_hp = base_for("hp") or design.base_hp
                    design.level_99_hp_target = target
                    design.final_target = target
                    strong_levels = flags_for_target(
                        base_hp=design.base_hp, base_vitality=vitality, rows=self.growth.rows,
                        target_hp=target, curve_type=style, slope=slope
                    )
                    write_strong_hp_flags(self.growth.rows, strong_levels)
                    self.growth_profiles.set(current_job_id(), field, design)
                else:
                    apply_generated_curve(
                        self.growth, field, base_for(field), target, style, slope, late
                    )
                    design = self.growth_profiles.get(current_job_id(), field, target)
                    design.curve_type = style
                    design.slope = slope
                    design.late_start = late
                    design.final_target = target
                    self.growth_profiles.set(current_job_id(), field, design)
            self.on_dirty(True)
            self.on_status("PASS", "Applied all end-game stat targets from character_status.csv starting values.")
            update_graph()

        buttons = ttk.Frame(self.graph_tab)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="Apply All End-game Targets", command=apply_all_targets).pack(side="right")
        ttk.Button(buttons, text="Apply Selected Curve", command=apply_curve).pack(side="right", padx=(0, 8))
        restore_design()

        totals = self.growth.totals(self.document.rows[self.current])
        ttk.Label(
            self.advanced_tab,
            text="Calculated table totals: " + "   ".join(
                f"{friendly_label(key)}={value}" for key, value in totals.items()
            ),
            wraplength=900,
        ).pack(anchor="w", padx=10, pady=8)

        columns = ["lv"] + available
        tree = ttk.Treeview(self.advanced_tab, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=friendly_label(column))
            tree.column(column, width=100, anchor="center")
        for curve_row in self.growth.rows:
            tree.insert("", "end", values=[curve_row.get(column, "") for column in columns])
        tree.pack(fill="both", expand=True, padx=10, pady=8)

    def update_inspector(self):
        if self.current is None:
            return
        row = self.document.rows[self.current]
        commands = [
            self.command_by_value.get(value, Choice(value, "Unknown")).label
            for value in self.current_command_values()
        ]
        self.on_inspect(
            "Job Record",
            {
                "ID": row.get("id", ""),
                "Name": self.display(row),
                "Description": self.messages.display(row.get("mes_id_description", "")),
                "Commands": ", ".join(commands) or "None",
                "Growth group": self.growth.group_id if self.growth else "Not found",
                "Character status record": self.current_status.get("id", "") if self.current_status else "Not linked",
                "Starting HP": self.current_status.get("hp", "") if self.current_status else "",
                "Starting stats": (
                    f"STR {self.current_status.get('strength','')} / VIT {self.current_status.get('vitality','')} / "
                    f"AGI {self.current_status.get('agility','')} / INT {self.current_status.get('intelligence','')} / "
                    f"LCK {self.current_status.get('luck','')}"
                ) if self.current_status else "Not available",
            },
        )

    def add(self):
        row = {field: "" for field in self.document.fieldnames}
        ids = []
        for existing in self.document.rows:
            try:
                ids.append(int(existing.get("id", "0")))
            except ValueError:
                pass
        row["id"] = str(max(ids, default=0) + 1)
        self.document.rows.append(row)
        self.on_dirty(True)
        self.refresh()

    def duplicate(self):
        if self.current is None:
            return
        row = dict(self.document.rows[self.current])
        ids = []
        for existing in self.document.rows:
            try:
                ids.append(int(existing.get("id", "0")))
            except ValueError:
                pass
        row["id"] = str(max(ids, default=0) + 1)
        self.document.rows.append(row)
        self.on_dirty(True)
        self.refresh()

    def delete(self):
        if self.current is not None and messagebox.askyesno(
            "Delete job", "Delete selected job?", parent=self
        ):
            del self.document.rows[self.current]
            self.current = None
            self.on_dirty(True)
            self.refresh()

    def validate(self):
        issues = self.document.validate()
        if self.status_document:
            issues.extend(f"character_status.csv: {item}" for item in self.status_document.validate())
        self.on_status(
            "PASS" if not issues else "ERROR",
            "Job data passed validation." if not issues else f"{len(issues)} job issue(s).",
        )
        return issues

    def save(self):
        if self.sprite_selector:
            self.sprite_selector.commit_pending()
        self.document.save()
        if self.status_document:
            self.status_document.save()
        self.messages.save()
        if self.growth:
            self.growth.save()
        if self.weapon_document:
            self.weapon_document.save()
        if self.armor_document:
            self.armor_document.save()
        if self.job_group_document:
            self.job_group_document.save()
        self.on_dirty(False)
        self.on_status("PASS", "Saved job identity, character_status base stats, equipment permissions, commands, growth curves, and English text.")
        if self.on_saved:
            self.on_saved()
        return True

    def save_changes(self):
        return self.save()

    # Existing compatibility hooks.
    def _build_fields(self): return None
    @staticmethod
    def _is_message_field(field): return str(field).lower().startswith("mes_id")
    def _update_translation_labels(self): return None
    def _display_name(self, row, index=0): return self.display(row)
    def refresh_list(self): return self.refresh()
    def _select_visible_index(self, index): return self.select(index)
