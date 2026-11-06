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
    assert argv == ["ssh", "-o", "NumberOfPasswordPrompts=1", "web"]
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


def test_saved_password_is_offered_only_once():
    argv, _ = build_launch(Connection("a", "h.example", 22, "u", "wrong"))
    assert argv[:3] == ["ssh", "-o", "NumberOfPasswordPrompts=1"]
    argv, _ = build_launch(Connection("a", "h.example", 22, "u"))
    assert "NumberOfPasswordPrompts=1" not in argv


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


def run_on_pty(prompt: str, typed: str, tmp_path):
    """Run askpass with a real controlling tty; return (tty output, stdout file text)."""
    import pty
    import select

    out_file = tmp_path / "answer"
    _, env = build_launch(Connection("a", "h", 22, "u", TRICKY))
    pid, master = pty.fork()
    if pid == 0:
        os.environ.update(env)
        os.execvp(
            "sh",
            ["sh", "-c", '"$0" "$1" >"$2"', env["SSH_ASKPASS"], prompt, str(out_file)],
        )
    seen = b""
    typed_sent = False
    while True:
        ready, _, _ = select.select([master], [], [], 5)
        if not ready:
            break
        try:
            chunk = os.read(master, 1024)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
        if not typed_sent and prompt.encode() in seen:
            os.write(master, typed.encode())
            typed_sent = True
    os.waitpid(pid, 0)
    return seen.decode(errors="replace"), out_file.read_text()


def test_askpass_does_not_echo_secret_typed_at_other_prompts(tmp_path):
    shown, answer = run_on_pty("Enter passphrase for key '/k': ", "hunter2\n", tmp_path)
    assert answer == "hunter2\n"
    assert "hunter2" not in shown


def test_askpass_echoes_hostkey_answer(tmp_path):
    shown, answer = run_on_pty(
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
        "yes\n",
        tmp_path,
    )
    assert answer == "yes\n"
    assert "yes" in shown.split("fingerprint])?", 1)[1]
