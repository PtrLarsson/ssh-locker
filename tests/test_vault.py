import dataclasses
import os
import stat

import pytest

from ssh_locker.models import Connection
from ssh_locker.vault import Vault, VaultError, vault_path

PASSWORD = 'p@ss $"x'


@pytest.fixture(autouse=True)
def vault_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))
    return tmp_path


def make_vault() -> Vault:
    v = Vault.create("pw")
    v.connections.append(Connection("a", "secret-host.example", 2222, "u", PASSWORD))
    v.save()
    return v


def test_roundtrip_password():
    make_vault()
    opened = Vault.open_with_password("pw")
    assert opened.connections == [
        Connection("a", "secret-host.example", 2222, "u", PASSWORD)
    ]


def test_roundtrip_key():
    v = make_vault()
    opened = Vault.open_with_key(v.key)
    assert opened.connections == v.connections


def test_file_has_no_plaintext():
    make_vault()
    raw = vault_path().read_bytes()
    assert b"secret-host.example" not in raw
    assert PASSWORD.encode() not in raw


def test_exists():
    assert not Vault.exists()
    make_vault()
    assert Vault.exists()


def test_wrong_password_raises_and_leaves_file():
    make_vault()
    before = vault_path().read_bytes()
    with pytest.raises(VaultError):
        Vault.open_with_password("nope")
    assert vault_path().read_bytes() == before


@pytest.mark.parametrize("damage", ["flip", "truncate", "empty"])
def test_corrupt_file_raises(damage):
    make_vault()
    path = vault_path()
    raw = bytearray(path.read_bytes())
    if damage == "flip":
        raw[-1] ^= 0xFF
    elif damage == "truncate":
        raw = raw[:10]
    else:
        raw = bytearray()
    path.write_bytes(bytes(raw))
    with pytest.raises(VaultError):
        Vault.open_with_password("pw")


def test_file_mode_0600():
    make_vault()
    assert stat.S_IMODE(os.stat(vault_path()).st_mode) == 0o600


def test_save_is_atomic():
    make_vault()
    assert os.listdir(vault_path().parent) == ["vault.bin"]


def test_save_failure_raises_vault_error(vault_home, monkeypatch):
    import errno

    import ssh_locker.vault as vault_mod

    v = make_vault()
    before = vault_path().read_bytes()

    def disk_full(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr(vault_mod.os, "replace", disk_full)
        with pytest.raises(VaultError, match="Cannot save vault"):
            v.save()
    assert vault_path().read_bytes() == before
    assert os.listdir(vault_home) == ["vault.bin"]  # temp file cleaned up


def test_color_and_comment_roundtrip():
    v = Vault.create("pw")
    v.connections.append(
        Connection("a", "h", color="green", comment="prod box, be careful")
    )
    v.save()
    (conn,) = Vault.open_with_password("pw").connections
    assert (conn.color, conn.comment) == ("green", "prod box, be careful")


def test_vault_saved_before_color_and_comment_still_opens(monkeypatch):
    import ssh_locker.vault as vault_mod

    def legacy_asdict(conn):
        data = dataclasses.asdict(conn)
        del data["color"], data["comment"]
        return data

    v = Vault.create("pw")
    v.connections.append(Connection("old", "h"))
    with monkeypatch.context() as patch:
        patch.setattr(vault_mod, "asdict", legacy_asdict)
        v.save()
    (conn,) = Vault.open_with_password("pw").connections
    assert (conn.color, conn.comment) == (None, "")
