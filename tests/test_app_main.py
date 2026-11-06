import pytest
from textual.widgets import DataTable, Footer

from ssh_locker.app import SshLockerApp
from ssh_locker.models import COLORS, Connection
from ssh_locker.vault import Vault

CONNS = [
    Connection("Client A prod", "a.example.com", 22, "deploy", "topsecret-A"),
    Connection("Client B staging", "staging.b.se", 2222, "peter", "topsecret-B"),
    Connection("Home NAS", "192.168.1.20", 22, "admin"),
]


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))
    v = Vault.create("pw")
    v.connections.extend(CONNS)
    v.save()
    return v


@pytest.fixture
def empty_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_LOCKER_HOME", str(tmp_path))
    return Vault.create("pw")


def row_texts(app):
    table = app.query_one(DataTable)
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


async def test_lists_connections_in_order(vault):
    app = SshLockerApp(vault)
    async with app.run_test():
        assert row_texts(app) == [
            ["  Client A prod", "a.example.com:22", "deploy", ""],
            ["  Client B staging", "staging.b.se:2222", "peter", ""],
            ["  Home NAS", "192.168.1.20:22", "admin", ""],
        ]


async def test_color_square_before_name_and_comment_column(vault):
    vault.connections[0].color = "green"
    vault.connections[0].comment = "prod box"
    app = SshLockerApp(vault)
    async with app.run_test():
        table = app.query_one(DataTable)
        name_cell = table.get_row_at(0)[0]
        assert name_cell.plain == "■ Client A prod"
        square = name_cell.spans[0]
        assert (square.start, square.end) == (0, 1)
        assert str(square.style) == COLORS["green"]
        assert row_texts(app)[0][3] == "prod box"
        assert app.query_one(DataTable).ordered_columns[3].label.plain == "Comment"


async def test_password_not_rendered(vault):
    app = SshLockerApp(vault)
    async with app.run_test():
        screen_svg = app.export_screenshot()
        assert "topsecret" not in screen_svg
        assert "topsecret" not in str(row_texts(app))


async def test_down_moves_selection_and_enter_returns_that_connection(vault):
    app = SshLockerApp(vault)
    async with app.run_test() as pilot:
        await pilot.press("down", "enter")
    assert app.return_value == CONNS[1]


async def test_q_returns_none(vault):
    app = SshLockerApp(vault)
    async with app.run_test() as pilot:
        await pilot.press("q")
    assert app.return_value is None
    assert not app.is_running


@pytest.mark.parametrize("key", ["enter", "e", "d"])
async def test_empty_list_keys_do_nothing(empty_vault, key):
    app = SshLockerApp(empty_vault)
    async with app.run_test() as pilot:
        await pilot.press(key)
        await pilot.pause()
        assert app.is_running
        assert len(app.screen_stack) == 1


async def test_footer_lists_all_commands(vault):
    app = SshLockerApp(vault)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query(Footer)
        shown = {
            (b.key, b.description)
            for b in app.BINDINGS
            if b.show
        }
        assert shown == {
            ("enter", "Connect"),
            ("n", "New"),
            ("e", "Edit"),
            ("d", "Delete"),
            ("i", "Import"),
            ("p", "Password"),
            ("q", "Quit"),
        }
