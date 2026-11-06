"""Render the README screenshot (docs/screenshot.svg) with made-up example data.

Runs the real app headless against a throwaway vault, so it never touches
your own vault. Usage: .venv/bin/python scripts/screenshot.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "screenshot.svg"

# Reserved example domains (RFC 2606) and documentation addresses (RFC 5737).
EXAMPLES = [
    ("Acme web prod", "web1.acme.example", 22, "deploy", "green", "Behind the load balancer"),
    ("Acme web staging", "staging.acme.example", 2222, "deploy", "yellow", "Reset nightly"),
    ("Acme database", "db.acme.example", 22, "dba", "red", "Primary, be careful"),
    ("Blog", "blog.example.org", 22, "peter", "blue", ""),
    ("Build server", "ci.example.net", 2200, "builder", "purple", "Runs the nightly builds"),
    ("Home NAS", "192.0.2.20", 22, "admin", "cyan", "Backups"),
    ("Raspberry Pi", "198.51.100.7", 22, "pi", None, ""),
]


async def main() -> None:
    with tempfile.TemporaryDirectory() as home:
        os.environ["SSH_LOCKER_HOME"] = home

        import ssh_locker.vault as vault_mod
        from ssh_locker.app import SshLockerApp
        from ssh_locker.models import Connection
        from ssh_locker.vault import Vault

        vault_mod.KDF_LOG2_N = 14  # throwaway vault; no need for the full cost
        vault = Vault.create("example-password")
        vault.connections.extend(
            Connection(name, host, port, user, "secret", color=color, comment=comment)
            for name, host, port, user, color, comment in EXAMPLES
        )

        app = SshLockerApp(vault)
        async with app.run_test(size=(100, 14)) as pilot:
            await pilot.press("down", "down")
            await pilot.pause()
            OUTPUT.parent.mkdir(exist_ok=True)
            OUTPUT.write_text(app.export_screenshot(title="ssh-locker"))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
