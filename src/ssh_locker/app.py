from pathlib import Path

from rich.segment import Segments
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header

from ssh_locker.models import COLORS, Connection
from ssh_locker.screens import ConfirmDelete, ConnectionForm, ImportScreen
from ssh_locker.sshconfig import ImportedHost, parse_ssh_config
from ssh_locker.vault import Vault, VaultError

def name_cell(conn: Connection) -> Text:
    """The name, led by its colour square (blank when it has no colour)."""
    if conn.color in COLORS:
        return Text.assemble(("\u25a0", COLORS[conn.color]), " ", conn.name)
    return Text(f"  {conn.name}")


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

    def __init__(self, vault: Vault, ssh_config_path: Path | None = None):
        super().__init__()
        self.vault = vault
        self._ssh_config_path = ssh_config_path

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Host:Port", "User", "Comment")
        self.refresh_table()
        table.focus()

    def _fatal_error(self) -> None:
        # Textual's crash report includes local variables, which can hold a
        # typed or saved password. Report the error without them.
        from rich.traceback import Traceback

        self.bell()
        traceback = Traceback(show_locals=False, width=None)
        self._exit_renderables.append(
            Segments(self.console.render(traceback, self.console.options))
        )
        self._close_messages_no_wait()

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
            # Text cells are shown literally; plain strings would be parsed
            # as markup, and "[/x]" in a name or comment would crash the list.
            table.add_row(
                name_cell(conn),
                Text(f"{conn.host}:{conn.port}"),
                Text(conn.username),
                Text(conn.comment),
            )
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
        try:
            self.vault.save()
        except VaultError as exc:
            # Keep the change in memory so the session isn't lost; say so.
            self.notify(str(exc), severity="error", markup=False)
        self.refresh_table()

    def action_import_hosts(self) -> None:
        hosts = parse_ssh_config(self._ssh_config_path)
        saved = {c.name for c in self.vault.connections}

        def done(chosen: list[ImportedHost] | None) -> None:
            new = [h for h in chosen or [] if h.alias not in saved]
            if not new:
                return
            self.vault.connections.extend(
                Connection(h.alias, h.hostname, h.port, h.user, None, imported=True)
                for h in new
            )
            self._persist()

        self.push_screen(ImportScreen(hosts, saved), done)
