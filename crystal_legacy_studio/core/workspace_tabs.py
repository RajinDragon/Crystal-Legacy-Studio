from dataclasses import dataclass

@dataclass
class TabRecord:
    key: str
    title: str
    kind: str = "module"
    pinned: bool = False
    dirty: bool = False

class WorkspaceTabPolicy:
    """Tracks which tabs are temporary navigation views and which must be retained."""
    def __init__(self) -> None:
        self._records: dict[str, TabRecord] = {}

    def register(self, record: TabRecord) -> None:
        self._records[record.key] = record

    def remove(self, key: str) -> None:
        self._records.pop(key, None)

    def get(self, key: str) -> TabRecord | None:
        return self._records.get(key)

    def mark_dirty(self, key: str, dirty: bool = True) -> None:
        record = self._records[key]
        record.dirty = dirty

    def toggle_pin(self, key: str) -> bool:
        record = self._records[key]
        record.pinned = not record.pinned
        return record.pinned

    def replacement_candidate(self, exclude_key: str | None = None) -> str | None:
        for key, record in self._records.items():
            if key == exclude_key:
                continue
            if record.kind in {"module", "editor"} and not record.pinned and not record.dirty:
                return key
        return None

    @staticmethod
    def display_title(record: TabRecord) -> str:
        prefix = "* " if record.dirty else ""
        suffix = " [Pinned]" if record.pinned and not record.dirty else ""
        return f"{prefix}{record.title}{suffix}"
