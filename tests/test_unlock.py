from types import SimpleNamespace

import pytest

from ssh_locker import cli, unlock as unlock_mod
from ssh_locker.models import Connection
from ssh_locker.unlock import unlock
from ssh_locker.vault import Vault, VaultError, vault_path


@pytest.fixture(autouse=True)
def vault_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))


class FakeBiometric:
    def __init__(self, key=None):
        self.key = key
        self.stored = []

    def load_key(self):
        return self.key

    def store_key(self, key):
        self.stored.append(key)
        return True


@pytest.fixture
def bio(monkeypatch):
    fake = FakeBiometric()
    monkeypatch.setattr(unlock_mod, "biometric", fake)
    return fake


class Prompts:
    """Scripted stand-in for getpass; records the prompts it was shown."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.shown = []

    def __call__(self, prompt):
        self.shown.append(prompt)
        return self.answers.pop(0)


def existing_vault():
    v = Vault.create("pw")
    v.connections.append(Connection("a", "h"))
    v.save()
    return v


def test_first_run_creates_vault_and_enrols_touch_id(bio):
    vault = unlock(Prompts("secret-pw", "secret-pw"))
    assert Vault.exists()
    assert bio.stored == [vault.key]
    assert Vault.open_with_password("secret-pw").connections == []


def test_first_run_mismatch_asks_again(bio):
    prompts = Prompts("first-one", "second-one", "same-same", "same-same")
    unlock(prompt_password=prompts)
    assert len(prompts.shown) == 4
    Vault.open_with_password("same-same")


def test_first_run_empty_password_rejected(bio):
    prompts = Prompts("", "", "okay-okay", "okay-okay")
    unlock(prompts)
    Vault.open_with_password("okay-okay")


def test_touch_id_success_never_prompts_password(bio):
    v = existing_vault()
    bio.key = v.key
    prompts = Prompts()
    vault = unlock(prompts)
    assert prompts.shown == []
    assert vault.connections == [Connection("a", "h")]


def test_touch_id_cancel_falls_back_to_password(bio):
    existing_vault()
    prompts = Prompts("pw")
    vault = unlock(prompts)
    assert len(prompts.shown) == 1
    assert vault.connections == [Connection("a", "h")]


def test_stale_touch_id_key_falls_back_to_password(bio):
    existing_vault()
    bio.key = b"\x00" * 32
    vault = unlock(Prompts("pw"))
    assert vault.connections == [Connection("a", "h")]


def test_wrong_password_three_times_raises_and_leaves_file(bio):
    existing_vault()
    before = vault_path().read_bytes()
    prompts = Prompts("x", "y", "z")
    with pytest.raises(VaultError):
        unlock(prompts)
    assert len(prompts.shown) == 3
    assert vault_path().read_bytes() == before
    assert bio.stored == []


def test_stale_key_is_replaced_after_password_unlock(bio):
    v = existing_vault()
    bio.key = b"\x00" * 32
    unlock(Prompts("pw"))
    assert bio.stored == [v.key]


def test_missing_touch_id_item_is_not_recreated_silently(bio):
    existing_vault()  # load_key() -> None: cancelled, or the owner deleted the item
    unlock(Prompts("pw"))
    assert bio.stored == []


# -- cli.main ----------------------------------------------------------------


def test_main_exits_1_with_message_on_vault_error(monkeypatch, capsys):
    def boom(prompt):
        raise VaultError("Wrong password or damaged vault")

    monkeypatch.setattr(cli, "unlock", boom)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Wrong password or damaged vault" in err
    assert "Traceback" not in err


def test_main_launches_selected_connection(monkeypatch):
    conn = Connection("a", "h")
    launched = []
    monkeypatch.setattr(cli, "unlock", lambda prompt: object())
    monkeypatch.setattr(
        cli, "SshLockerApp", lambda vault: SimpleNamespace(run=lambda: conn)
    )
    monkeypatch.setattr(cli, "launch", launched.append)
    cli.main([])
    assert launched == [conn]


def test_main_quit_does_not_launch(monkeypatch):
    launched = []
    monkeypatch.setattr(cli, "unlock", lambda prompt: object())
    monkeypatch.setattr(
        cli, "SshLockerApp", lambda vault: SimpleNamespace(run=lambda: None)
    )
    monkeypatch.setattr(cli, "launch", launched.append)
    cli.main([])
    assert launched == []


def test_main_reports_missing_ssh(monkeypatch, capsys):
    def no_ssh(conn):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(cli, "unlock", lambda prompt: object())
    monkeypatch.setattr(
        cli, "SshLockerApp", lambda vault: SimpleNamespace(run=lambda: Connection("a", "h"))
    )
    monkeypatch.setattr(cli, "launch", no_ssh)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 127
    assert "ssh" in capsys.readouterr().err


def test_main_version(capsys):
    from importlib.metadata import version

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"ssh-locker {version('ssh-locker')}"
