"""Exercise ingress backpressure with no API calls and an isolated temporary database.

Run from the repository root: .venv/bin/python -m scripts.check_load
"""

import asyncio
import json
import socket
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
import uvicorn

from contracts import Settings
from server.app import create_app


class WaitingClassifier:
    async def classify(self, notification):
        await asyncio.Event().wait()


class UnusedSpeech:
    async def synthesize(self, text, destination):
        raise AssertionError("Load probe must not generate speech")


async def main():
    with tempfile.TemporaryDirectory(prefix="sap-load-") as folder:
        settings = Settings(
            _env_file=None,
            data_dir=Path(folder),
            classifier_provider="demo",
            tts_provider="macos",
            max_pending_notifications=8,
            grouping_window_seconds=0,
            provider_timeout_seconds=120,
        )
        app = create_app(
            settings,
            allow_test_ingestion=True,
            classifier=WaitingClassifier(),
            speech=UnusedSpeech(),
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_level="critical",
                access_log=False,
                limit_concurrency=32,
                backlog=64,
                timeout_keep_alive=1,
            )
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.setblocking(False)
            port = listener.getsockname()[1]
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        await asyncio.sleep(0.01)
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    timeout=10,
                    limits=httpx.Limits(max_connections=64, max_keepalive_connections=0),
                ) as client:
                    start = time.monotonic()
                    responses = await asyncio.gather(
                        *[
                            client.post(
                                "/api/notifications",
                                json={"app": "Load probe", "body": "Synthetic notification"},
                            )
                            for _ in range(64)
                        ]
                    )
                    statuses = Counter(response.status_code for response in responses)
                    assert set(statuses) <= {202, 429, 503}, statuses
                    # Fill any remaining slots if the connection cap rejected the whole first wave.
                    for _ in range(8):
                        response = await client.post(
                            "/api/notifications",
                            json={"app": "Load probe", "body": "Synthetic notification"},
                        )
                        if response.status_code == 429:
                            break
                        assert response.status_code == 202
                    state = (await client.get("/api/state")).json()
                    assert state["counts"]["pending"] == 8
                    assert (
                        await client.post("/api/notifications", json={"app": "Load probe"})
                    ).status_code == 429
                    assert (await client.get("/healthz")).status_code == 200
                    print(
                        json.dumps(
                            {
                                "concurrent_requests": 64,
                                "statuses": dict(statuses),
                                "retained_notifications": 8,
                                "queue_limit": 8,
                                "health": "ok",
                                "seconds": round(time.monotonic() - start, 3),
                                "paid_api_calls": 0,
                            }
                        )
                    )
            finally:
                server.should_exit = True
                await task


if __name__ == "__main__":
    asyncio.run(main())
