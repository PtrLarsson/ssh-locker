from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from ssh_locker.models import Connection


def validate_connection(
    conn: Connection,
    existing: list[Connection],
    editing: Connection | None,
) -> str | None:
    """Return an error message, or None when the connection is acceptable."""
    if not conn.name.strip():
        return "Name is required"
    if not conn.host.strip():
        return "Host is required"
    if not isinstance(conn.port, int) or not 1 <= conn.port <= 65535:
        return "Port must be a number from 1 to 65535"
    for other in existing:
        if other is not editing and other.name == conn.name:
            return f"A connection named '{conn.name}' already exists"
    return None


class ConnectionForm(ModalScreen[Connection | None]):
    """New/Edit dialog. Dismisses with the Connection, or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ConnectionForm { align: center middle; }
    ConnectionForm > Vertical {
        width: 60; height: auto; border: round $accent; padding: 1 2;
        background: $surface;
    }
    ConnectionForm .field { height: 1; margin-bottom: 1; }
    ConnectionForm .field Label { width: 12; }
    ConnectionForm .field Input { width: 1fr; }
    ConnectionForm #error { color: $error; height: auto; }
    ConnectionForm Horizontal.buttons { height: 3; align-horizontal: right; }
    """

    def __init__(self, existing: list[Connection], editing: Connection | None = None):
        super().__init__()
        self._existing = existing
        self._editing = editing

    def compose(self) -> ComposeResult:
        e = self._editing
        title = "Edit connection" if e else "New connection"
        with Vertical():
            yield Label(title)
            yield self._field("Name", "name", e.name if e else "")
            yield self._field("Host", "host", e.host if e else "")
            yield self._field("Port", "port", str(e.port) if e else "22")
            yield self._field("Username", "username", e.username if e else "")
            yield self._field("Password", "password", "", password=True)
            if e:
                yield Checkbox("Clear saved password", id="clear-password", compact=True)
            yield Static("", id="error")
            with Horizontal(classes="buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    @staticmethod
    def _field(label: str, field_id: str, value: str, password: bool = False):
        row = Horizontal(classes="field")
        row.compose_add_child(Label(label))
        row.compose_add_child(
            Input(value=value, id=field_id, password=password, compact=True)
        )
        return row

    def _value(self, field_id: str) -> str:
        return self.query_one(f"#{field_id}", Input).value

    def _submit(self) -> None:
        port_text = self._value("port").strip() or "22"
        port = int(port_text) if port_text.isdigit() else port_text
        password = self._value("password") or None
        e = self._editing
        imported = False
        if e:
            clear = self.query_one("#clear-password", Checkbox).value
            if password is None and not clear:
                password = e.password
            host, user = self._value("host").strip(), self._value("username").strip()
            # Host/port/user of an imported entry come from ~/.ssh/config; once
            # the user changes them, the entry is theirs and connects directly.
            imported = e.imported and (host, port, user) == (e.host, e.port, e.username)
        conn = Connection(
            name=self._value("name").strip(),
            host=self._value("host").strip(),
            port=port,
            username=self._value("username").strip(),
            password=password,
            imported=imported,
        )
        error = validate_connection(conn, self._existing, e)
        if error:
            self.query_one("#error", Static).update(error)
            return
        self.dismiss(conn)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDelete(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Delete"),
        Binding("n,escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmDelete { align: center middle; }
    ConfirmDelete > Vertical {
        width: 50; height: auto; border: round $error; padding: 1 2;
        background: $surface;
    }
    ConfirmDelete Horizontal { height: 3; align-horizontal: right; }
    """

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Delete '{self._name}'?  (y/n)")
            with Horizontal():
                yield Button("Delete", id="confirm", variant="error")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
