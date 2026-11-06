import os
import subprocess
import sys
from pathlib import Path

import pytest

from ssh_locker import connect
from ssh_locker.connect import build_launch, launch
from ssh_locker.models import Connection

TRICKY = 'sp ace $x "q" \\ é'


def test_imported_uses_alias():
    conn = Connection("web", "web.example.com", 2222, "deploy", imported=True)
    assert build_launch(conn) == (["ssh", "web"], {})


def test_imported_with_password_uses_alias_and_askpass():
    conn = Connection("web", "web.example.com", 22, "deploy", "pw", imported=True)
    argv, env = build_launch(conn)
    assert argv == ["ssh", "web"]
    assert env["SSH_LOCKER_PASSWORD"] == "pw"
    assert env["SSH_ASKPASS_REQUIRE"] == "force"


def test_no_password_has_no_askpass_env():
    argv, env = build_launch(Connection("a", "h.example", 2200, "u"))
    assert argv == ["ssh", "-p", "2200", "u@h.example"]
    assert env == {}


def test_with_password_env_and_argv_clean():
    argv, env = build_launch(Connection("a", "h.example", 22, "u", TRICKY))
    assert not any(TRICKY in part for part in argv)
    assert env["SSH_ASKPASS_REQUIRE"] == "force"
    assert env["SSH_LOCKER_PASSWORD"] == TRICKY
    assert Path(env["SSH_ASKPASS"]).is_absolute()
    assert os.access(env["SSH_ASKPASS"], os.X_OK)


def test_empty_username_omits_user_at():
    argv, _ = build_launch(Connection("a", "h.example", 22, ""))
    assert argv == ["ssh", "-p", "22", "h.example"]


def run_askpass(prompt: str, **kwargs) -> subprocess.CompletedProcess:
    _, env = build_launch(Connection("a", "h", 22, "u", TRICKY))
    return subprocess.run(
        [env["SSH_ASKPASS"], prompt],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        **kwargs,
    )


def test_askpass_answers_password_prompt():
    result = run_askpass("peter@host's password: ")
    assert result.returncode == 0
    assert result.stdout.removesuffix("\n") == TRICKY


def test_askpass_does_not_answer_hostkey_prompt():
    # start_new_session detaches from the controlling tty, so /dev/tty is unusable
    result = run_askpass(
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
        start_new_session=True,
    )
    assert result.returncode == 1
    assert TRICKY not in result.stdout


def test_launch_execs_ssh(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.os, "execvpe", lambda *a: calls.append(a))
    conn = Connection("a", "h.example", 22, "u", "pw")
    launch(conn)
    argv, extra = build_launch(conn)
    (file, got_argv, got_env), = calls
    assert file == "ssh"
    assert got_argv == argv
    assert got_env["SSH_LOCKER_PASSWORD"] == "pw"
    assert got_env["PATH"] == os.environ["PATH"]
