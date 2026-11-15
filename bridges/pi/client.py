"""One physical press, one complete WAV, then a durable acknowledgment."""

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import signal
import threading
import wave
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID

import httpx

try:
    from .led import update_led
except ImportError:
    from led import update_led

SERVER_URL = "https://sap.elischiffler.dev"
POLL_SECONDS = 3
MAX_AUDIO_BYTES = 5_000_000
MAX_AUDIO_SECONDS = 45
LOG = logging.getLogger("pager")


class Pager:
    def __init__(self, http, led, state_dir, play):
        self.http = http
        self.led = led
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.pending_file = self.state_dir / "ack-pending.json"
        self.audio_file = self.state_dir / "message.wav"
        self.play = play
        self.busy = threading.Lock()
        self.pending = None
        self.download_confirmed = False
        # A corrupt journal is a startup failure, never permission to replay.
        if self.pending_file.exists():
            self.pending = str(UUID(json.loads(self.pending_file.read_text())["id"]))
            LOG.warning("Pending ACK loaded for %s; waiting for button", self.pending)
        self.audio_file.unlink(missing_ok=True)

    def sync_directory(self):
        fd = os.open(self.state_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def persist_pending(self):
        temporary = self.pending_file.with_suffix(".tmp")
        with temporary.open("w") as file:
            json.dump({"id": self.pending}, file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.pending_file)
        self.sync_directory()

    def clear_pending(self):
        self.pending_file.unlink(missing_ok=True)
        self.sync_directory()
        self.pending = None

    async def status(self):
        try:
            async with asyncio.timeout(8):
                response = await self.http.get("/status")
                response.raise_for_status()
                status = response.json()
                if not isinstance(status, dict) or not isinstance(status.get("items"), list):
                    raise ValueError("Malformed status")
                update_led(self.led, status)
                return status
        except (httpx.HTTPError, TimeoutError, ValueError):
            update_led(self.led, None)
            LOG.exception("Status poll failed")
            return None

    async def poll(self):
        while True:
            await self.status()
            await asyncio.sleep(POLL_SECONDS)

    async def acknowledge(self):
        # Re-persist before retry in case the first disk write failed after playback.
        self.persist_pending()
        async with asyncio.timeout(8):
            response = await self.http.post("/ack", json={"ids": [self.pending]})
        if response.status_code in (400, 403, 404, 409, 410, 422):
            LOG.error("ACK rejected/expired for %s (HTTP %s); refreshing status",
                      self.pending, response.status_code)
            self.clear_pending()
            await self.status()
            return False
        response.raise_for_status()
        result = response.json()
        if (response.status_code != 200 or not isinstance(result, dict)
                or result.get("status") != "acknowledged"
                or result.get("ids") != [self.pending]):
            raise ValueError("Unconfirmed ACK response; retaining pending ID")
        LOG.info("Acknowledged %s", self.pending)
        self.clear_pending()
        return True

    async def download(self, message_id):
        self.download_confirmed = False
        async with asyncio.timeout(20):
            async with self.http.stream("GET", "/audio/" + message_id) as response:
                if response.status_code == 409:
                    LOG.warning("Audio unavailable/conflicting for %s; try a later press", message_id)
                    await self.status()
                    return False
                if response.status_code != 200:
                    raise ValueError(f"Audio requires HTTP 200, received {response.status_code}")
                transfer_id = response.headers.get("x-pi-transfer-id")
                length = response.headers.get("content-length")
                if length is not None and not 0 < int(length) <= MAX_AUDIO_BYTES:
                    raise ValueError("Invalid or excessive audio length")
                size = 0
                with self.audio_file.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_AUDIO_BYTES:
                            raise ValueError("Audio exceeds 5 MB")
                        file.write(chunk)
                    file.flush()
                    os.fsync(file.fileno())
                if length is not None and size != int(length):
                    raise ValueError("Incomplete audio download")
        # Validate both declared duration and actual PCM data before invoking aplay.
        with wave.open(str(self.audio_file), "rb") as wav:
            frames = wav.getnframes()
            if frames <= 0 or frames / wav.getframerate() > MAX_AUDIO_SECONDS:
                raise ValueError("Invalid or excessive WAV duration")
            expected = frames * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(frames)) != expected:
                raise ValueError("Truncated WAV data")
        self.sync_directory()
        if transfer_id:
            try:
                with self.audio_file.open("rb") as file:
                    digest = hashlib.file_digest(file, "sha256").hexdigest()
                async with asyncio.timeout(5):
                    receipt = await self.http.post("/api/pi/downloaded", json={
                        "id": message_id, "transfer_id": transfer_id,
                        "size": size, "sha256": digest,
                    })
                if receipt.status_code == 409:
                    LOG.warning("Download receipt rejected/expired for %s; waiting for next press",
                                message_id)
                    await self.status()
                    return False
                receipt.raise_for_status()
                if receipt.status_code != 200 or receipt.json() != {
                    "status": "download_confirmed", "id": message_id,
                }:
                    raise ValueError("Unconfirmed download receipt")
                self.download_confirmed = True
                LOG.info("Server confirmed saved WAV for %s", message_id)
            except (httpx.HTTPError, TimeoutError, ValueError):
                # Telemetry failure does not turn a successful download into a playback ACK.
                LOG.exception("WAV saved, but download receipt was not confirmed for %s", message_id)
        else:
            LOG.warning("Server has no download-receipt support; WAV saved for %s", message_id)
        return True

    async def handle_press(self):
        try:
            if self.pending is not None:
                # An ACK-only press never also claims another item.
                await self.acknowledge()
                await self.status()
                return
            status = await self.status()
            if status is None or not status["items"]:
                return
            message_id = str(UUID(status["items"][0]["id"]))
            if not await self.download(message_id):
                return
            await self.play(self.audio_file)
            self.pending = message_id
            self.persist_pending()
            await self.acknowledge()
            await self.status()
        except Exception:
            # Download/playback failures never reach ACK; pending ACKs survive errors.
            LOG.exception("Button operation failed; pending ACK=%s", self.pending)
        finally:
            try:
                self.audio_file.unlink(missing_ok=True)
            finally:
                self.busy.release()

    def press(self, loop):
        # Acquire in the GPIO callback so presses during playback cannot queue up.
        if self.busy.acquire(blocking=False):
            try:
                return asyncio.run_coroutine_threadsafe(self.handle_press(), loop)
            except Exception:
                self.busy.release()
                raise
        return None


async def play_audio(path):
    # Uses existing ALSA default; PAGER_ALSA_DEVICE can select an installed output.
    args = ["aplay", "--quiet"]
    if os.environ.get("PAGER_ALSA_DEVICE"):
        args.extend(["--device", os.environ["PAGER_ALSA_DEVICE"]])
    process = await asyncio.create_subprocess_exec(*args, str(path))
    try:
        async with asyncio.timeout(50):
            code = await process.wait()
        if code != 0:
            raise RuntimeError(f"aplay failed with exit status {code}")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def run(state_dir):
    from gpiozero import LED, Button

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    with (
        LED(int(os.environ.get("PAGER_LED_GPIO", "27"))) as led,
        Button(int(os.environ.get("PAGER_BUTTON_GPIO", "17")),
               pull_up=True, bounce_time=0.05) as button,
    ):
        async with httpx.AsyncClient(
            base_url=SERVER_URL, verify=True, follow_redirects=False,
            timeout=httpx.Timeout(5, connect=5), trust_env=False,
            headers={"Accept-Encoding": "identity"},
        ) as http:
            pager = Pager(http, led, state_dir, play_audio)
            button.when_pressed = lambda: pager.press(loop)
            poll = asyncio.create_task(pager.poll())
            LOG.info("Pager started: %s, poll=%ss, button=GPIO%s, LED=GPIO%s",
                     SERVER_URL, POLL_SECONDS, button.pin.number, led.pin.number)
            await stopped.wait()
            button.when_pressed = None
            # Allow an in-flight play/ACK to finish before normal service shutdown.
            while pager.busy.locked():
                await asyncio.sleep(0.1)
            poll.cancel()
            await asyncio.gather(poll, return_exceptions=True)
            led.off()


def main():
    state_dir = Path(os.environ.get("PAGER_STATE_DIR", "/var/lib/sap-pager"))
    state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[
        RotatingFileHandler(state_dir / "pager.log", maxBytes=1_000_000, backupCount=3),
    ], format="%(asctime)s %(levelname)s %(message)s")
    # Prevent multiple processes from downloading, playing, or sharing the journal.
    with (state_dir / "client.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(run(state_dir))


if __name__ == "__main__":
    main()
