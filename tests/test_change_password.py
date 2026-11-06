import errno
import os

import pytest
from textual.widgets import Input, Static

import ssh_locker.app as app_mod
import ssh_locker.cli as cli
import ssh_locker.vault as vault_mod
from ssh_locker import biometric
from ssh_locker.app import SshLockerApp
from ssh_locker.models import Connection
from ssh_locker.unlock import new_password_problem
from ssh_locker.vault import Vault, VaultError, vault_path

SIZE = (100, 40)
OLD, NEW = "old-master-pw", "new-master-pw"


@pytest.fixture(autouse=True)
def vault_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))
    return tmp_path


def saved_vault() -> Vault:
    v = Vault.create(OLD)
    v.connections.append(Connection("a", "h", 22, "u", "pw"))
    v.save()
    return v


class FakeBackend:
    def __init__(self, stored=None):
        self.stored = stored

    def available(self):
        return True

    def exists(self):
        return self.stored is not None

    def put(self, key):
        self.stored = key

    def get(self):
        return self.stored

    def delete(self):
        self.stored = None


# -- rules ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "new, repeat, problem",
    [
        ("short", "short", "at least 8"),
        (NEW, NEW + "x", "did not match"),
        (OLD, OLD, "differ"),
    ],
)
def test_new_password_rules(new, repeat, problem):
    assert problem in new_password_problem(OLD, new, repeat)


def test_new_password_ok():
    assert new_password_problem(OLD, NEW, NEW) is None


# -- vault --------------------------------------------------------------------------


def test_change_password_rekeys_and_keeps_connections():
    v = saved_vault()
    old_key = v.key
    v.change_password(OLD, NEW)
    assert v.key != old_key
    with pytest.raises(VaultError):
        Vault.open_with_password(OLD)
    assert Vault.open_with_password(NEW).connections == v.connections
    with pytest.raises(VaultError):  # old Touch ID key no longer opens it
        Vault.open_with_key(old_key)


def test_change_password_uses_fresh_salt():
    v = saved_vault()
    salt = slice(6, 22)
    before = vault_path().read_bytes()[salt]
    v.change_password(OLD, NEW)
    assert vault_path().read_bytes()[salt] != before


def test_wrong_current_password_changes_nothing():
    v = saved_vault()
    before = vault_path().read_bytes()
    key = v.key
    with pytest.raises(VaultError, match="Current password is wrong"):
        v.change_password("not-the-password", NEW)
    assert vault_path().read_bytes() == before
    assert v.key == key


def test_failed_save_keeps_old_password(monkeypatch):
    v = saved_vault()
    key = v.key

    def disk_full(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr(vault_mod.os, "replace", disk_full)
        with pytest.raises(VaultError, match="Cannot save vault"):
            v.change_password(OLD, NEW)
    assert v.key == key
    v.save()  # in-memory vault still consistent with the old password
    assert Vault.open_with_password(OLD).connections == v.connections


# -- Touch ID shortcut ---------------------------------------------------------------


def test_shortcut_replaced_when_present(monkeypatch):
    fake = FakeBackend(stored=b"old" * 10)
    monkeypatch.setattr(biometric, "_backend", fake)
    assert biometric.replace_key_if_present(b"new" * 10) is True
    assert fake.stored == b"new" * 10


def test_shortcut_not_created_when_absent(monkeypatch):
    fake = FakeBackend(stored=None)
    monkeypatch.setattr(biometric, "_backend", fake)
    assert biometric.replace_key_if_present(b"new" * 10) is False
    assert fake.stored is None


# -- in the app (p) --------------------------------------------------------------------


def fill(app, **fields):
    for field_id, value in fields.items():
        app.screen.query_one(f"#{field_id}", Input).value = value


async def test_app_change_password(monkeypatch):
    fake = FakeBackend(stored=b"old" * 10)
    monkeypatch.setattr(biometric, "_backend", fake)
    v = saved_vault()
    app = SshLockerApp(v)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p")
        fill(app, current=OLD, new=NEW, repeat=NEW)
        await pilot.click("#change")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    assert Vault.open_with_password(NEW).connections == v.connections
    assert fake.stored == v.key


async def test_app_wrong_current_password_keeps_dialog_open(monkeypatch):
    monkeypatch.setattr(biometric, "_backend", FakeBackend())
    v = saved_vault()
    app = SshLockerApp(v)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p")
        fill(app, current="wrong-one", new=NEW, repeat=NEW)
        await pilot.click("#change")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        assert "wrong" in str(app.screen.query_one("#error", Static).render())
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    Vault.open_with_password(OLD)


async def test_app_rule_violation_shown(monkeypatch):
    monkeypatch.setattr(biometric, "_backend", FakeBackend())
    app = SshLockerApp(saved_vault())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p")
        fill(app, current=OLD, new="short", repeat="short")
        await pilot.click("#change")
        await pilot.pause()
        assert "at least 8" in str(app.screen.query_one("#error", Static).render())
    Vault.open_with_password(OLD)


# -- on the command line --------------------------------------------------------------


def scripted_getpass(monkeypatch, *answers):
    answers = list(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": answers.pop(0))


def test_cli_change_password(monkeypatch, capsys):
    fake = FakeBackend(stored=b"old" * 10)
    monkeypatch.setattr(biometric, "_backend", fake)
    saved_vault()
    scripted_getpass(monkeypatch, OLD, NEW, NEW)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--change-password"])
    assert exc.value.code == 0
    assert "changed" in capsys.readouterr().out
    vault = Vault.open_with_password(NEW)
    assert fake.stored == vault.key


def test_cli_wrong_current_password(monkeypatch, capsys):
    monkeypatch.setattr(biometric, "_backend", FakeBackend())
    saved_vault()
    before = vault_path().read_bytes()
    scripted_getpass(monkeypatch, "wrong-one")
    with pytest.raises(SystemExit) as exc:
        cli.main(["--change-password"])
    assert exc.value.code == 1
    assert "Wrong password" in capsys.readouterr().err
    assert vault_path().read_bytes() == before


def test_cli_new_password_retries_then_gives_up(monkeypatch, capsys):
    monkeypatch.setattr(biometric, "_backend", FakeBackend())
    saved_vault()
    scripted_getpass(monkeypatch, OLD, "short", "short", NEW, "typo", OLD, OLD)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--change-password"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "at least 8" in err and "did not match" in err and "differ" in err
    Vault.open_with_password(OLD)


def test_cli_change_password_without_vault(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--change-password"])
    assert exc.value.code == 1
    assert "No vault" in capsys.readouterr().err
    assert not os.path.exists(vault_path())
