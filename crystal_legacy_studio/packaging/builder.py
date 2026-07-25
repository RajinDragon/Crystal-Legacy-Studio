from dataclasses import dataclass, asdict
from pathlib import Path
import base64
import datetime
import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from crystal_legacy_studio.core.atomic import atomic_write_text, atomic_write_bytes
from crystal_legacy_studio.core.errors import PackageBuildError, PackageVerificationError
from crystal_legacy_studio.project.models import Project
from .crypto import PackageKeyStore

EXCLUDED_PARTS = {".crystal", "Build", "Packages", "Backups", "__pycache__"}
EXCLUDED_NAMES = {"package-private-key.pem", "crystal-project.json"}

@dataclass
class PackageOptions:
    title: str
    author: str
    version: str
    description: str = ""
    package_type: str = "CompleteMod"
    requires_new_save: bool = False
    includes_runtime_plugin: bool = False

@dataclass
class PackageResult:
    package_path: Path
    package_id: str
    file_count: int
    package_sha256: str
    verified: bool

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

class PackageBuilder:
    def build(self, project: Project, options: PackageOptions, output_dir: Path) -> PackageResult:
        if not options.title.strip():
            raise PackageBuildError("Package title is required.")
        output_dir.mkdir(parents=True, exist_ok=True)
        key_store = PackageKeyStore(project.metadata_dir / "keys")
        private_key, public_key = key_store.ensure_keys()

        stable_id_path = project.metadata_dir / "package-id.txt"
        if stable_id_path.exists():
            package_id = stable_id_path.read_text(encoding="utf-8").strip()
        else:
            package_id = f"{project.manifest.project_id}:{uuid.uuid4()}"
            atomic_write_text(stable_id_path, package_id)

        safe_name = "".join(c for c in options.title if c.isalnum() or c in "-_").strip() or "mod"
        package_path = output_dir / f"{safe_name}-{options.version}.crystalpackage"

        with tempfile.TemporaryDirectory(prefix="crystal-package-") as temp_name:
            stage = Path(temp_name)
            content_dir = stage / "content"
            content_dir.mkdir(parents=True)

            copied_files: list[Path] = []
            for source in sorted(project.working_root.rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(project.working_root)
                if any(part in EXCLUDED_PARTS for part in relative.parts):
                    continue
                if source.name in EXCLUDED_NAMES:
                    continue
                destination = content_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied_files.append(destination)

            if not copied_files:
                raise PackageBuildError("The package contains no files.", detail="Save project changes before packaging.")

            checksums = {}
            for path in sorted(copied_files):
                relative = path.relative_to(stage).as_posix()
                checksums[relative] = sha256_file(path)

            manifest = {
                "schemaVersion": 1,
                "packageId": package_id,
                "name": options.title,
                "author": options.author,
                "version": options.version,
                "description": options.description,
                "packageType": options.package_type,
                "gameProfile": project.manifest.game_profile,
                "minimumStudioVersion": "0.1.0-alpha.1",
                "createdUtc": datetime.datetime.now(datetime.UTC).isoformat(),
                "projectId": project.manifest.project_id,
                "requiresNewSave": options.requires_new_save,
                "includesRuntimePlugin": options.includes_runtime_plugin,
                "dependencies": [],
                "conflicts": [],
                "contentFileCount": len(copied_files),
                "signatureAlgorithm": "Ed25519",
                "hashAlgorithm": "SHA-256",
            }
            manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            atomic_write_bytes(stage / "package.json", manifest_bytes)

            checksum_lines = [f"{digest}  {path}" for path, digest in sorted(checksums.items())]
            checksum_bytes = ("\n".join(checksum_lines) + "\n").encode("utf-8")
            atomic_write_bytes(stage / "checksums.sha256", checksum_bytes)

            signed_payload = manifest_bytes + b"\n--CHECKSUMS--\n" + checksum_bytes
            signature = private_key.sign(signed_payload)
            signature_doc = {
                "algorithm": "Ed25519",
                "signatureBase64": base64.b64encode(signature).decode("ascii"),
                "signedFiles": ["package.json", "checksums.sha256"],
            }
            atomic_write_text(stage / "signature.json", json.dumps(signature_doc, indent=2))
            atomic_write_bytes(stage / "keys" / "public-key.pem", key_store.public_pem(public_key))

            report = {
                "status": "PASS",
                "errors": [],
                "warnings": [],
                "fileCount": len(copied_files),
                "generatedUtc": datetime.datetime.now(datetime.UTC).isoformat(),
                "privateKeyIncluded": False,
            }
            atomic_write_text(stage / "reports" / "validation-report.json", json.dumps(report, indent=2))

            temp_archive = package_path.with_suffix(package_path.suffix + ".tmp")
            if temp_archive.exists():
                temp_archive.unlink()
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(stage).as_posix())
            temp_archive.replace(package_path)

        self.verify(package_path)
        return PackageResult(
            package_path=package_path,
            package_id=package_id,
            file_count=len(copied_files),
            package_sha256=sha256_file(package_path),
            verified=True,
        )

    def verify(self, package_path: Path) -> None:
        try:
            with zipfile.ZipFile(package_path, "r") as archive:
                names = set(archive.namelist())
                required = {
                    "package.json", "checksums.sha256", "signature.json",
                    "keys/public-key.pem", "reports/validation-report.json"
                }
                missing = required - names
                if missing:
                    raise PackageVerificationError("Package is incomplete.", detail=", ".join(sorted(missing)))
                if any(name.endswith("package-private-key.pem") for name in names):
                    raise PackageVerificationError("A private signing key was found in the package.")

                manifest_bytes = archive.read("package.json")
                checksum_bytes = archive.read("checksums.sha256")
                signature_doc = json.loads(archive.read("signature.json"))
                public_key = serialization.load_pem_public_key(archive.read("keys/public-key.pem"))
                if not isinstance(public_key, Ed25519PublicKey):
                    raise PackageVerificationError("The package public key is invalid.")

                signature = base64.b64decode(signature_doc["signatureBase64"])
                public_key.verify(signature, manifest_bytes + b"\n--CHECKSUMS--\n" + checksum_bytes)

                for line in checksum_bytes.decode("utf-8").splitlines():
                    if not line.strip():
                        continue
                    digest, relative = line.split("  ", 1)
                    actual = hashlib.sha256(archive.read(relative)).hexdigest()
                    if actual != digest:
                        raise PackageVerificationError("Package content hash mismatch.", detail=relative)
        except PackageVerificationError:
            raise
        except Exception as exc:
            raise PackageVerificationError("Package verification failed.", detail=str(exc)) from exc
