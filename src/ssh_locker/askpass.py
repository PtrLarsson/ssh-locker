"""SSH_ASKPASS helper (stdlib only; run as a script by askpass.sh).

Answers password prompts with $SSH_LOCKER_PASSWORD. Any other prompt (for
example the host-key "yes/no" question) is put to the user on /dev/tty, so the
saved password is never typed into the wrong question.
"""

import os
import re
import sys
import termios


def main(argv: list[str]) -> int:
    prompt = argv[1] if len(argv) > 1 else ""

    if re.search(r"password", prompt, re.IGNORECASE):
        password = os.environ.get("SSH_LOCKER_PASSWORD")
        if password is None:
            return 1
        sys.stdout.write(password + "\n")
        return 0

    try:
        # Separate read and write handles: a text-mode "r+" tty cannot switch
        # from writing to reading (io.UnsupportedOperation).
        with open("/dev/tty") as rd, open("/dev/tty", "w") as wr:
            # Only the host-key yes/no question is typed in the open; anything
            # else (key passphrase, verification code, PIN) is a secret.
            hidden = "yes/no" not in prompt
            answer = _ask(rd, wr, prompt, hidden)
    except (OSError, termios.error):
        return 1
    sys.stdout.write(answer)
    return 0


def _ask(rd, wr, prompt: str, hidden: bool) -> str:
    fd = rd.fileno()
    saved = termios.tcgetattr(fd) if hidden else None
    try:
        if saved is not None:
            quiet = list(saved)
            quiet[3] &= ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, quiet)
        wr.write(prompt)
        wr.flush()
        return rd.readline()
    finally:
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            wr.write("\n")
            wr.flush()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
