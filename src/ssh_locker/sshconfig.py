"""Minimal ~/.ssh/config reader used by the import screen."""

import glob
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".ssh" / "config"
WILDCARD = re.compile(r"[*?!]")


@dataclass
class ImportedHost:
    alias: str
    hostname: str
    port: int
    user: str


def _lines(path: Path, seen: set[Path]) -> Iterator[tuple[str, list[str]]]:
    """Yield (lowercased keyword, values) with Include directives expanded."""
    try:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        text = path.read_text()
    except OSError:
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"(\S+?)\s*(?:=\s*|\s+)(.*)$", line)
        if not match:
            continue
        keyword = match.group(1).lower()
        try:
            values = shlex.split(match.group(2), comments=True)
        except ValueError:
            continue
        if keyword == "include":
            for pattern in values:
                pattern = str(Path(pattern).expanduser())
                if not Path(pattern).is_absolute():
                    pattern = str(path.parent / pattern)
                for included in sorted(glob.glob(pattern)):
                    yield from _lines(Path(included), seen)
        else:
            yield keyword, values


def parse_ssh_config(path: Path | None = None) -> list[ImportedHost]:
    path = path or DEFAULT_CONFIG
    hosts: list[ImportedHost] = []
    aliases: list[str] | None = None
    settings: dict[str, str] = {}

    def flush() -> None:
        for alias in aliases or []:
            try:
                port = int(settings.get("port", "22"))
            except ValueError:
                port = 22
            hosts.append(
                ImportedHost(
                    alias,
                    settings.get("hostname", alias),
                    port,
                    settings.get("user", ""),
                )
            )

    for keyword, values in _lines(path, set()):
        if keyword == "host":
            flush()
            aliases = [v for v in values if not WILDCARD.search(v)]
            settings = {}
        elif keyword == "match":
            flush()
            aliases = None
            settings = {}
        elif aliases is not None and values and keyword not in settings:
            settings[keyword] = values[0]
    flush()
    return hosts
