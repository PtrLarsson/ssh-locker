"""Build and run the ssh command for a saved connection.

Saved passwords reach ssh through SSH_ASKPASS reading an environment variable,
so they never appear in ssh's argv.
"""

import os
import sys
from pathlib import Path
from typing import NoReturn

from ssh_locker.models import Connection

ASKPASS = Path(__file__).with_name("askpass.sh")


def build_launch(conn: Connection) -> tuple[list[str], dict[str, str]]:
    # A wrong saved password must not be retried: repeated failures trip
    # lockouts, and ssh would just feed it the same answer again.
    once = ["-o", "NumberOfPasswordPrompts=1"] if conn.password is not None else []
    if conn.imported:
        argv = ["ssh", *once, "--", conn.name]
    else:
        target = f"{conn.username}@{conn.host}" if conn.username else conn.host
        argv = ["ssh", *once, "-p", str(conn.port), "--", target]
    if conn.password is None:
        return argv, {}

    return argv, {
        "SSH_ASKPASS": str(ASKPASS),
        "SSH_ASKPASS_REQUIRE": "force",
        "SSH_LOCKER_PASSWORD": conn.password,
        "SSH_LOCKER_PYTHON": sys.executable,
    }


def launch(conn: Connection) -> NoReturn:
    argv, extra_env = build_launch(conn)
    os.execvpe("ssh", argv, {**os.environ, **extra_env})
