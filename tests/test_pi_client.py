import asyncio
import hashlib
import io
import json
import wave
from uuid import uuid4

import httpx
import pytest

from bridges.pi.client import MAX_AUDIO_BYTES, Pager


class LED:
    lit = False

    def on(self):
        self.lit = True

    def off(self):
        self.lit = False


def wav_bytes(seconds=0.01):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * int(8000 * seconds))
    return output.getvalue()


class Server:
    def __init__(self):
        self.id = str(uuid4())
        self.calls = []
        self.audio = wav_bytes()
        self.audio_code = 200
        self.ack_code = 200
        self.lose_ack = False
        self.poll_failure = False

    def handle(self, request):
        self.calls.append(request)
        assert "range" not in request.headers
        assert "authorization" not in request.headers
        if request.url.path == "/status":
            if self.poll_failure:
                raise httpx.ConnectError("offline")
            return httpx.Response(200, json={
                "items": [{"id": self.id, "priority": 3}], "led_on": True,
            })
        if request.url.path == "/audio/" + self.id:
            return httpx.Response(self.audio_code, content=self.audio)
        assert request.url.path == "/ack"
        assert request.headers["content-type"] == "application/json"
        assert request.content == ('{"ids":["' + self.id + '"]}').encode()
        if self.lose_ack:
            raise httpx.ReadTimeout("lost ACK response")
        return httpx.Response(self.ack_code, json={"status": "acknowledged", "ids": [self.id]})


async def press(pager):
    future = pager.press(asyncio.get_running_loop())
    assert future is not None
    await asyncio.wrap_future(future)


async def test_button_plays_one_then_ack_and_keeps_server_led(tmp_path):
    server = Server()
    played = []

    async def play(path):
        assert path.read_bytes() == server.audio
        assert not any(r.url.path == "/ack" for r in server.calls)
        assert pager.led.lit
        played.append(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        pager = Pager(http, LED(), tmp_path, play)
        await pager.status()
        assert played == []
        await press(pager)
        assert len(played) == 1
        assert [r.url.path for r in server.calls] == [
            "/status", "/status", "/audio/" + server.id, "/ack", "/status",
        ]
        assert not pager.audio_file.exists()
        assert not pager.pending_file.exists()
        assert pager.led.lit
        server.poll_failure = True
        assert await pager.status() is None
        assert not pager.led.lit


@pytest.mark.parametrize("failure", ["http", "conflict", "oversize", "truncated", "duration", "play"])
async def test_failed_audio_never_acknowledges(tmp_path, failure):
    server = Server()
    played = []
    if failure == "http":
        server.audio_code = 500
    if failure == "conflict":
        server.audio_code = 409
    if failure == "oversize":
        server.audio = b"x" * (MAX_AUDIO_BYTES + 1)
    if failure == "truncated":
        server.audio = server.audio[:-2]
    if failure == "duration":
        server.audio = wav_bytes(46)

    async def play(path):
        played.append(path)
        raise RuntimeError("speaker failure")

    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        pager = Pager(http, LED(), tmp_path, play)
        await press(pager)
        assert not any(r.url.path == "/ack" for r in server.calls)
        assert len(played) == (1 if failure == "play" else 0)
        assert not pager.audio_file.exists()
        assert not pager.busy.locked()
        if failure == "conflict":
            assert server.calls[-1].url.path == "/status"


async def test_busy_presses_ignored_and_lost_ack_survives_restart(tmp_path):
    server = Server()
    server.lose_ack = True
    played = []

    async def play(path):
        assert pager.press(asyncio.get_running_loop()) is None
        played.append(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        pager = Pager(http, LED(), tmp_path, play)
        await press(pager)
        assert pager.pending == server.id
        assert pager.pending_file.exists()
        server.lose_ack = False
        pager = Pager(http, LED(), tmp_path, play)
        count = len(server.calls)
        await pager.status()  # Startup polling cannot automatically acknowledge.
        assert len(server.calls) == count + 1
        await press(pager)
        assert len(played) == 1
        assert not pager.pending_file.exists()
        assert sum(r.url.path.startswith("/audio/") for r in server.calls) == 1


async def test_rejected_ack_refreshes_without_playing_next_item(tmp_path, caplog):
    server = Server()
    server.ack_code = 409

    async def play(path):
        raise AssertionError("Pending ACK must not play audio")

    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        pager = Pager(http, LED(), tmp_path, play)
        pager.pending = server.id
        pager.persist_pending()
        await press(pager)
        assert "ACK rejected/expired" in caplog.text
        assert pager.pending is None
        assert not any(r.url.path.startswith("/audio/") for r in server.calls)
        assert server.calls[-1].url.path == "/status"


async def test_manual_download_only_saves_wav_without_ack(tmp_path):
    from bridges.pi.download_only import download_only

    server = Server()
    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        path = await download_only(http, tmp_path)
        assert path.read_bytes() == server.audio
        assert [r.url.path for r in server.calls] == ["/status", "/audio/" + server.id]
        (tmp_path / "ack-pending.json").write_text('{"id":"' + server.id + '"}')
        with pytest.raises(RuntimeError, match="Pending playback ACK"):
            await download_only(http, tmp_path)
        assert len(server.calls) == 2


async def test_manual_download_removes_partial_file(tmp_path):
    from bridges.pi.download_only import download_only

    server = Server()
    server.audio = server.audio[:-2]
    async with httpx.AsyncClient(transport=httpx.MockTransport(server.handle),
                                 base_url="https://mock") as http:
        with pytest.raises(ValueError, match="Truncated"):
            await download_only(http, tmp_path)
        assert not (tmp_path / "download-test" / "message.wav").exists()
        assert not any(r.url.path == "/ack" for r in server.calls)


@pytest.mark.parametrize("receipt_code", [200, 503, 409])
async def test_download_receipt_only_after_complete_validated_file(tmp_path, receipt_code):
    from bridges.pi.download_only import download_only

    server = Server()
    transfer_id = str(uuid4())
    receipts = []

    def handler(request):
        if request.url.path == "/api/pi/downloaded":
            path = tmp_path / "download-test" / "message.wav"
            assert path.read_bytes() == server.audio
            body = json.loads(request.content)
            assert body == {"id": server.id, "transfer_id": transfer_id,
                            "size": len(server.audio),
                            "sha256": hashlib.sha256(server.audio).hexdigest()}
            receipts.append(body)
            return httpx.Response(receipt_code, json={"status": "download_confirmed", "id": server.id})
        response = server.handle(request)
        if request.url.path.startswith("/audio/"):
            response.headers["x-pi-transfer-id"] = transfer_id
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                 base_url="https://mock") as http:
        path = await download_only(http, tmp_path)
        assert len(receipts) == 1
        assert (path is not None) == (receipt_code != 409)
        assert not any(r.url.path == "/ack" for r in server.calls)
        server.audio = b"not a WAV"
        with pytest.raises(wave.Error):
            await download_only(http, tmp_path)
        assert len(receipts) == 1
