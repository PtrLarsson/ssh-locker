"""SSH_ASKPASS helper (stdlib only; run as a script by askpass.sh).

Answers password prompts with $SSH_LOCKER_PASSWORD. Any other prompt (for
example the host-key "yes/no" question) is put to the user on /dev/tty, so the
saved password is never typed into the wrong question.
"""

import os
import re
import sys


def main(argv: list[str]) -> int:
    prompt = argv[1] if len(argv) > 1 else ""

    if re.search(r"password", prompt, re.IGNORECASE):
        password = os.environ.get("SSH_LOCKER_PASSWORD")
        if password is None:
            return 1
        sys.stdout.write(password + "\n")
        return 0

    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(prompt)
            tty.flush()
            answer = tty.readline()
    except OSError:
        return 1
    sys.stdout.write(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
