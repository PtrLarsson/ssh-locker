import getpass
import sys

from ssh_locker.app import SshLockerApp
from ssh_locker.connect import launch
from ssh_locker.unlock import unlock
from ssh_locker.vault import VaultError


def main() -> None:
    try:
        vault = unlock(getpass.getpass)
    except VaultError as exc:
        print(f"ssh-locker: {exc}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print(file=sys.stderr)
        sys.exit(1)

    connection = SshLockerApp(vault).run()
    if connection is None:
        return

    # The TUI has restored the terminal by now; hand it over to ssh.
    try:
        launch(connection)
    except FileNotFoundError:
        print("ssh-locker: could not find the 'ssh' command", file=sys.stderr)
        sys.exit(127)
