import argparse
import getpass
import sys
from importlib.metadata import version

from ssh_locker import biometric
from ssh_locker.app import SshLockerApp
from ssh_locker.connect import launch
from ssh_locker.unlock import ATTEMPTS, new_password_problem, unlock
from ssh_locker.vault import Vault, VaultError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ssh-locker", description="Encrypted SSH connection manager."
    )
    parser.add_argument(
        "--version", action="version", version=f"ssh-locker {version('ssh-locker')}"
    )
    parser.add_argument(
        "--change-password",
        action="store_true",
        help="change the master password and exit",
    )
    args = parser.parse_args(argv)

    if args.change_password:
        try:
            sys.exit(change_password())
        except (KeyboardInterrupt, EOFError):
            print(file=sys.stderr)
            sys.exit(1)

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


def change_password() -> int:
    """Interactive master password change. Returns the exit code."""
    if not Vault.exists():
        print("ssh-locker: No vault yet; run ssh-locker to create one.", file=sys.stderr)
        return 1

    # The current password is always required, even where Touch ID would unlock.
    current = getpass.getpass("Current master password: ")
    try:
        vault = Vault.open_with_password(current)
    except VaultError as exc:
        print(f"ssh-locker: {exc}", file=sys.stderr)
        return 1

    for _ in range(ATTEMPTS):
        new = getpass.getpass("New master password: ")
        repeat = getpass.getpass("Repeat new master password: ")
        problem = new_password_problem(current, new, repeat)
        if problem:
            print(problem, file=sys.stderr)
            continue
        try:
            vault.change_password(current, new)
        except VaultError as exc:
            print(f"ssh-locker: {exc}", file=sys.stderr)
            return 1
        biometric.replace_key_if_present(vault.key)
        print("Master password changed.")
        return 0

    print("ssh-locker: master password not changed.", file=sys.stderr)
    return 1
