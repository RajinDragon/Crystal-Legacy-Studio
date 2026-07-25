from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from crystal_legacy_studio.core.atomic import atomic_write_bytes

class PackageKeyStore:
    def __init__(self, keys_dir: Path) -> None:
        self.keys_dir = keys_dir
        self.private_path = keys_dir / "package-private-key.pem"
        self.public_path = keys_dir / "package-public-key.pem"

    def ensure_keys(self) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        if self.private_path.exists():
            private_key = serialization.load_pem_private_key(
                self.private_path.read_bytes(), password=None
            )
            if not isinstance(private_key, Ed25519PrivateKey):
                raise TypeError("Stored package key is not an Ed25519 key.")
            return private_key, private_key.public_key()

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        atomic_write_bytes(
            self.private_path,
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
        )
        atomic_write_bytes(
            self.public_path,
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
        )
        return private_key, public_key

    @staticmethod
    def public_pem(public_key: Ed25519PublicKey) -> bytes:
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
