import asyncio
import hmac
import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import StringConstraints, TypeAdapter, ValidationError

from contracts.esp import parse_esp_json, parse_esp_packet
from contracts.models import ClassificationResult, NotificationInput
from contracts.settings import ROOT, Settings
from intelligence import (
    Classifier,
    GroupSummarizer,
    SpeechProvider,
    build_group_summarizer,
    build_providers,
    validate_wav,
)
from intelligence.formatting import (
    _safe_preview,
    format_notification_for_speech,
    redact_preview_secrets,
)

from .pi import PiDelivery
from .schemas import (
    AckRequest,
    AckResponse,
    ClaimResponse,
    DeviceId,
    DeviceRequest,
    EnqueueResponse,
    HealthResponse,
    HeartbeatResponse,
    IngressLogResponse,
    PiAckRequest,
    PiDownloadRequest,
    RetryResponse,
    StateResponse,
)
from .store import ERROR_MESSAGES, QueueError, QueueStore

MAX_NOTIFICATION_BODY = 32 * 1024
INGRESS_PATHS = frozenset({"/api/notifications", "/api/esp/notifications"})
LOOPBACK_HOST = re.compile(r"(?i)(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?")
GROUP_SPEECH = TypeAdapter(
    Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=350)
    ]
)
LOGGER = logging.getLogger(__name__)


async def database_call(operation, *args):
    """Keep bounded SQLite lock and filesystem waits off the HTTP event loop."""
    try:
        return await asyncio.to_thread(operation, *args)
    except sqlite3.OperationalError:
        raise QueueError(503, "Storage is temporarily unavailable; retry shortly.") from None


def provider_error(error: Exception, operation: str) -> str:
    if isinstance(error, TimeoutError):
        return f"{operation}_timeout"
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in ERROR_MESSAGES:
        return code
    return f"{operation}_unavailable"


async def process_queue(
    store: QueueStore,
    wake: asyncio.Event,
    classifier: Classifier,
    speech: SpeechProvider,
    summarizer: GroupSummarizer,
):
    settings = store.settings
    while True:
        wake.clear()
        job = await database_call(store.reserve_job)
        if job is None:
            with suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), 1)
            continue

        message_id = job["id"]
        if job["job_type"] == "classification":
            batch = [job]
            classify_batch = getattr(classifier, "classify_batch", None)
            if classify_batch is not None:
                await asyncio.sleep(settings.classification_batch_wait_seconds)
                batch = await database_call(store.reserve_classification_batch, message_id, 10)
            try:
                async with asyncio.timeout(settings.provider_timeout_seconds):
                    notifications = [
                        NotificationInput.model_validate_json(item["input_json"]) for item in batch
                    ]
                    raw_results = (
                        await classify_batch(notifications)
                        if len(batch) > 1
                        else [await classifier.classify(notifications[0])]
                    )
                    if not isinstance(raw_results, list) or len(raw_results) != len(notifications):
                        raise ValueError("Classification count mismatch")
                    classified = [
                        ClassificationResult.model_validate(result) for result in raw_results
                    ]
                    summaries = [
                        _safe_preview(result.spoken_text)
                        if result.spoken_text is not None
                        else None
                        for result in classified
                    ]
                    results = [
                        format_notification_for_speech(notification, result)
                        for notification, result in zip(notifications, classified, strict=True)
                    ]
            except ValidationError:
                for item in batch:
                    await database_call(store.fail_job, item["id"], "classification_invalid")
            except Exception as error:
                for item in batch:
                    await database_call(
                        store.fail_job, item["id"], provider_error(error, "classification")
                    )
            else:
                for item, result, summary in zip(batch, results, summaries, strict=True):
                    await database_call(store.finish_classification, item["id"], result, summary)
            continue

        if job["job_type"] == "summary":
            try:
                async with asyncio.timeout(settings.provider_timeout_seconds):
                    group = await database_call(store.group_for_summary, message_id)
                    spoken_text = GROUP_SPEECH.validate_python(await summarizer.summarize(group))
            except ValidationError:
                await database_call(store.fail_job, message_id, "summary_invalid")
            except Exception as error:
                await database_call(store.fail_job, message_id, provider_error(error, "summary"))
            else:
                await database_call(store.finish_summary, message_id, spoken_text)
            continue

        path = store.audio_path(message_id)
        staging = path.with_suffix(".pending.wav")
        try:
            async with asyncio.timeout(settings.provider_timeout_seconds):
                published = await speech.synthesize(job["spoken_text"], staging)
        except Exception as error:
            await database_call(store.fail_job, message_id, provider_error(error, "speech"))
        else:
            try:
                if published != staging or staging.is_symlink():
                    raise ValueError("Invalid audio path.")
                validate_wav(
                    staging,
                    max_bytes=settings.max_audio_bytes,
                    max_seconds=settings.max_audio_seconds,
                )
                staging.replace(path)
            except Exception:
                await database_call(store.fail_job, message_id, "speech_invalid")
            else:
                await database_call(store.finish_speech, message_id)
        finally:
            staging.unlink(missing_ok=True)


def create_app(
    settings: Settings | None = None,
    classifier: Classifier | None = None,
    speech: SpeechProvider | None = None,
    summarizer: GroupSummarizer | None = None,
    *,
    allow_test_ingestion: bool = False,
) -> FastAPI:
    settings = settings if settings is not None else Settings()
    store = QueueStore(settings)
    pi = PiDelivery(store)
    pi_audio_lock = asyncio.Lock()
    wake = asyncio.Event()
    sensitive_values = [
        secret.get_secret_value()
        for secret in (settings.esp_ingest_token, settings.openai_api_key)
        if secret is not None and secret.get_secret_value()
    ]

    @asynccontextmanager
    async def lifespan(_app):
        active_classifier = classifier
        active_speech = speech
        active_summarizer = (
            summarizer if summarizer is not None else build_group_summarizer(settings)
        )
        if classifier is None or speech is None:
            default_classifier, default_speech = build_providers(settings)
            if classifier is None:
                active_classifier = default_classifier
            if speech is None:
                active_speech = default_speech
        await database_call(store.initialize)
        await database_call(pi.initialize)
        _app.state.worker_healthy = True

        async def supervise_worker():
            while True:
                try:
                    if not _app.state.worker_healthy:
                        await database_call(store.initialize)
                        _app.state.worker_healthy = True
                    await process_queue(
                        store,
                        wake,
                        active_classifier,
                        active_speech,
                        active_summarizer,
                    )
                except Exception as error:
                    _app.state.worker_healthy = False
                    LOGGER.error(
                        "Queue worker interrupted (%s); retrying storage in one second.",
                        type(error).__name__,
                    )
                    await asyncio.sleep(1)

        worker = asyncio.create_task(supervise_worker())
        _app.state.worker = worker
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        host = request.headers.get("host", "")
        public_host_matches = (
            settings.environment == "production"
            and settings.public_host is not None
            and host.lower() in {settings.public_host, f"{settings.public_host}:443"}
        )
        if not (LOOPBACK_HOST.fullmatch(host) or public_host_matches):
            return JSONResponse({"detail": "The request host is not allowed."}, status_code=403)
        if public_host_matches and request.url.scheme != "https":
            return JSONResponse({"detail": "HTTPS is required."}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None and origin.lower() != f"{request.url.scheme}://{host.lower()}":
                return JSONResponse(
                    {"detail": "The request origin is not allowed."}, status_code=403
                )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {"detail": "The request origin is not allowed."}, status_code=403
                )
        response = await call_next(request)
        # The dashboard and its unbundled assets must refresh together after deploys.
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.middleware("http")
    async def log_ingress(request: Request, call_next):
        path = request.scope["path"]
        if request.method != "POST" or path not in INGRESS_PATHS:
            return await call_next(request)
        started = perf_counter()
        entry = {
            "id": uuid4(),
            "received_at": datetime.now(timezone.utc),
            "method": "POST",
            "path": path,
        }
        request.state.ingress_entry = entry
        try:
            response = await call_next(request)
        except Exception as error:
            LOGGER.error("Notification ingress interrupted (%s).", type(error).__name__)
            response = JSONResponse({"detail": "Notification ingress failed."}, status_code=500)
        entry["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        if response.status_code != 202:
            for field in ("event_id", "app", "payload", "queue_status"):
                entry.pop(field, None)
        entry["status_code"] = response.status_code
        try:
            await database_call(store.record_ingress, entry)
        except QueueError:
            LOGGER.error("Could not persist request history metadata.")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def redact_log_text(value: str, max_length: int) -> str:
        for secret in sensitive_values:
            value = value.replace(secret, "redacted")
        return _safe_preview(value)[:max_length].strip()

    def ingress_payload(payload: dict | str, notification: NotificationInput) -> dict | str:
        def redact(value: str) -> str:
            for secret in sensitive_values:
                value = value.replace(secret, "redacted")
            return redact_preview_secrets(value)

        if isinstance(payload, str):
            return "[Content unavailable]" if notification.content_hidden else redact(payload)
        result = {}
        for name, value in payload.items():
            if notification.content_hidden and name in {
                "sender",
                "title",
                "subtitle",
                "body",
                "message",
                "sender_id",
                "conversation_id",
                "conversation_name",
            }:
                result[name] = "" if name in {"title", "subtitle", "body", "message"} else None
            else:
                result[name] = redact(value) if isinstance(value, str) else value
        return result

    async def accept_notification(
        request: Request, notification: NotificationInput, payload: dict | str
    ):
        entry = request.state.ingress_entry
        event_id = str(notification.event_id)
        entry["event_id"] = event_id
        entry["app"] = redact_log_text(notification.app, 100) or "Unknown app"
        entry["payload"] = ingress_payload(payload, notification)
        entry["payload_redacted"] = entry["payload"] != payload
        # Capture the original request before the worker can classify/delete queue content.
        await database_call(store.record_ingress, entry)
        status = await database_call(store.enqueue, notification)
        entry["queue_status"] = status
        wake.set()
        return {"event_id": event_id, "status": status}

    @app.exception_handler(QueueError)
    async def queue_error(_request: Request, error: QueueError):
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse({"detail": "The request contains invalid fields."}, status_code=422)

    @app.get("/healthz", response_model=HealthResponse)
    async def health():
        worker = getattr(app.state, "worker", None)
        if worker is None or worker.done() or not getattr(app.state, "worker_healthy", False):
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    async def enqueue(request: Request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise QueueError(415, "Send notifications as application/json.")
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal() or len(length) > 12:
                raise QueueError(400, "The request has an invalid content length.")
            if int(length) > MAX_NOTIFICATION_BODY:
                raise QueueError(413, "The notification body exceeds 32 KiB.")
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > MAX_NOTIFICATION_BODY:
                raise QueueError(413, "The notification body exceeds 32 KiB.")
            raw.extend(part)
        try:
            notification = NotificationInput.model_validate_json(raw)
        except ValidationError as error:
            raise QueueError(422, "The notification contains invalid fields.") from error
        return await accept_notification(request, notification, json.loads(raw))

    # Explicit Python-only hook for isolated tests; never registered in production.
    if allow_test_ingestion and settings.environment == "local":
        app.add_api_route(
            "/api/notifications",
            enqueue,
            methods=["POST"],
            status_code=202,
            response_model=EnqueueResponse,
        )

    @app.post("/api/esp/notifications", status_code=202, response_model=EnqueueResponse)
    async def enqueue_esp(request: Request):
        configured = settings.esp_ingest_token
        if configured is None:
            if settings.environment == "production":
                raise QueueError(503, "ESP ingestion is not configured.")
        else:
            scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                supplied.encode("utf-8"), configured.get_secret_value().encode("utf-8")
            ):
                return JSONResponse(
                    {"detail": "An ESP ingestion token is required."},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "text/plain"}:
            raise QueueError(415, "Send ESP packets as application/json or text/plain UTF-8.")
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > MAX_NOTIFICATION_BODY:
                raise QueueError(413, "The notification body exceeds 32 KiB.")
            raw.extend(part)
        try:
            header_id = request.headers.get("x-event-id")
            event_id = UUID(header_id) if header_id is not None else None
            if content_type == "application/json":
                notification = parse_esp_json(
                    raw, timezone_name=settings.esp_timezone, event_id=event_id
                )
            else:
                notification = parse_esp_packet(
                    raw.decode("utf-8"), timezone_name=settings.esp_timezone, event_id=event_id
                )
        except (ValueError, UnicodeError):
            raise QueueError(
                422, "The ESP packet contains invalid fields or an ambiguous timestamp."
            ) from None
        payload = json.loads(raw) if content_type == "application/json" else raw.decode("utf-8")
        return await accept_notification(request, notification, payload)

    @app.get("/api/ingress-log", response_model=IngressLogResponse)
    async def recent_ingress(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        before: Annotated[int | None, Query(ge=1)] = None,
    ):
        return await database_call(store.ingress_history, limit, before)

    @app.get("/status")
    async def pi_status():
        return await database_call(pi.status)

    @app.get("/api/pi/status")
    async def pi_dashboard():
        return await database_call(pi.dashboard)

    @app.get("/audio/{message_id}")
    async def pi_audio(message_id: UUID, request: Request):
        if "range" in request.headers:
            raise QueueError(416, "Download the complete audio file for Pi playback.")
        if pi_audio_lock.locked():
            raise QueueError(409, "A Pi audio transfer is already running.")
        await pi_audio_lock.acquire()
        try:
            path, lease_id = await database_call(pi.begin_audio, str(message_id))
        except BaseException:
            pi_audio_lock.release()
            raise

        class TrackedAudio(FileResponse):
            async def __call__(self, scope, receive, send):
                async def tracked_send(message):
                    if message["type"] == "http.response.body" and not message.get(
                        "more_body", False
                    ):
                        await database_call(pi.finish_audio, str(message_id), lease_id, True)
                    await send(message)

                try:
                    # Use ordinary body frames so the final frame can be tracked.
                    scope = {
                        **scope,
                        "extensions": {
                            k: v
                            for k, v in scope.get("extensions", {}).items()
                            if k != "http.response.pathsend"
                        },
                    }
                    await super().__call__(scope, receive, tracked_send)
                except BaseException:
                    with suppress(Exception):
                        await database_call(pi.finish_audio, str(message_id), lease_id, False)
                    raise
                finally:
                    pi_audio_lock.release()

        return TrackedAudio(path, media_type="audio/wav", headers={"X-Pi-Transfer-ID": lease_id})

    @app.post("/api/pi/downloaded")
    async def pi_downloaded(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 1024:
                raise QueueError(413, "The download receipt is too large.")
            raw.extend(chunk)
        try:
            receipt = PiDownloadRequest.model_validate_json(raw)
        except ValidationError:
            raise QueueError(422, "Send one valid download receipt.") from None
        return await database_call(
            pi.confirm_download, str(receipt.id), str(receipt.transfer_id),
            receipt.size, receipt.sha256,
        )

    @app.post("/ack")
    async def pi_ack(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 1024:
                raise QueueError(413, "The acknowledgment is too large.")
            raw.extend(chunk)
        try:
            ack = PiAckRequest.model_validate_json(raw)
        except ValidationError:
            raise QueueError(422, "Send exactly one downloaded notification ID.") from None
        return await database_call(pi.acknowledge, str(ack.ids[0]))

    @app.get("/api/state", response_model=StateResponse)
    async def state():
        return {
            "providers": {"classifier": settings.classifier_provider, "tts": settings.tts_provider},
            **(await database_call(store.snapshot)),
        }

    @app.post("/api/delivery/claim", response_model=ClaimResponse)
    async def claim(request: DeviceRequest):
        return {"delivery": await database_call(store.claim, request.device_id)}

    @app.post("/api/delivery/{lease_id}/heartbeat", response_model=HeartbeatResponse)
    async def heartbeat(lease_id: UUID, request: DeviceRequest):
        return {"delivery": await database_call(store.heartbeat, str(lease_id), request.device_id)}

    @app.get("/api/delivery/{lease_id}/audio")
    async def audio(lease_id: UUID, device_id: Annotated[DeviceId, Query()]):
        return FileResponse(
            await database_call(store.authorize_audio, str(lease_id), device_id),
            media_type="audio/wav",
        )

    @app.post("/api/delivery/{lease_id}/ack", response_model=AckResponse)
    async def acknowledge(lease_id: UUID, request: AckRequest):
        status = await database_call(
            store.acknowledge, str(lease_id), request.device_id, request.outcome
        )
        return {"status": status}

    @app.post("/api/messages/{message_id}/retry", response_model=RetryResponse)
    async def retry(message_id: UUID):
        status = await database_call(store.retry, str(message_id))
        wake.set()
        return {"status": status}

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True, check_dir=False), name="web")
    return app


app = create_app()
