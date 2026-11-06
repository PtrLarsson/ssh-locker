"""Touch ID shortcut to the vault key.

macOS refuses biometric-protected Keychain items for unsigned programs
(errSecMissingEntitlement, -34018), so the Touch ID check is enforced by this
app (LocalAuthentication prompt) and the key sits in a plain login-Keychain
item. The master password remains the root of the encryption.

Nothing in this module raises: every failure maps to False / None so callers
fall back to the master password prompt.
"""

import threading

SERVICE = "ssh-locker"
ACCOUNT = "vault-key"
REASON = "Unlock ssh-locker"
PROMPT_TIMEOUT = 60


class _MacBackend:
    def _query(self):
        import Security as S

        return {
            S.kSecClass: S.kSecClassGenericPassword,
            S.kSecAttrService: SERVICE,
            S.kSecAttrAccount: ACCOUNT,
        }

    def available(self) -> bool:
        import LocalAuthentication as LA

        context = LA.LAContext.alloc().init()
        ok, _ = context.canEvaluatePolicy_error_(
            LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics, None
        )
        return bool(ok)

    def put(self, key: bytes) -> None:
        import Foundation as F
        import Security as S

        self.delete()
        item = self._query()
        item[S.kSecValueData] = F.NSData.dataWithBytes_length_(key, len(key))
        item[S.kSecAttrAccessible] = S.kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        status, _ = S.SecItemAdd(item, None)
        if status != 0:
            raise RuntimeError(f"SecItemAdd failed: {status}")

    def get(self) -> bytes:
        import LocalAuthentication as LA
        import Security as S

        context = LA.LAContext.alloc().init()
        done = threading.Event()
        result = {}

        def reply(success, error):
            result["ok"] = bool(success)
            done.set()

        context.evaluatePolicy_localizedReason_reply_(
            LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics, REASON, reply
        )
        if not done.wait(PROMPT_TIMEOUT) or not result.get("ok"):
            raise RuntimeError("Touch ID failed or cancelled")

        query = self._query()
        query[S.kSecReturnData] = True
        query[S.kSecMatchLimit] = S.kSecMatchLimitOne
        status, data = S.SecItemCopyMatching(query, None)
        if status != 0 or data is None:
            raise RuntimeError(f"SecItemCopyMatching failed: {status}")
        return bytes(data)

    def delete(self) -> None:
        import Security as S

        S.SecItemDelete(self._query())


_backend = _MacBackend()


def store_key(key: bytes) -> bool:
    try:
        if not _backend.available():
            return False
        _backend.put(key)
        return True
    except Exception:
        return False


def load_key() -> bytes | None:
    try:
        if not _backend.available():
            return None
        return _backend.get()
    except Exception:
        return None


def forget_key() -> None:
    try:
        _backend.delete()
    except Exception:
        pass
