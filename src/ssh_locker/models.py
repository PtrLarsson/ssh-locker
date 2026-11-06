from dataclasses import dataclass


@dataclass
class Connection:
    name: str
    host: str
    port: int = 22
    username: str = ""
    password: str | None = None
    imported: bool = False
