import sys
from collections.abc import Callable

from ssh_locker import biometric
from ssh_locker.vault import Vault, VaultError

ATTEMPTS = 3


def unlock(prompt_password: Callable[[str], str]) -> Vault:
    """Open (or on first run, create) the vault.

    Touch ID is tried first; the master password is the fallback and the root
    of the encryption. Raises VaultError when the vault cannot be opened.
    """
    if not Vault.exists():
        return _create(prompt_password)

    key = biometric.load_key()
    if key is not None:
        try:
            return Vault.open_with_key(key)
        except VaultError:
            pass  # stale shortcut (e.g. master key changed): use the password

    for attempt in range(ATTEMPTS):
        password = prompt_password("Master password: ")
        try:
            vault = Vault.open_with_password(password)
        except VaultError as exc:
            if attempt == ATTEMPTS - 1:
                raise
            print(str(exc), file=sys.stderr)
            continue
        biometric.store_key(vault.key)
        return vault
    raise VaultError("Could not unlock the vault")  # pragma: no cover


def _create(prompt_password: Callable[[str], str]) -> Vault:
    print("No vault found: choose a master password.", file=sys.stderr)
    for _ in range(ATTEMPTS):
        password = prompt_password("New master password: ")
        repeat = prompt_password("Repeat master password: ")
        if not password:
            print("The master password cannot be empty.", file=sys.stderr)
        elif password != repeat:
            print("The passwords did not match.", file=sys.stderr)
        else:
            vault = Vault.create(password)
            biometric.store_key(vault.key)
            return vault
    raise VaultError("No master password was set")
