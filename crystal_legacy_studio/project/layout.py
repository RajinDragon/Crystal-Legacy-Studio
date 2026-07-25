from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import datetime
import hashlib
import json
import shutil

from crystal_legacy_studio.core.atomic import atomic_write_text
from crystal_legacy_studio.core.errors import ProjectError
from crystal_legacy_studio.game.profiles import get_profile


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class GameProjectLayout:
    r"""Canonical Crystal Legacy layout derived only from the FF1PR game root."""

    game_root: Path
    game_profile: str = "ff1pr-steam-windows"

    @property
    def data_dir(self) -> Path:
        profile = get_profile(self.game_profile)
        for name in profile.data_dir_names:
            candidate = self.game_root / name
            if candidate.is_dir():
                return candidate
        return self.game_root / profile.data_dir_names[0]

    @property
    def streaming_assets(self) -> Path:
        return self.data_dir / "StreamingAssets"

    @property
    def magicite_root(self) -> Path:
        return self.streaming_assets / "Magicite"

    @property
    def magicite_export(self) -> Path:
        return self.streaming_assets / "MagiciteExport"

    @property
    def active_mod(self) -> Path:
        return self.magicite_root / "Crystal Legacy"

    @property
    def bepinex_root(self) -> Path:
        return self.game_root / "BepInEx"

    @property
    def studio_root(self) -> Path:
        return self.bepinex_root / "Crystal Legacy"

    @property
    def working_root(self) -> Path:
        return self.studio_root / "Working"

    @property
    def working_data(self) -> Path:
        return self.working_root / "Data"

    @property
    def working_master(self) -> Path:
        return self.working_data / "Master"

    @property
    def working_message(self) -> Path:
        return self.working_data / "Message"

    @property
    def working_overlays(self) -> Path:
        return self.working_root / "Overlays"

    @property
    def metadata_dir(self) -> Path:
        return self.working_root / ".crystal"

    @property
    def package_root(self) -> Path:
        return self.game_root / "Crystal Legacy"

    @property
    def import_dir(self) -> Path:
        return self.package_root / "Import"

    @property
    def export_dir(self) -> Path:
        return self.package_root / "Export"

    @property
    def backup_dir(self) -> Path:
        return self.package_root / "Backups"

    def validate_required_installation(self) -> None:
        missing: list[str] = []
        profile = get_profile(self.game_profile)
        if not any((self.game_root / name).is_file() for name in profile.executable_names):
            missing.append(" or ".join(str(self.game_root / name) for name in profile.executable_names))
        for required in (self.bepinex_root, self.magicite_root, self.magicite_export):
            if not required.is_dir():
                missing.append(str(required))
        if missing:
            raise ProjectError(
                f"The selected folder is not a complete Crystal Legacy {get_profile(self.game_profile).display_name} game root.",
                detail="Missing required path(s):\n" + "\n".join(missing),
            )

    def ensure_managed_directories(self) -> None:
        self.validate_required_installation()
        for path in (
            self.studio_root,
            self.working_root,
            self.working_master,
            self.working_message,
            self.working_overlays,
            self.metadata_dir,
            self.import_dir,
            self.export_dir,
            self.backup_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def timestamped_backup(self, source: Path, category: str) -> Path | None:
        if not source.exists():
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / category / stamp
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / source.name)
        return destination

    @staticmethod
    def _tree_manifest(root: Path) -> dict[str, str]:
        if not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "DEPLOYED_BY_CRYSTAL_LEGACY_STUDIO.txt"
        }

    def active_has_mod_data(self) -> bool:
        """Return True when the live Crystal Legacy folder contains real mod files."""
        if not self.active_mod.is_dir():
            return False
        return any(
            path.is_file() and path.name != "DEPLOYED_BY_CRYSTAL_LEGACY_STUDIO.txt"
            for path in self.active_mod.rglob("*")
        )

    def _working_deployment_manifest(self) -> dict[str, str]:
        working: dict[str, str] = {}
        for source_root, prefix in (
            (self.working_master, "master/Assets/GameAssets/Serial/Data/Master"),
            (self.working_message, "message/Assets/GameAssets/Serial/Data/Message"),
            (self.working_overlays, ""),
        ):
            if not source_root.exists():
                continue
            for path in sorted(source_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(source_root).as_posix()
                key = f"{prefix}/{relative}".strip("/")
                # Editable Master/Message files are authoritative over any stale
                # copies that may exist in imported overlay resources.
                if source_root == self.working_overlays and (
                    key.startswith("master/Assets/GameAssets/Serial/Data/Master/")
                    or key.startswith("message/Assets/GameAssets/Serial/Data/Message/")
                ):
                    continue
                working[key] = sha256_file(path)
        return working

    def adopt_active_as_working(self) -> dict[str, int]:
        r"""Make the live Magicite\Crystal Legacy folder the editable source of truth.

        Master and Message data are copied into their editor-friendly working folders.
        Every other live resource (keys, sprites, bestiary assets, AI, BGM, etc.) is
        copied into Working/Overlays so it remains part of future deployments.
        """
        self.ensure_managed_directories()
        if not self.active_has_mod_data():
            return {"master": 0, "message": 0, "overlays": 0}

        for destination in (self.working_master, self.working_message, self.working_overlays):
            if destination.exists():
                shutil.rmtree(destination)
            destination.mkdir(parents=True, exist_ok=True)

        master_source = self.active_mod / "master/Assets/GameAssets/Serial/Data/Master"
        message_source = self.active_mod / "message/Assets/GameAssets/Serial/Data/Message"
        counts = {"master": 0, "message": 0, "overlays": 0}

        for source, destination, label in (
            (master_source, self.working_master, "master"),
            (message_source, self.working_message, "message"),
        ):
            if source.exists():
                for path in source.rglob("*"):
                    if path.is_file():
                        target = destination / path.relative_to(source)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
                        counts[label] += 1

        excluded_roots = [master_source.resolve(), message_source.resolve()]
        for path in self.active_mod.rglob("*"):
            if not path.is_file() or path.name == "DEPLOYED_BY_CRYSTAL_LEGACY_STUDIO.txt":
                continue
            resolved = path.resolve()
            if any(root == resolved or root in resolved.parents for root in excluded_roots):
                continue
            target = self.working_overlays / path.relative_to(self.active_mod)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            counts["overlays"] += 1

        atomic_write_text(
            self.metadata_dir / "active-source.json",
            json.dumps({
                "source": str(self.active_mod),
                "adoptedUtc": datetime.datetime.now(datetime.UTC).isoformat(),
                "counts": counts,
            }, indent=2),
        )
        return counts

    def compare_working_to_active(self) -> dict:
        """Compare the complete editable working state with the live mod."""
        working = self._working_deployment_manifest()
        active = self._tree_manifest(self.active_mod)
        keys = sorted(set(working) | set(active))
        missing_active = [key for key in keys if key in working and key not in active]
        # Generated master/message keys and the deployment marker are allowed when
        # they are not explicitly stored in Working/Overlays.
        extra_active = [
            key for key in keys
            if key in active and key not in working and not key.endswith("keys/Export.json")
        ]
        changed = [key for key in keys if key in working and key in active and working[key] != active[key]]
        result = {
            "matches": not missing_active and not extra_active and not changed,
            "missingActive": missing_active,
            "extraActive": extra_active,
            "changed": changed,
            "workingFileCount": len(working),
            "activeFileCount": len(active),
            "checkedUtc": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.metadata_dir / "last-integrity-check.json", json.dumps(result, indent=2))
        return result

