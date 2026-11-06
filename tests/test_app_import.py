import pytest
from textual.widgets import DataTable, SelectionList, Static

from ssh_locker.app import SshLockerApp
from ssh_locker.connect import build_launch
from ssh_locker.models import Connection
from ssh_locker.vault import Vault

SIZE = (100, 40)

CONFIG = """\
Host web
  HostName web.example.com
  Port 2222
  User deploy
Host db
  HostName db.example.com
"""


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path / "home"))
    return Vault.create("pw")


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ssh_config"
    path.write_text(CONFIG)
    return path


def persisted(vault):
    return Vault.open_with_key(vault.key).connections


async def test_import_selected_hosts_added_as_imported(vault, config):
    app = SshLockerApp(vault, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        app.screen.query_one(SelectionList).select("web")
        await pilot.click("#import")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.query_one(DataTable).row_count == 1
    assert persisted(vault) == [
        Connection("web", "web.example.com", 2222, "deploy", None, imported=True)
    ]
    assert (persisted(vault)[0].color, persisted(vault)[0].comment) == (None, "")


async def test_space_toggles_highlighted_host(vault, config):
    app = SshLockerApp(vault, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        await pilot.press("space")
        await pilot.click("#import")
        await pilot.pause()
    assert [c.name for c in persisted(vault)] == ["web"]


async def test_already_saved_name_not_selectable(vault, config):
    vault.connections.append(Connection("web", "mine.example", 22, "me"))
    vault.save()
    app = SshLockerApp(vault, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        selection = app.screen.query_one(SelectionList)
        selection.select("web")
        selection.select("db")
        await pilot.click("#import")
        await pilot.pause()
    names = [c.name for c in persisted(vault)]
    assert names == ["web", "db"]
    assert persisted(vault)[0].host == "mine.example"  # untouched


async def test_no_config_shows_message_and_closes(vault, tmp_path):
    app = SshLockerApp(vault, ssh_config_path=tmp_path / "missing")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        await pilot.pause()
        text = str(app.screen.query_one("#message", Static).render())
        assert "No hosts found in ~/.ssh/config" in text
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        await pilot.press("i")
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.is_running


async def test_cancel_adds_nothing(vault, config):
    app = SshLockerApp(vault, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        app.screen.query_one(SelectionList).select("web")
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    assert persisted(vault) == []


async def test_imported_connection_launches_via_alias(vault, config):
    app = SshLockerApp(vault, ssh_config_path=config)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i")
        app.screen.query_one(SelectionList).select("db")
        await pilot.click("#import")
        await pilot.pause()
        await pilot.press("enter")
    argv, env = build_launch(app.return_value)
    assert argv == ["ssh", "db"]
    assert env == {}
