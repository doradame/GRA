import asyncio

import pytest

import app.core.retry as retry_module
from app.core.retry import retry_async, retry_sync


class _TransientError(Exception):
    pass


async def _noop_sleep(*a, **kw):
    # Sostituisce asyncio.sleep senza ricadere su asyncio.sleep (sarebbe ricorsione,
    # perche asyncio e un singleton: la lambda non deve richiamarlo).
    return None


def test_retry_async_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr(retry_module.asyncio, "sleep", _noop_sleep)
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _TransientError("boom")
        return "ok"

    result = asyncio.run(
        retry_async(factory, retries=5, base_delay=0.01, retry_on=(_TransientError,))
    )

    assert result == "ok"
    assert calls["n"] == 3


def test_retry_async_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(retry_module.asyncio, "sleep", _noop_sleep)
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise _TransientError("boom")

    with pytest.raises(_TransientError):
        asyncio.run(retry_async(factory, retries=2, base_delay=0.01, retry_on=(_TransientError,)))
    # 1 tentativo + 2 retry.
    assert calls["n"] == 3


def test_retry_async_does_not_retry_non_listed_exception():
    async def factory():
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        asyncio.run(retry_async(factory, retries=5, retry_on=(_TransientError,)))


def test_retry_async_should_retry_false_propagates_immediately():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise _TransientError("boom")

    with pytest.raises(_TransientError):
        asyncio.run(
            retry_async(
                factory,
                retries=5,
                base_delay=0.01,
                retry_on=(_TransientError,),
                should_retry=lambda _exc: False,
            )
        )
    assert calls["n"] == 1


def test_retry_sync_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(retry_module.time, "sleep", lambda *a, **kw: None)
    calls = {"n": 0}

    def func():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _TransientError("boom")
        return 42

    result = retry_sync(func, retries=3, base_delay=0.01, retry_on=(_TransientError,))

    assert result == 42
    assert calls["n"] == 2
