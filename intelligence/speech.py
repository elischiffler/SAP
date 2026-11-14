"""Generate bounded PCM WAV files without playing audio."""

import asyncio
import os
import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from openai import APITimeoutError, OpenAIError

from contracts import Settings

from .common import ProviderError, clean_spoken_text, openai_client

_UNKNOWN_WAV_SIZE = 0xFFFFFFFF


def _invalid_wav() -> ProviderError:
    return ProviderError(
        "speech_invalid", "Speech audio is invalid or exceeds the configured limits."
    )


def validate_wav(path: Path, *, max_bytes: int, max_seconds: float) -> None:
    """Require a complete, finite PCM WAV playable by the browser."""
    try:
        with path.open("rb") as raw:
            header = raw.read(12)
            size = os.fstat(raw.fileno()).st_size
            if not 44 <= size <= max_bytes or len(header) != 12:
                raise _invalid_wav()
            riff, riff_size, format_name = struct.unpack("<4sI4s", header)
            if riff != b"RIFF" or format_name != b"WAVE" or riff_size != size - 8:
                raise _invalid_wav()
            raw.seek(0)
            with wave.open(raw) as audio:
                frames = audio.getnframes()
                frame_size = audio.getnchannels() * audio.getsampwidth()
                rate = audio.getframerate()
                if not rate or not 0 < frames <= rate * max_seconds:
                    raise _invalid_wav()
                if (
                    frame_size * frames > size
                    or len(audio.readframes(frames)) != frame_size * frames
                    or audio.readframes(1)
                ):
                    raise _invalid_wav()
    except (EOFError, OSError, ValueError, struct.error, wave.Error):
        raise _invalid_wav() from None


def _finish_streamed_wav(path: Path, size: int) -> None:
    """Replace unknown RIFF and PCM lengths once the full HTTP stream arrives."""
    with path.open("r+b") as audio:
        header = audio.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            return
        if struct.unpack_from("<I", header, 4)[0] != _UNKNOWN_WAV_SIZE:
            return
        while audio.tell() + 8 <= size:
            offset = audio.tell()
            kind, length = struct.unpack("<4sI", audio.read(8))
            if kind == b"data" and length == _UNKNOWN_WAV_SIZE:
                audio.seek(offset + 4)
                audio.write(struct.pack("<I", size - offset - 8))
                audio.seek(4)
                audio.write(struct.pack("<I", size - 8))
                return
            audio.seek(length + (length % 2), 1)


class _WavSpeech:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def synthesize(self, text: str, destination: Path) -> Path:
        text = clean_spoken_text(text)
        if not 1 <= len(text) <= 350:
            raise ProviderError("speech_invalid", "Speech input must be a short nonempty summary.")
        try:
            async with asyncio.timeout(self._settings.provider_timeout_seconds):
                with TemporaryDirectory(prefix=".speech-", dir=destination.parent) as work_dir:
                    audio = Path(work_dir) / "audio.wav"
                    await self._generate(text, audio)
                    validate_wav(
                        audio,
                        max_bytes=self._settings.max_audio_bytes,
                        max_seconds=self._settings.max_audio_seconds,
                    )
                    audio.replace(destination)
        except (TimeoutError, APITimeoutError, httpx.TimeoutException):
            raise ProviderError("speech_timeout", "Speech synthesis timed out.") from None
        except (OSError, OpenAIError, httpx.HTTPError):
            raise ProviderError("speech_unavailable", "Speech synthesis failed.") from None
        return destination

    async def _generate(self, text: str, path: Path) -> None:
        raise NotImplementedError


class OpenAISpeech(_WavSpeech):
    async def _generate(self, text: str, path: Path) -> None:
        model = self._settings.tts_model
        options = (
            {"instructions": "Read the supplied text verbatim in a clear, calm speaking voice."}
            if not model.startswith("tts-1")
            else {}
        )
        async with openai_client(self._settings) as client:
            async with client.audio.speech.with_streaming_response.create(
                input=text,
                model=model,
                voice=self._settings.tts_voice,
                response_format="wav",
                **options,
            ) as response:
                size = 0
                with path.open("wb") as audio:
                    async for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > self._settings.max_audio_bytes:
                            raise _invalid_wav()
                        audio.write(chunk)
                _finish_streamed_wav(path, size)


class MacOSSpeech(_WavSpeech):
    async def _generate(self, text: str, path: Path) -> None:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/say",
            "-o",
            str(path),
            "--file-format=WAVE",
            "--data-format=LEI16@24000",
            "-f",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # macOS speech supports embedded [[...]] voice commands. Render ordinary text only.
        plain_text = text.replace("[", "").replace("]", "")
        try:
            await process.communicate(plain_text.encode("utf-8"))
        except asyncio.CancelledError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
        if process.returncode != 0:
            raise ProviderError("speech_unavailable", "macOS speech synthesis failed.")
