import pytest

from ssh_locker import biometric


class FakeBackend:
    def __init__(self, available=True, get_raises=False):
        self._available = available
        self._get_raises = get_raises
        self.stored = None

    def available(self):
        return self._available

    def put(self, key):
        self.stored = key

    def get(self):
        if self._get_raises:
            raise RuntimeError("user cancelled")
        return self.stored

    def delete(self):
        self.stored = None


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(biometric, "_backend", backend)
    return backend


def test_store_then_load_returns_key(fake):
    assert biometric.store_key(b"k" * 32) is True
    assert biometric.load_key() == b"k" * 32


def test_load_returns_none_when_backend_get_raises(fake):
    fake.stored = b"k" * 32
    fake._get_raises = True
    assert biometric.load_key() is None


def test_store_returns_false_when_unavailable(fake):
    fake._available = False
    assert biometric.store_key(b"k" * 32) is False
    assert fake.stored is None


def test_load_returns_none_when_unavailable(fake):
    fake.stored = b"k" * 32
    fake._available = False
    assert biometric.load_key() is None


def test_forget_removes_key(fake):
    biometric.store_key(b"k" * 32)
    biometric.forget_key()
    assert biometric.load_key() is None
