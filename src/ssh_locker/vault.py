"""Encrypted on-disk storage for connections.

File layout: MAGIC | version | salt (16) | nonce (12) | AES-256-GCM ciphertext.
MAGIC, version and salt are authenticated as associated data.
"""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ssh_locker.models import Connection

MAGIC = b"SSHL"
VERSION = 1
SALT_LEN = 16
NONCE_LEN = 12
HEADER_LEN = len(MAGIC) + 1 + SALT_LEN
KEY_LEN = 32

DAMAGED = "Wrong password or damaged vault"


class VaultError(Exception):
    """Raised with a user-presentable message when the vault cannot be opened."""


def vault_path() -> Path:
    home = os.environ.get("SSH_LOCKER_HOME")
    base = (
        Path(home)
        if home
        else Path.home() / "Library" / "Application Support" / "ssh-locker"
    )
    return base / "vault.bin"


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=2**15, r=8, p=1)
    return kdf.derive(password.encode("utf-8"))


class Vault:
    def __init__(self, key: bytes, salt: bytes, connections: list[Connection]):
        self._key = key
        self._salt = salt
        self.connections = connections

    @property
    def key(self) -> bytes:
        return self._key

    @staticmethod
    def exists() -> bool:
        return vault_path().exists()

    @classmethod
    def create(cls, password: str) -> "Vault":
        salt = os.urandom(SALT_LEN)
        vault = cls(_derive_key(password, salt), salt, [])
        vault.save()
        return vault

    @classmethod
    def open_with_password(cls, password: str) -> "Vault":
        salt = cls._read_salt()
        return cls._open(_derive_key(password, salt), salt)

    @classmethod
    def open_with_key(cls, key: bytes) -> "Vault":
        return cls._open(key, cls._read_salt())

    @classmethod
    def _read_raw(cls) -> bytes:
        try:
            raw = vault_path().read_bytes()
        except OSError as exc:
            raise VaultError(f"Cannot read vault: {exc.strerror or exc}") from exc
        if len(raw) < HEADER_LEN + NONCE_LEN or not raw.startswith(MAGIC):
            raise VaultError(DAMAGED)
        if raw[len(MAGIC)] != VERSION:
            raise VaultError("Unsupported vault version")
        return raw

    @classmethod
    def _read_salt(cls) -> bytes:
        return cls._read_raw()[len(MAGIC) + 1 : HEADER_LEN]

    @classmethod
    def _open(cls, key: bytes, salt: bytes) -> "Vault":
        raw = cls._read_raw()
        header = raw[:HEADER_LEN]
        nonce = raw[HEADER_LEN : HEADER_LEN + NONCE_LEN]
        ciphertext = raw[HEADER_LEN + NONCE_LEN :]
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, header)
            items = json.loads(plaintext)
            connections = [Connection(**item) for item in items]
        except (InvalidTag, ValueError, TypeError) as exc:
            raise VaultError(DAMAGED) from exc
        return cls(key, salt, connections)

    def save(self) -> None:
        header = MAGIC + bytes([VERSION]) + self._salt
        nonce = os.urandom(NONCE_LEN)
        plaintext = json.dumps([asdict(c) for c in self.connections]).encode("utf-8")
        blob = header + nonce + AESGCM(self._key).encrypt(nonce, plaintext, header)

        path = vault_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".vault-")
        except OSError as exc:
            raise VaultError(f"Cannot save vault: {exc.strerror or exc}") from exc
        try:
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            Path(tmp).unlink(missing_ok=True)
            raise VaultError(f"Cannot save vault: {exc.strerror or exc}") from exc
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
