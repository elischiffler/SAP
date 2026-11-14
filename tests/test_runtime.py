import asyncio
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from contracts import Settings
from server.app import create_app
from server.store import QueueStore


@pytest.mark.parametrize(
    "host",
    ["https://pager.example.com", "example.com/path", "*.example.com", "", "example.com:8000"],
)
def test_production_rejects_non_hostname_configuration(host):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, public_host=host)


@pytest.mark.parametrize(
    "override",
    [
        {"public_host": None},
        {"openai_api_key": None},
        {"tts_provider": "macos"},
        {"classifier_provider": "demo"},
    ],
)
def test_production_requires_hosted_providers_key_and_host(override):
    values = dict(
        environment="production", public_host="pager.example.com", openai_api_key="test-key"
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(values | override))


async def test_public_host_https_and_origin_are_required(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        environment="production",
        public_host="pager.example.com",
        openai_api_key="test-key",
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client,
    ):
        assert (await client.get("https://pager.example.com/healthz")).status_code == 200
        assert (await client.get("http://pager.example.com/healthz")).status_code == 403
        assert (await client.get("https://wrong.example.com/healthz")).status_code == 403
        response = await client.post(
            "https://pager.example.com/api/delivery/claim",
            json={"device_id": "pager"},
            headers={"Origin": "https://wrong.example.com"},
        )
        assert response.status_code == 403
        response = await client.post(
            "https://pager.example.com/api/delivery/claim",
            json={"device_id": "pager"},
            headers={"Origin": "https://pager.example.com"},
        )
        assert response.status_code == 200


async def test_worker_fault_changes_health_and_recovers(tmp_path, monkeypatch):
    app = create_app(
        Settings(
            _env_file=None, data_dir=tmp_path, classifier_provider="demo", tts_provider="macos"
        )
    )
    reserve = QueueStore.reserve_job
    broken = True

    def transient_failure(store):
        if broken:
            raise sqlite3.OperationalError("synthetic private database detail")
        return reserve(store)

    monkeypatch.setattr(QueueStore, "reserve_job", transient_failure)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        async with asyncio.timeout(3):
            while (await client.get("/healthz")).status_code != 503:
                await asyncio.sleep(0.01)
        broken = False
        async with asyncio.timeout(3):
            while (await client.get("/healthz")).status_code != 200:
                await asyncio.sleep(0.01)


async def test_database_lock_returns_503_without_blocking_health(tmp_path):
    app = create_app(
        Settings(
            _env_file=None, data_dir=tmp_path, classifier_provider="demo", tts_provider="macos"
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        with sqlite3.connect(tmp_path / "pager.sqlite3") as lock:
            lock.execute("BEGIN IMMEDIATE")
            blocked = asyncio.create_task(client.get("/api/state"))
            # A synchronous lock wait in the event loop would prevent this coroutine running.
            await asyncio.sleep(0.02)
            health = await asyncio.wait_for(client.get("/healthz"), timeout=0.15)
            assert health.status_code in {200, 503}
            response = await asyncio.wait_for(blocked, timeout=1)
            assert response.status_code == 503
            assert str(tmp_path) not in response.text
        assert (await client.get("/api/state")).status_code == 200
