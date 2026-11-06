from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header

from ssh_locker.models import Connection
from ssh_locker.screens import ConfirmDelete, ConnectionForm
from ssh_locker.vault import Vault

MAIN_ACTIONS = {"connect", "new", "edit", "delete", "import_hosts", "quit"}


class SshLockerApp(App[Connection | None]):
    TITLE = "ssh-locker"
    BINDINGS = [
        Binding("enter", "connect", "Connect", priority=True),
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("i", "import_hosts", "Import"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, vault: Vault):
        super().__init__()
        self.vault = vault

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Host:Port", "User")
        self.refresh_table()
        table.focus()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # Main-screen commands are inactive while a dialog is open.
        if action in MAIN_ACTIONS and len(self.screen_stack) > 1:
            return False
        return True

    def refresh_table(self) -> None:
        table = self.query_one(DataTable)
        cursor = table.cursor_row
        table.clear()
        for conn in self.vault.connections:
            table.add_row(conn.name, f"{conn.host}:{conn.port}", conn.username)
        if table.row_count:
            table.move_cursor(row=min(cursor, table.row_count - 1))

    def selected(self) -> Connection | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return self.vault.connections[table.cursor_row]

    def action_connect(self) -> None:
        conn = self.selected()
        if conn is not None:
            self.exit(conn)

    def action_quit(self) -> None:
        self.exit(None)

    def action_new(self) -> None:
        def done(conn: Connection | None) -> None:
            if conn is not None:
                self.vault.connections.append(conn)
                self._persist()

        self.push_screen(ConnectionForm(self.vault.connections), done)

    def action_edit(self) -> None:
        current = self.selected()
        if current is None:
            return

        def done(conn: Connection | None) -> None:
            if conn is not None:
                index = self.vault.connections.index(current)
                self.vault.connections[index] = conn
                self._persist()

        self.push_screen(ConnectionForm(self.vault.connections, current), done)

    def action_delete(self) -> None:
        current = self.selected()
        if current is None:
            return

        def done(confirmed: bool | None) -> None:
            if confirmed:
                self.vault.connections.remove(current)
                self._persist()

        self.push_screen(ConfirmDelete(current.name), done)

    def _persist(self) -> None:
        self.vault.save()
        self.refresh_table()

    def action_import_hosts(self) -> None:
        pass
