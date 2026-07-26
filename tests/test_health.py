"""健康检查 API 测试。"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

import personal_assistant.core.health as health_module
import personal_assistant.core.store_chroma as store_chroma_module
from personal_assistant.core.health import HealthService
from personal_assistant.core.store_chroma import ChromaStore
from personal_assistant.main_api import (
    LOOPBACK_ORIGIN_REGEX,
    TAURI_ORIGINS,
    request_observability,
)


@pytest.mark.asyncio
async def test_health_returns_four_components(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"api", "ollama", "mysql", "chroma"}
    for key in ("api", "ollama", "mysql", "chroma"):
        assert "ok" in data[key]


@pytest.mark.asyncio
async def test_request_id_is_preserved_when_safe(client):
    response = await client.get("/", headers={"x-request-id": "desktop_trace-42"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "desktop_trace-42"
    assert response.headers["server-timing"].startswith("ttfb;dur=")


@pytest.mark.asyncio
async def test_request_id_is_replaced_when_invalid(client):
    response = await client.get("/", headers={"x-request-id": "unsafe value"})
    assert response.status_code == 200
    generated = response.headers["x-request-id"]
    assert generated != "unsafe value"
    assert len(generated) == 32
    assert generated.isalnum()


@pytest.mark.asyncio
async def test_health_service_caches_probes_and_returns_an_isolated_copy(monkeypatch):
    service = HealthService(cache_ttl=30.0)
    ollama = AsyncMock(return_value={"ok": True, "models": []})
    mysql = AsyncMock(return_value={"ok": True})
    chroma = AsyncMock(return_value={"ok": True, "collections": 0})
    monkeypatch.setattr(service, "_check_ollama", ollama)
    monkeypatch.setattr(service, "_check_mysql", mysql)
    monkeypatch.setattr(service, "_check_chroma", chroma)

    first = await service.check_all()
    first["mysql"]["ok"] = False
    second = await service.check_all()

    assert second["mysql"]["ok"] is True
    assert ollama.await_count == mysql.await_count == chroma.await_count == 1


@pytest.mark.asyncio
async def test_health_cache_is_instance_scoped(monkeypatch):
    cached = HealthService(cache_ttl=30.0)
    uncached = HealthService(cache_ttl=0.0)

    for service, mysql_ok in ((cached, True), (uncached, False)):
        monkeypatch.setattr(
            service,
            "_check_ollama",
            AsyncMock(return_value={"ok": True, "models": []}),
        )
        monkeypatch.setattr(
            service,
            "_check_mysql",
            AsyncMock(return_value={"ok": mysql_ok}),
        )
        monkeypatch.setattr(
            service,
            "_check_chroma",
            AsyncMock(return_value={"ok": True, "collections": 0}),
        )

    assert (await cached.check_all())["mysql"]["ok"] is True
    assert (await uncached.check_all())["mysql"]["ok"] is False
    assert (await uncached.check_all())["mysql"]["ok"] is False
    assert uncached._check_mysql.await_count == 2


@pytest.mark.asyncio
async def test_health_service_single_flight_for_ten_concurrent_callers(monkeypatch):
    service = HealthService(cache_ttl=0.0)
    release = asyncio.Event()
    started = asyncio.Event()

    async def probe(result):
        started.set()
        await release.wait()
        return result

    async def probe_ollama():
        return await probe({"ok": True, "models": []})

    async def probe_mysql():
        return await probe({"ok": True})

    async def probe_chroma():
        return await probe({"ok": True, "collections": 0})

    ollama = AsyncMock(side_effect=probe_ollama)
    mysql = AsyncMock(side_effect=probe_mysql)
    chroma = AsyncMock(side_effect=probe_chroma)
    monkeypatch.setattr(service, "_check_ollama", ollama)
    monkeypatch.setattr(service, "_check_mysql", mysql)
    monkeypatch.setattr(service, "_check_chroma", chroma)

    callers = [asyncio.create_task(service.check_all(force=True)) for _ in range(10)]
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*callers)

    assert len(results) == 10
    assert ollama.await_count == mysql.await_count == chroma.await_count == 1
    results[0]["mysql"]["ok"] = False
    assert all(result["mysql"]["ok"] is True for result in results[1:])


@pytest.mark.asyncio
async def test_chroma_probe_gate_is_shared_across_service_instances(monkeypatch):
    first = HealthService(cache_ttl=0.0)
    second = HealthService(cache_ttl=0.0)
    entered = 0
    started = threading.Event()
    release = threading.Event()

    def blocked_chroma_probe(path) -> int:
        nonlocal entered
        entered += 1
        started.set()
        if not release.wait(timeout=2.0):
            raise TimeoutError("test failed to release Chroma probe")
        return 0

    monkeypatch.setattr(
        health_module,
        "_load_chroma_collections",
        blocked_chroma_probe,
    )

    first_probe = asyncio.create_task(first._check_chroma())
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()

    second_result = await asyncio.wait_for(second._check_chroma(), timeout=1.0)
    assert second_result["ok"] is False
    assert "still running" in second_result["error"]
    assert entered == 1

    release.set()
    first_result = await first_probe
    assert first_result == {
        "ok": True,
        "path": str(health_module.settings.chroma_dir),
        "collections": 0,
    }


@pytest.mark.asyncio
async def test_chroma_store_close_is_idempotent():
    store = ChromaStore()
    client = Mock()
    store._client = client
    store._collection = object()

    await store.close()
    await store.close()

    client.close.assert_called_once_with()
    assert store._client is None
    assert store._collection is None


@pytest.mark.asyncio
async def test_chroma_store_serializes_first_use_and_shutdown(monkeypatch, tmp_path):
    clients = []
    operation_started = threading.Event()
    release_operation = threading.Event()

    class FakeCollection:
        should_block = False

        def count(self):
            if self.should_block:
                operation_started.set()
                assert release_operation.wait(timeout=1.0)
            return 1

    class FakeClient:
        def __init__(self):
            self.collection = FakeCollection()
            self.close_calls = 0

        def get_or_create_collection(self, _name):
            return self.collection

        def close(self):
            self.close_calls += 1

    def create_client(*, path):
        assert path == str(tmp_path / "chroma")
        # Widen the initialization race: without lifecycle locking, both calls
        # observe an empty collection and construct separate clients.
        time.sleep(0.03)
        client = FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(store_chroma_module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(store_chroma_module.chromadb, "PersistentClient", create_client)
    store = ChromaStore()

    assert await asyncio.gather(store.count(), store.count()) == [1, 1]
    assert len(clients) == 1

    clients[0].collection.should_block = True
    count_task = asyncio.create_task(store.count())
    assert await asyncio.to_thread(operation_started.wait, 1.0)
    close_task = asyncio.create_task(store.close())
    await asyncio.sleep(0.02)
    assert clients[0].close_calls == 0

    release_operation.set()
    assert await count_task == 1
    await close_task
    assert clients[0].close_calls == 1


@pytest.mark.asyncio
async def test_health_service_bounds_each_probe(monkeypatch):
    service = HealthService(cache_ttl=0.0, probe_timeout=0.01)

    async def slow_probe():
        await asyncio.sleep(0.2)
        return {"ok": True}

    monkeypatch.setattr(service, "_check_ollama", slow_probe)
    monkeypatch.setattr(service, "_check_mysql", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(service, "_check_chroma", AsyncMock(return_value={"ok": True}))

    result = await service.check_all(force=True)

    assert result["ollama"] == {"ok": False, "error": "Ollama 健康检查超时"}
    assert result["mysql"]["ok"] is True
    assert result["chroma"]["ok"] is True


@pytest.mark.asyncio
async def test_health_service_degrades_when_a_probe_raises(monkeypatch):
    service = HealthService(cache_ttl=0.0)
    monkeypatch.setattr(
        service,
        "_check_ollama",
        AsyncMock(side_effect=RuntimeError("provider secret detail")),
    )
    monkeypatch.setattr(service, "_check_mysql", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(service, "_check_chroma", AsyncMock(return_value={"ok": True}))

    result = await service.check_all(force=True)

    assert result["ollama"] == {"ok": False, "error": "Ollama 健康检查失败"}
    assert "secret" not in result["ollama"]["error"]


@pytest.mark.asyncio
async def test_unhandled_500_keeps_request_id_cors_and_timing_headers():
    test_app = FastAPI()
    test_app.middleware("http")(request_observability)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=TAURI_ORIGINS,
        allow_origin_regex=LOOPBACK_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Server-Timing"],
    )

    @test_app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("must not leak")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get(
            "/explode",
            headers={"Origin": "https://tauri.localhost", "X-Request-ID": "boom-42"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "must not leak" not in response.text
    assert response.headers["x-request-id"] == "boom-42"
    assert response.headers["server-timing"].startswith("ttfb;dur=")
    assert response.headers["access-control-allow-origin"] == "https://tauri.localhost"
