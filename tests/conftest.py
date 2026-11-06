import pytest

import ssh_locker.vault as vault_mod


@pytest.fixture(autouse=True)
def fast_kdf(request, monkeypatch):
    """Use a cheap scrypt cost so the suite stays fast.

    The cost is recorded in each vault header, so files stay self-consistent.
    Tests marked `real_kdf` run with the production cost.
    """
    if "real_kdf" not in request.keywords:
        monkeypatch.setattr(vault_mod, "KDF_LOG2_N", 14)
