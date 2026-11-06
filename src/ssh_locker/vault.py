"""Encrypted on-disk storage for connections.

File layout (v2): MAGIC | version | log2(scrypt N) | salt (16) | nonce (12) |
AES-256-GCM ciphertext. Everything before the nonce is authenticated as
associated data, so the recorded KDF cost cannot be altered unnoticed.

v1 files (MAGIC | 1 | salt | nonce | ciphertext, scrypt N = 2^15) still open,
and are rewritten as v2 at the current cost on the next password unlock.
"""

import hmac
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
VERSION = 2
SALT_LEN = 16
NONCE_LEN = 12
HEADER_LEN = len(MAGIC) + 2 + SALT_LEN
KEY_LEN = 32

# scrypt cost as log2(N), with r = 8, p = 1. 17 is the OWASP minimum.
KDF_LOG2_N = 17
V1_LOG2_N = 15
# Accepted range when reading a file: bounds memory use (2^20 * 1 KiB = 1 GiB).
MIN_LOG2_N, MAX_LOG2_N = 14, 20

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


def _derive_key(password: str, salt: bytes, log2_n: int) -> bytes:
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=2**log2_n, r=8, p=1)
    return kdf.derive(password.encode("utf-8"))


class _File:
    """A parsed vault file."""

    def __init__(self, raw: bytes):
        if len(raw) < len(MAGIC) + 1 or not raw.startswith(MAGIC):
            raise VaultError(DAMAGED)
        self.version = raw[len(MAGIC)]
        if self.version == 1:
            self.log2_n = V1_LOG2_N
            header_len = len(MAGIC) + 1 + SALT_LEN
        elif self.version == 2:
            if len(raw) < len(MAGIC) + 2:
                raise VaultError(DAMAGED)
            self.log2_n = raw[len(MAGIC) + 1]
            header_len = HEADER_LEN
            if not MIN_LOG2_N <= self.log2_n <= MAX_LOG2_N:
                raise VaultError(DAMAGED)
        else:
            raise VaultError("Unsupported vault version")
        if len(raw) < header_len + NONCE_LEN:
            raise VaultError(DAMAGED)
        self.header = raw[:header_len]
        self.salt = raw[header_len - SALT_LEN : header_len]
        self.nonce = raw[header_len : header_len + NONCE_LEN]
        self.ciphertext = raw[header_len + NONCE_LEN :]

    def decrypt(self, key: bytes) -> list[Connection]:
        try:
            plaintext = AESGCM(key).decrypt(self.nonce, self.ciphertext, self.header)
            return [Connection(**item) for item in json.loads(plaintext)]
        except (InvalidTag, ValueError, TypeError) as exc:
            raise VaultError(DAMAGED) from exc


class Vault:
    def __init__(
        self,
        key: bytes,
        salt: bytes,
        connections: list[Connection],
        log2_n: int,
    ):
        self._key = key
        self._salt = salt
        self._log2_n = log2_n
        self.connections = connections

    def __repr__(self) -> str:
        return f"<Vault {len(self.connections)} connections>"

    @property
    def key(self) -> bytes:
        return self._key

    @staticmethod
    def exists() -> bool:
        return vault_path().exists()

    @classmethod
    def create(cls, password: str) -> "Vault":
        salt = os.urandom(SALT_LEN)
        vault = cls(_derive_key(password, salt, KDF_LOG2_N), salt, [], KDF_LOG2_N)
        vault.save()
        return vault

    @classmethod
    def open_with_password(cls, password: str) -> "Vault":
        file = cls._read()
        key = _derive_key(password, file.salt, file.log2_n)
        vault = cls(key, file.salt, file.decrypt(key), file.log2_n)
        if file.version < VERSION or file.log2_n < KDF_LOG2_N:
            vault._rekey(password)
        return vault

    @classmethod
    def open_with_key(cls, key: bytes) -> "Vault":
        file = cls._read()
        return cls(key, file.salt, file.decrypt(key), file.log2_n)

    @staticmethod
    def _read() -> _File:
        try:
            raw = vault_path().read_bytes()
        except OSError as exc:
            raise VaultError(f"Cannot read vault: {exc.strerror or exc}") from exc
        return _File(raw)

    def change_password(self, current: str, new: str) -> None:
        """Re-encrypt under `new`. On any failure the old password stays valid."""
        if not hmac.compare_digest(
            _derive_key(current, self._salt, self._log2_n), self._key
        ):
            raise VaultError("Current password is wrong")
        saved = (self._salt, self._log2_n, self._key)
        try:
            self._rekey(new)
        except BaseException:
            self._salt, self._log2_n, self._key = saved
            raise

    def _rekey(self, password: str) -> None:
        """Re-encrypt under a fresh salt at the current KDF cost."""
        self._salt = os.urandom(SALT_LEN)
        self._log2_n = KDF_LOG2_N
        self._key = _derive_key(password, self._salt, self._log2_n)
        self.save()

    def save(self) -> None:
        header = MAGIC + bytes([VERSION, self._log2_n]) + self._salt
        nonce = os.urandom(NONCE_LEN)
        plaintext = json.dumps([asdict(c) for c in self.connections]).encode("utf-8")
        blob = header + nonce + AESGCM(self._key).encrypt(nonce, plaintext, header)

        path = vault_path()
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
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
