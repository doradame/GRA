import asyncio

import app.services.sparse_corpus_stats as stats_module
from app.services.sparse_corpus_stats import (
    apply_document_delta,
    get_global_stats_snapshot,
    get_term_ids_cached,
    reconcile_bm25_cache_if_needed,
    reset_global_stats,
)


class FakeRedis:
    """Doppio minimale di redis.Redis: copre solo i comandi usati da sparse_corpus_stats.py."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    def hmget(self, key, fields):
        h = self.hashes.get(key, {})
        return [h.get(f) for f in fields]

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, amount):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + amount)

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value):
        self.strings[key] = str(value)

    def incrby(self, key, amount):
        self.strings[key] = str(int(self.strings.get(key, 0)) + amount)

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.strings.pop(key, None)

    def exists(self, key):
        return 1 if (key in self.hashes or key in self.strings) else 0

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.ops = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return queue

    def execute(self):
        for name, args, kwargs in self.ops:
            getattr(self.redis, name)(*args, **kwargs)
        self.ops = []


def _patch_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(stats_module, "_redis_client", fake)
    monkeypatch.setattr(stats_module, "_get_redis", lambda: fake)
    return fake


def test_get_term_ids_cached_returns_only_known_terms(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.hashes[stats_module.REDIS_VOCAB_KEY] = {"risk": "1", "approval": "2"}

    result = get_term_ids_cached(["risk", "unknown"])

    assert result == {"risk": 1}


def test_get_global_stats_snapshot_returns_df_and_avg_doc_len(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.hashes[stats_module.REDIS_DF_KEY] = {"1": "5", "2": "50"}
    fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] = "100"
    fake.strings[stats_module.REDIS_TOTAL_TOKENS_KEY] = "800"

    df, total_chunks, avg_doc_len = get_global_stats_snapshot([1, 2, 3])

    assert df == {1: 5, 2: 50}
    assert total_chunks == 100
    assert avg_doc_len == 8.0


def test_get_global_stats_snapshot_defaults_when_empty(monkeypatch):
    _patch_redis(monkeypatch)

    df, total_chunks, avg_doc_len = get_global_stats_snapshot([])

    assert df == {}
    assert total_chunks == 0
    assert avg_doc_len == 1.0


def test_apply_document_delta_increments_df_and_totals(monkeypatch):
    fake = _patch_redis(monkeypatch)

    apply_document_delta({1: 3, 2: 1}, chunk_count_delta=5, token_count_delta=40)

    assert fake.hashes[stats_module.REDIS_DF_KEY] == {"1": "3", "2": "1"}
    assert fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] == "5"
    assert fake.strings[stats_module.REDIS_TOTAL_TOKENS_KEY] == "40"


def test_apply_document_delta_can_subtract_negative_contribution(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.hashes[stats_module.REDIS_DF_KEY] = {"1": "3"}
    fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] = "5"
    fake.strings[stats_module.REDIS_TOTAL_TOKENS_KEY] = "40"

    apply_document_delta({1: -3}, chunk_count_delta=-5, token_count_delta=-40)

    assert fake.hashes[stats_module.REDIS_DF_KEY] == {"1": "0"}
    assert fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] == "0"
    assert fake.strings[stats_module.REDIS_TOTAL_TOKENS_KEY] == "0"


def test_reset_global_stats_clears_all_keys(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.hashes[stats_module.REDIS_DF_KEY] = {"1": "3"}
    fake.hashes[stats_module.REDIS_VOCAB_KEY] = {"risk": "1"}
    fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] = "5"
    fake.strings[stats_module.REDIS_TOTAL_TOKENS_KEY] = "40"

    reset_global_stats()

    assert stats_module.REDIS_DF_KEY not in fake.hashes
    assert stats_module.REDIS_VOCAB_KEY not in fake.hashes
    assert stats_module.REDIS_TOTAL_CHUNKS_KEY not in fake.strings
    assert stats_module.REDIS_TOTAL_TOKENS_KEY not in fake.strings


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeDb:
    """AsyncSession minimale: serve solo a reconcile_bm25_cache_if_needed (count chunk)."""

    def __init__(self, chunk_count: int):
        self._chunk_count = chunk_count

    async def execute(self, stmt):
        return _FakeScalarResult(self._chunk_count)


def _patch_recompute(monkeypatch):
    calls = {"count": 0}

    async def fake_recompute(db):
        calls["count"] += 1

    monkeypatch.setattr(stats_module, "recompute_global_stats_from_postgres", fake_recompute)
    return calls


def test_reconcile_recomputes_when_cache_missing(monkeypatch):
    _patch_redis(monkeypatch)  # cache vuota -> exists ritorna 0
    calls = _patch_recompute(monkeypatch)

    result = asyncio.run(reconcile_bm25_cache_if_needed(_FakeDb(100), tolerance=5))

    assert result is True
    assert calls["count"] == 1


def test_reconcile_recomputes_when_drift_exceeds_tolerance(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] = "90"  # cache: 90, postgres: 100
    calls = _patch_recompute(monkeypatch)

    result = asyncio.run(reconcile_bm25_cache_if_needed(_FakeDb(100), tolerance=5))

    assert result is True
    assert calls["count"] == 1


def test_reconcile_skips_when_within_tolerance(monkeypatch):
    fake = _patch_redis(monkeypatch)
    fake.strings[stats_module.REDIS_TOTAL_CHUNKS_KEY] = "97"  # diff 3 <= tolerance 5
    calls = _patch_recompute(monkeypatch)

    result = asyncio.run(reconcile_bm25_cache_if_needed(_FakeDb(100), tolerance=5))

    assert result is False
    assert calls["count"] == 0
