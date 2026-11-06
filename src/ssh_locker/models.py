from dataclasses import dataclass, field

# Label colours a connection can carry, shown as a square before its name.
# Mid-tone values stay readable on both light and dark terminals.
COLORS = {
    "red": "#e5534b",
    "orange": "#e0823d",
    "yellow": "#d4b72c",
    "green": "#57ab5a",
    "cyan": "#39c5cf",
    "blue": "#539bf5",
    "purple": "#b083f0",
    "grey": "#909dab",
}


@dataclass
class Connection:
    name: str
    host: str
    port: int = 22
    username: str = ""
    password: str | None = field(default=None, repr=False)
    imported: bool = False
    color: str | None = None
    comment: str = ""
