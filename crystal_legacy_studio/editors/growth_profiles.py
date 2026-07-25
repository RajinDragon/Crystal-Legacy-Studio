from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json

from crystal_legacy_studio.core.atomic import atomic_write_text

@dataclass
class GrowthDesign:
    curve_type: str = "Linear"
    slope: float = 1.0
    late_start: int = 40
    final_target: int = 90
    preview_level_cap: int = 99
    base_hp: int = 35
    level_99_hp_target: int = 700
    level_250_hp_target: int = 9999

class GrowthProfileStore:
    def __init__(self, project_root: Path):
        self.path = project_root / ".crystal" / "growth-designs.json"
        self.data: dict[str, dict] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = loaded
            except (OSError, json.JSONDecodeError):
                self.data = {}

    @staticmethod
    def _key(job_id: str, field: str) -> str:
        return f"{job_id}:{field}"

    def get(self, job_id: str, field: str, default_target: int = 90) -> GrowthDesign:
        raw = self.data.get(self._key(job_id, field), {})
        values = asdict(GrowthDesign(final_target=default_target))
        if isinstance(raw, dict):
            values.update({key: value for key, value in raw.items() if key in values})
        try:
            return GrowthDesign(**values)
        except (TypeError, ValueError):
            return GrowthDesign(final_target=default_target)

    def set(self, job_id: str, field: str, design: GrowthDesign) -> None:
        self.data[self._key(job_id, field)] = asdict(design)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.data, indent=2, sort_keys=True))
