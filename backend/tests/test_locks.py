import app.core.locks as locks_module
from app.core.locks import acquire_lock, is_locked, release_lock


class FakeLockRedis:
    """Doppio minimale di redis.Redis per i soli comandi usati da core/locks.py."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return self.store.pop(key, None) is not None

    def exists(self, key):
        return 1 if key in self.store else 0

    def eval(self, script, numkeys, key, token):
        # Replica la semantica del Lua CAS: del solo se il token corrisponde.
        if self.store.get(key) == token:
            self.store.pop(key, None)
            return 1
        return 0


def _patch_redis(monkeypatch):
    fake = FakeLockRedis()
    monkeypatch.setattr(locks_module, "_redis_client", fake)
    monkeypatch.setattr(locks_module, "_get_redis", lambda: fake)
    return fake


def test_acquire_lock_succeeds_when_free(monkeypatch):
    _patch_redis(monkeypatch)

    assert acquire_lock("lock:job:test", "tok1") is True
    assert is_locked("lock:job:test") is True


def test_acquire_lock_fails_when_already_held(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.store["lock:job:test"] = "other-token"

    assert acquire_lock("lock:job:test", "tok1") is False
    # Il detentore originale resta.
    assert is_locked("lock:job:test") is True


def test_release_lock_only_with_matching_token(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.store["lock:job:test"] = "tok1"

    # Token sbagliato: non rilascia (è il lock di un altro).
    release_lock("lock:job:test", "wrong")
    assert is_locked("lock:job:test") is True

    # Token corretto: rilascia.
    release_lock("lock:job:test", "tok1")
    assert is_locked("lock:job:test") is False


def test_release_does_not_delete_reacquired_lock(monkeypatch):
    # Scenario CAS: il nostro lock è scaduto (TTL), un altro detentore lo ha riacquisito.
    # Il nostro release col vecchio token NON deve cancellare il lock altrui.
    fake = _patch_redis(monkeypatch)
    fake.store["lock:job:test"] = "new-owner-token"

    release_lock("lock:job:test", "our-old-token")

    assert is_locked("lock:job:test") is True
    assert fake.store["lock:job:test"] == "new-owner-token"
