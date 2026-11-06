import pytest
from textual.widgets import Checkbox, DataTable, Input, Static

from ssh_locker.app import SshLockerApp
from ssh_locker.models import Connection
from ssh_locker.screens import validate_connection
from ssh_locker.vault import Vault

SIZE = (100, 40)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))
    v = Vault.create("pw")
    v.connections.extend(
        [
            Connection("alpha", "alpha.example", 22, "u1", "pw-alpha"),
            Connection("beta", "beta.example", 2222, "u2", None),
        ]
    )
    v.save()
    return v


def fill(app, **fields):
    for field_id, value in fields.items():
        app.screen.query_one(f"#{field_id}", Input).value = value


def persisted(vault):
    return Vault.open_with_key(vault.key).connections


# -- validation (no UI) ------------------------------------------------------


@pytest.mark.parametrize(
    "conn",
    [
        Connection("", "h"),
        Connection("   ", "h"),
        Connection("n", ""),
        Connection("n", "   "),
        Connection("n", "h", 0),
        Connection("n", "h", 65536),
        Connection("dup", "h"),
    ],
)
def test_validate_rejects(conn):
    existing = [Connection("dup", "x")]
    assert validate_connection(conn, existing, None)


def test_validate_rejects_non_int_port():
    conn = Connection("n", "h", "abc")  # the form passes the raw value through
    assert validate_connection(conn, [], None)


def test_validate_editing_keeps_own_name():
    existing = [Connection("dup", "x")]
    assert validate_connection(Connection("dup", "y"), existing, existing[0]) is None


def test_validate_accepts_valid():
    assert validate_connection(Connection("n", "h", 65535, "u"), [], None) is None


# -- New / Edit / Delete -----------------------------------------------------


async def test_new_adds_and_persists(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n")
        fill(app, name="gamma", host="gamma.example", port="2200",
             username="u3", password="s3cret")
        await pilot.click("#save")
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 3
    assert persisted(vault)[-1] == Connection(
        "gamma", "gamma.example", 2200, "u3", "s3cret"
    )


async def test_new_blank_password_stored_as_none(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n")
        fill(app, name="gamma", host="gamma.example")
        await pilot.click("#save")
        await pilot.pause()
    assert persisted(vault)[-1].password is None
    assert persisted(vault)[-1].port == 22


async def test_edit_changes_selected_and_keeps_password_when_blank(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("e")
        assert app.screen.query_one("#name", Input).value == "alpha"
        fill(app, host="new.example", password="")
        await pilot.click("#save")
        await pilot.pause()
    first = persisted(vault)[0]
    assert (first.host, first.password) == ("new.example", "pw-alpha")


async def test_edit_clear_password_checkbox(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("e")
        app.screen.query_one("#clear-password", Checkbox).value = True
        await pilot.click("#save")
        await pilot.pause()
    assert persisted(vault)[0].password is None


async def test_edit_imported_password_only_stays_imported(vault):
    vault.connections[0] = Connection("web", "web", 22, "", None, imported=True)
    vault.save()
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("e")
        fill(app, password="added")
        await pilot.click("#save")
        await pilot.pause()
    first = persisted(vault)[0]
    assert first.imported is True and first.password == "added"


async def test_edit_imported_host_change_takes_over_details(vault):
    vault.connections[0] = Connection("web", "web", 22, "", None, imported=True)
    vault.save()
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("e")
        fill(app, host="other.example")
        await pilot.click("#save")
        await pilot.pause()
    assert persisted(vault)[0].imported is False


async def test_delete_requires_confirmation(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d")
        await pilot.press("n")
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 2
        await pilot.press("d")
        await pilot.press("y")
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1
    assert [c.name for c in persisted(vault)] == ["beta"]


async def test_form_error_keeps_dialog_open(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n")
        fill(app, name="alpha", host="x")  # duplicate name
        await pilot.click("#save")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        assert "already" in str(app.screen.query_one("#error", Static).render())
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    assert len(persisted(vault)) == 2


async def test_non_numeric_port_shows_error(vault):
    app = SshLockerApp(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n")
        fill(app, name="x", host="h", port="abc")
        await pilot.click("#save")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        assert "ort" in str(app.screen.query_one("#error", Static).render())
