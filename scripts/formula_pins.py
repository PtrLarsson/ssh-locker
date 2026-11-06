"""Print the Homebrew formula's pinned Python resources as requirements.

Lets pip-audit check the exact versions that `brew install` builds.
Usage: python scripts/formula_pins.py Formula/ssh-locker.rb > requirements.txt
"""

import re
import sys

RESOURCE = re.compile(
    r'resource "(?P<name>[^"]+)" do\s+url "[^"]*/(?P<file>[^"/]+)"', re.MULTILINE
)
ARCHIVE = re.compile(r"\.(tar\.gz|tar\.bz2|zip)$")


def pins(formula: str) -> list[str]:
    result = []
    for match in RESOURCE.finditer(formula):
        # sdist file names are <name>-<version>.<ext>
        stem = ARCHIVE.sub("", match["file"])
        version = stem.rsplit("-", 1)[1]
        result.append(f"{match['name']}=={version}")
    return result


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print("\n".join(pins(f.read())))
