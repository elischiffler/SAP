"""Manually download one real offered WAV; never play or acknowledge it."""

import asyncio
import fcntl
import os
import sys
import wave
from pathlib import Path
from uuid import UUID

import httpx

try:
    from .client import SERVER_URL, Pager
except ImportError:
    sys.path.insert(0, "/opt/sap-pager")
    from client import SERVER_URL, Pager


class NoHardwareLED:
    def on(self):
        pass

    def off(self):
        pass


async def never_play(path):
    raise RuntimeError("Download-only test must never play audio")


async def download_only(http, state_dir):
    state_dir = Path(state_dir)
    if (state_dir / "ack-pending.json").exists():
        raise RuntimeError("Pending playback ACK exists; resolve it with the button first")
    pager = Pager(http, NoHardwareLED(), state_dir / "download-test", never_play)
    try:
        status = await pager.status()
        if status is None:
            raise RuntimeError("Status request failed")
        if not status["items"]:
            print("No notification is currently offered. Nothing downloaded.")
            return None
        message_id = str(UUID(status["items"][0]["id"]))
        if not await pager.download(message_id):
            print("Audio is not ready (HTTP 409). Try again later.")
            return None
        with wave.open(str(pager.audio_file), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
            audio_format = (f"PCM WAV, {wav.getframerate()} Hz, "
                            f"{wav.getsampwidth() * 8}-bit, {wav.getnchannels()} channel(s)")
        print(f"Downloaded ID: {message_id}")
        print(f"Saved: {pager.audio_file}")
        print(f"Validated WAV: {pager.audio_file.stat().st_size} bytes, {seconds:.2f} seconds")
        print(f"Format: {audio_format}")
        print("Dashboard download receipt: " + ("confirmed" if pager.download_confirmed
                                                else "not confirmed"))
        print("Not played. Not acknowledged. Server reservation expires after 90 seconds.")
        return pager.audio_file
    except BaseException:
        pager.audio_file.unlink(missing_ok=True)
        raise


async def run(state_dir):
    async with httpx.AsyncClient(
        base_url=SERVER_URL, verify=True, follow_redirects=False, trust_env=False,
        timeout=httpx.Timeout(5, connect=5), headers={"Accept-Encoding": "identity"},
    ) as http:
        await download_only(http, state_dir)


if __name__ == "__main__":
    state_dir = Path(os.environ.get("PAGER_STATE_DIR", "/var/lib/sap-pager"))
    with (state_dir / "client.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Stop sap-pager.service before running this test.")
        asyncio.run(run(state_dir))
