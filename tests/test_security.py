"""Security properties of ssh-locker, grouped by what they protect."""

import os
import stat
import subprocess

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from textual.widgets import DataTable, Input

import ssh_locker.vault as vault_mod
from ssh_locker import biometric, unlock as unlock_mod
from ssh_locker.app import SshLockerApp
from ssh_locker.connect import build_launch
from ssh_locker.models import Connection
from ssh_locker.screens import validate_connection
from ssh_locker.sshconfig import parse_ssh_config
from ssh_locker.unlock import unlock
from ssh_locker.vault import Vault, VaultError, vault_path

SIZE = (100, 40)
SECRET = "S3cret-pa55word!"


@pytest.fixture(autouse=True)
def vault_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("SSH_LOCKER_HOME", str(home))
    return home


def saved_vault(password="master-pw") -> Vault:
    v = Vault.create(password)
    v.connections.append(Connection("a", "h.example", 22, "u", SECRET))
    v.save()
    return v


# -- Encryption at rest -------------------------------------------------------


@pytest.mark.real_kdf
def test_kdf_cost_meets_owasp_minimum():
    # OWASP password storage guidance: scrypt N >= 2^17, r = 8, p = 1.
    assert vault_mod.KDF_LOG2_N >= 17
    Vault.create("master-pw")
    raw = vault_path().read_bytes()
    assert raw[4] == 2  # format version
    assert raw[5] == vault_mod.KDF_LOG2_N  # cost recorded in the header


@pytest.mark.parametrize("offset", [4, 5, 6, 21])  # version, cost, salt, salt end
def test_header_tampering_is_detected(offset):
    saved_vault()
    path = vault_path()
    raw = bytearray(path.read_bytes())
    raw[offset] ^= 0x01
    path.write_bytes(bytes(raw))
    with pytest.raises(VaultError):
        Vault.open_with_password("master-pw")


def test_unreasonable_kdf_cost_in_file_is_rejected():
    saved_vault()
    path = vault_path()
    raw = bytearray(path.read_bytes())
    raw[5] = 40  # 2^40 scrypt would exhaust memory
    path.write_bytes(bytes(raw))
    with pytest.raises(VaultError):
        Vault.open_with_password("master-pw")


def test_every_save_uses_a_fresh_nonce():
    v = saved_vault()
    first = vault_path().read_bytes()
    v.save()
    second = vault_path().read_bytes()
    nonce = slice(vault_mod.HEADER_LEN, vault_mod.HEADER_LEN + vault_mod.NONCE_LEN)
    assert first[nonce] != second[nonce]
    assert first != second


def write_v1_vault(password: str, connections_json: bytes) -> bytes:
    """Write a vault in the original v1 format (scrypt N=2^15, no cost byte)."""
    salt = os.urandom(16)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())
    header = b"SSHL" + bytes([1]) + salt
    nonce = os.urandom(12)
    blob = header + nonce + AESGCM(key).encrypt(nonce, connections_json, header)
    vault_path().parent.mkdir(parents=True, exist_ok=True)
    vault_path().write_bytes(blob)
    return key


def test_v1_vault_opens_and_is_upgraded_on_password_unlock():
    old_key = write_v1_vault("master-pw", b'[{"name": "a", "host": "h"}]')
    vault = Vault.open_with_password("master-pw")
    assert [c.name for c in vault.connections] == ["a"]
    raw = vault_path().read_bytes()
    assert raw[4] == 2 and raw[5] == vault_mod.KDF_LOG2_N
    assert Vault.open_with_password("master-pw").connections == vault.connections
    with pytest.raises(VaultError):  # the old Touch ID key is now stale
        Vault.open_with_key(old_key)


def test_v1_vault_opened_by_key_stays_readable():
    old_key = write_v1_vault("master-pw", b'[{"name": "a", "host": "h"}]')
    vault = Vault.open_with_key(old_key)
    vault.save()
    assert Vault.open_with_key(old_key).connections == vault.connections
    assert Vault.open_with_password("master-pw").connections == vault.connections


def test_vault_directory_is_private(vault_home):
    vault_home.mkdir(mode=0o755)
    saved_vault()
    assert stat.S_IMODE(os.stat(vault_home).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(vault_path()).st_mode) == 0o600


class NoBiometric:
    def load_key(self):
        return None

    def store_key(self, key):
        return True


def test_master_password_needs_at_least_8_characters(monkeypatch):
    monkeypatch.setattr(unlock_mod, "biometric", NoBiometric())
    answers = iter(["short12", "short12", "long-enough", "long-enough"])
    shown = []

    def prompt(text):
        shown.append(text)
        return next(answers)

    unlock(prompt)
    assert len(shown) == 4
    Vault.open_with_password("long-enough")


# -- Secrets stay out of logs, reprs and crash reports ---------------------------


def test_password_not_in_connection_repr():
    assert SECRET not in repr(Connection("a", "h", 22, "u", SECRET))


def test_vault_repr_does_not_expose_key():
    v = saved_vault()
    assert v.key.hex() not in repr(v)
    assert SECRET not in repr(v)


async def test_crash_report_does_not_show_typed_password(monkeypatch):
    import ssh_locker.screens as screens

    def explode(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(screens, "validate_connection", explode)
    app = SshLockerApp(saved_vault())
    printed = []
    # Capture the crash report at the point the app would print it.
    monkeypatch.setattr(
        app, "_print_error_renderables", lambda: printed.extend(app._exit_renderables)
    )
    with pytest.raises(RuntimeError):
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("n")
            app.screen.query_one("#password", Input).value = "typed-" + SECRET
            await pilot.click("#save")
            await pilot.pause()
    report = "".join(segment.text for r in printed for segment in r.segments)
    assert "boom" in report  # the crash is still reported
    assert SECRET not in report


# -- ssh invocation: no option injection ------------------------------------------


@pytest.mark.parametrize(
    "conn",
    [
        Connection("x", "-oProxyCommand=touch /tmp/pwned"),
        Connection("x", "host with space"),
        Connection("x", "h", 22, "-oProxyCommand=evil"),
        Connection("x", "h", 22, "user@other"),
        Connection("x", "h", 22, "us er"),
    ],
)
def test_validation_rejects_values_ssh_would_parse_as_options(conn):
    assert validate_connection(conn, [], None)


@pytest.mark.parametrize("field", ["name", "host", "username", "comment"])
@pytest.mark.parametrize("bad", ["\x1b]0;pwned\x07", "line\nbreak", "nul\x00", "del\x7f"])
def test_validation_rejects_control_characters(field, bad):
    values = {"name": "n", "host": "h", "username": "u", "comment": "c"}
    values[field] = bad
    assert validate_connection(Connection(**values), [], None)


def test_destination_is_separated_from_options():
    argv, _ = build_launch(Connection("a", "h.example", 22, "u", "pw"))
    assert argv[-2:] == ["--", "u@h.example"]
    argv, _ = build_launch(Connection("-web", "h", imported=True))
    assert argv[-2:] == ["--", "-web"]


def test_import_skips_unsafe_hosts(tmp_path):
    config = tmp_path / "config"
    config.write_text(
        "Host -oProxyCommand=evil\n"
        "Host ok\n  HostName -oProxyCommand=evil\n"
        "Host fine\n  HostName fine.example\n"
    )
    assert [h.alias for h in parse_ssh_config(config)] == ["fine"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Enter passphrase for key '/Users/x/.ssh/id_ed25519': ",
        "Verification code: ",
        "Enter PIN for authenticator: ",
    ],
)
def test_askpass_never_gives_saved_password_to_other_prompts(prompt):
    _, env = build_launch(Connection("a", "h", 22, "u", SECRET))
    result = subprocess.run(
        [env["SSH_ASKPASS"], prompt],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        start_new_session=True,  # no controlling tty
    )
    assert SECRET not in result.stdout


# -- Untrusted text is displayed, never interpreted ---------------------------------


async def test_markup_in_fields_is_shown_literally():
    v = saved_vault()
    v.connections.append(Connection("[red]x[/red]", "h2", comment="[/oops] [link=x]y"))
    v.save()
    app = SshLockerApp(v)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        row = app.query_one(DataTable).get_row_at(1)
        assert str(row[0]).strip() == "[red]x[/red]"
        assert str(row[3]) == "[/oops] [link=x]y"
        app.export_screenshot()  # forces a full render


async def test_markup_in_duplicate_name_error_is_shown_literally():
    v = Vault.create("master-pw")
    v.connections.append(Connection("[/oops]", "h"))
    v.save()
    app = SshLockerApp(v)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n")
        app.screen.query_one("#name", Input).value = "[/oops]"
        app.screen.query_one("#host", Input).value = "h2"
        await pilot.click("#save")
        await pilot.pause()
        app.export_screenshot()
        assert "[/oops]" in str(app.screen.query_one("#error").render())


async def test_markup_in_name_does_not_break_delete_dialog():
    v = Vault.create("master-pw")
    v.connections.append(Connection("[/oops]", "h"))
    v.save()
    app = SshLockerApp(v)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d")
        await pilot.pause()
        app.export_screenshot()
        await pilot.press("y")
        await pilot.pause()
    assert Vault.open_with_key(v.key).connections == []


async def test_markup_in_ssh_config_does_not_break_import(tmp_path):
    config = tmp_path / "config"
    config.write_text("Host [/oops]\n  HostName [bold]h\n")
    v = Vault.create("master-pw")
    app = SshLockerApp(v, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        await pilot.pause()
        app.export_screenshot()
        assert app.is_running


# -- Keychain ---------------------------------------------------------------------


def test_keychain_item_is_device_only_and_never_synced(monkeypatch):
    import Security

    added = []
    monkeypatch.setattr(Security, "SecItemDelete", lambda query: 0)
    monkeypatch.setattr(
        Security, "SecItemAdd", lambda item, _: (added.append(item), (0, None))[1]
    )
    biometric._MacBackend().put(b"k" * 32)
    (item,) = added
    assert (
        item[Security.kSecAttrAccessible]
        == Security.kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    )
    assert not item.get(Security.kSecAttrSynchronizable, False)
