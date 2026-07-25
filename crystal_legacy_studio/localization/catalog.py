from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil

from crystal_legacy_studio.core.atomic import atomic_write_text

MESSAGE_TAG_PATTERN = re.compile(r"<[^>]+>")
MESSAGE_KEY_PATTERN = re.compile(r"^(MSG_|MES_|SPEAKER_)", re.IGNORECASE)

@dataclass
class MessageCatalog:
    language: str = "en"
    source_path: Path | None = None
    entries: dict[str, str] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    separators: dict[str, str] = field(default_factory=dict)
    dirty_keys: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path, language: str = "en") -> "MessageCatalog":
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        catalog = cls(language=language, source_path=path, lines=text.splitlines())
        for raw_line in catalog.lines:
            parsed = catalog._parse_line(raw_line)
            if parsed:
                key, value, separator = parsed
                catalog.entries[key] = value
                catalog.separators[key] = separator
        return catalog

    @staticmethod
    def _parse_line(line: str) -> tuple[str, str, str] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "//")):
            return None
        for separator in ("\t", ",", ":", "="):
            if separator in line:
                key, value = line.split(separator, 1)
                key = key.strip()
                if MESSAGE_KEY_PATTERN.match(key):
                    return key, value, separator
        return None

    def resolve(self, key: str | None, *, fallback_to_key: bool = True) -> str:
        key = (key or "").strip()
        if not key:
            return ""
        value = self.entries.get(key)
        return value if value is not None else (key if fallback_to_key else "")

    def display(self, key: str | None, *, strip_control_tags: bool = True) -> str:
        value = self.resolve(key)
        if strip_control_tags:
            value = MESSAGE_TAG_PATTERN.sub("", value)
        return value.strip()

    def contains(self, key: str | None) -> bool:
        return bool(key and key.strip() in self.entries)

    def set_text(self, key: str, text: str) -> None:
        key = key.strip()
        text = text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
        if not key:
            raise ValueError("Message key is blank.")
        if not MESSAGE_KEY_PATTERN.match(key):
            raise ValueError(f"'{key}' is not a recognized message key.")
        if self.entries.get(key) != text:
            self.entries[key] = text
            self.dirty_keys.add(key)


    # Backward-compatible editor API.
    def set(self, key: str, text: str) -> None:
        self.set_text(key, text)

    def search_text(self, key: str | None) -> str:
        if not key:
            return ""
        return f"{key} {self.resolve(key)} {self.display(key)}".lower()

    def validate_keys(self, keys: list[str]) -> list[str]:
        missing=[]
        for key in keys:
            key=(key or "").strip()
            if key and MESSAGE_KEY_PATTERN.match(key) and key not in self.entries:
                missing.append(key)
        return sorted(set(missing))

    def save(self) -> None:
        if not self.source_path:
            raise ValueError("No project translation file is configured.")
        remaining=set(self.dirty_keys)
        output=[]
        for line in self.lines:
            parsed=self._parse_line(line)
            if not parsed:
                output.append(line)
                continue
            key, _value, separator=parsed
            if key in remaining:
                output.append(f"{key}{separator}{self.entries[key]}")
                remaining.remove(key)
            else:
                output.append(line)
        for key in sorted(remaining):
            if output and output[-1].strip():
                output.append("")
            output.append(f"{key}\t{self.entries[key]}")
            self.separators[key]="\t"
        atomic_write_text(self.source_path, "\n".join(output)+"\n", encoding="utf-8")
        self.lines=output
        self.dirty_keys.clear()


def locate_message_file(search_root: Path | None, language: str = "en") -> Path | None:
    if not search_root or not search_root.exists():
        return None
    filename=f"system_{language}.txt"
    candidates=[
        search_root/'message'/'Assets'/'GameAssets'/'Serial'/'Data'/'Message'/filename,
        search_root/'Message'/filename,
        search_root/filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches=list(search_root.rglob(filename))
    return matches[0] if matches else None


def ensure_project_message_copy(project_root: Path, source_path: Path, language: str = "en") -> Path:
    destination=project_root/'Data'/'Message'/f'system_{language}.txt'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination
