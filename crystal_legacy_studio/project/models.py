from dataclasses import dataclass, asdict
from pathlib import Path
import datetime
import json
import uuid
from crystal_legacy_studio.core.atomic import atomic_write_text
from crystal_legacy_studio.core.errors import ProjectError
from crystal_legacy_studio.project.layout import GameProjectLayout

@dataclass
class ProjectManifest:
    schema_version: int
    project_id: str
    name: str
    author: str
    version: str
    game_profile: str
    created_utc: str
    modified_utc: str

class Project:
    """A Crystal Legacy project anchored to the FF1PR game root."""
    def __init__(self, root: Path, manifest: ProjectManifest) -> None:
        self.root = root.expanduser().resolve()  # ALWAYS the FF1PR game root
        self.layout = GameProjectLayout(self.root, manifest.game_profile)
        self.manifest = manifest

    @property
    def working_root(self) -> Path:
        return self.layout.working_root

    @property
    def metadata_dir(self) -> Path:
        return self.layout.metadata_dir

    @property
    def manifest_path(self) -> Path:
        return self.working_root / "crystal-project.json"

    def save(self) -> None:
        self.manifest.modified_utc = datetime.datetime.now(datetime.UTC).isoformat()
        atomic_write_text(self.manifest_path, json.dumps(asdict(self.manifest), indent=2))

class ProjectService:
    REQUIRED_DIRS = [
        "Assets", "Data/Master", "Data/Message", "Overlays", "Rulesets", "Build",
        ".crystal/keys", ".crystal/logs", ".crystal/cache", ".crystal/history", ".crystal/level-probe"
    ]

    def create(self, root: Path, name: str, author: str = "", magicite_export: Path | None = None, game_profile: str = "ff1pr-steam-windows") -> Project:
        game_root = root.expanduser().resolve()
        layout = GameProjectLayout(game_root, game_profile)
        layout.ensure_managed_directories()
        if not name.strip():
            raise ProjectError("Project name is required.")
        now = datetime.datetime.now(datetime.UTC).isoformat()
        manifest = ProjectManifest(
            schema_version=2,
            project_id=str(uuid.uuid4()),
            name=name.strip(),
            author=author.strip(),
            version="0.1.0",
            game_profile=game_profile,
            created_utc=now,
            modified_utc=now,
        )
        for relative in self.REQUIRED_DIRS:
            (layout.working_root / relative).mkdir(parents=True, exist_ok=True)
        project = Project(game_root, manifest)
        project.save()
        # The live Magicite\Crystal Legacy folder is authoritative whenever it
        # already exists. New projects inherit the current installed mod rather
        # than silently starting from untouched MagiciteExport defaults.
        layout.adopt_active_as_working()
        return project

    def open(self, root: Path, magicite_export: Path | None = None) -> Project:
        game_root = root.expanduser().resolve()
        layout = GameProjectLayout(game_root)
        path = layout.working_root / "crystal-project.json"
        if not path.exists():
            raise ProjectError(
                "No Crystal Legacy project was found for this game installation.",
                detail=f"Expected: {path}\nUse New to initialize the working project under BepInEx\\Crystal Legacy\\Working.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            project = Project(game_root, ProjectManifest(**payload))
            project.layout.validate_required_installation()
            if project.layout.active_has_mod_data():
                comparison = project.layout.compare_working_to_active()
                if not comparison["matches"]:
                    project.layout.timestamped_backup(project.working_root, "BeforeOpenAdoptActive")
                    project.layout.adopt_active_as_working()
            return project
        except Exception as exc:
            raise ProjectError("The project manifest is invalid.", detail=str(exc)) from exc
