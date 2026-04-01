import asyncio
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request as StarletteRequest

from plc.api.plc_api_app.config import PLC_IP, POLL_INTERVAL_MS, build_allow_origins, log_event, now_utc_iso
from plc.api.plc_api_app.snapshot_service import build_snapshot, discover_sources, empty_snapshot
from plc.api.plc_api_app.tag_service import (
    build_dashboard_snapshot,
    collect_tag_values,
    get_db2_payload,
    normalize_requested_tags,
    parse_dashboard_tag_list,
    read_missing_tags_direct,
)

FRONTEND_HTTP_LOG_SKIP_PREFIXES = (
    "/include/dashboard/plc/dashboard-snapshot",
    "/plc/dashboard-snapshot",
    "/plc/tags",
)
PLC_API_CALLER_HEADER = "x-plcapi-caller"
INTERNAL_CALLERS = {"historian_listener", "historian-listener"}
SEVERITY_ORDER = {
    "low": 10,
    "medium": 20,
    "high": 30,
    "critical": 40,
    "crucial": 50,
}


def get_plc_api_caller(request: StarletteRequest) -> str:
    return str(request.headers.get(PLC_API_CALLER_HEADER, "")).strip().lower()


def is_internal_caller(request: StarletteRequest) -> bool:
    return get_plc_api_caller(request) in INTERNAL_CALLERS


def should_skip_http_log(path: str, request: StarletteRequest) -> bool:
    normalized = str(path or "")
    if not any(normalized.startswith(prefix) for prefix in FRONTEND_HTTP_LOG_SKIP_PREFIXES):
        return False
    return not is_internal_caller(request)


def should_log_for_frontend_skip(severity: str) -> bool:
    return SEVERITY_ORDER.get(str(severity or "").strip().lower(), 10) > SEVERITY_ORDER["medium"]


def is_unreachable_peer_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "unreachable peer" in message
        or "recv tcp" in message
    )


async def refresh_snapshot_forever(app: FastAPI) -> None:
    while True:
        try:
            snapshot = await asyncio.to_thread(build_snapshot, app.state.sources)
            app.state.snapshot = snapshot
            app.state.last_refresh_error = ""
            if app.state.plc_unreachable_active:
                log_event(
                    "plc_reconnected",
                    previous_error=app.state.plc_unreachable_message,
                )
                app.state.plc_unreachable_active = False
                app.state.plc_unreachable_message = ""
        except Exception as exc:
            message = str(exc)
            app.state.last_refresh_error = message
            if is_unreachable_peer_error(exc):
                if not app.state.plc_unreachable_active:
                    app.state.plc_unreachable_active = True
                    app.state.plc_unreachable_message = message
                    log_event(
                        "plc_unreachable_detected",
                        message=message,
                        severity="critical",
                        status_code=503,
                    )
            else:
                log_event("refresh_error", message=message)
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sources = discover_sources()
    app.state.sources = sources
    app.state.snapshot = empty_snapshot(sources)
    app.state.last_refresh_error = ""
    app.state.plc_unreachable_active = False
    app.state.plc_unreachable_message = ""
    log_event(
        "sources_loaded",
        count=len(sources),
        poll_interval_ms=POLL_INTERVAL_MS,
        dbs=[f"DB{source.db_num}" for source in sources],
    )

    try:
        app.state.snapshot = await asyncio.to_thread(build_snapshot, sources)
    except Exception as exc:
        message = str(exc)
        app.state.last_refresh_error = message
        if is_unreachable_peer_error(exc):
            app.state.plc_unreachable_active = True
            app.state.plc_unreachable_message = message
            log_event(
                "plc_unreachable_detected",
                message=message,
                severity="critical",
                status_code=503,
            )
        else:
            log_event("initial_refresh_error", message=message)

    refresh_task = asyncio.create_task(refresh_snapshot_forever(app))
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="PLC Realtime API", version="2.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=build_allow_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_http_requests(request, call_next):
        started = time.monotonic()
        request_path = request.url.path
        caller = get_plc_api_caller(request)
        skip_http_log = should_skip_http_log(request_path, request)
        try:
            response = await call_next(request)
        except Exception as exc:
            severity = "critical"
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            if (not skip_http_log) or should_log_for_frontend_skip(severity):
                log_event(
                    "http_request_failed",
                    method=request.method,
                    path=request_path,
                    query=str(request.url.query),
                    http_status=500,
                    severity=severity,
                    status_code=500,
                    duration_ms=duration_ms,
                    caller=caller,
                    message=str(exc),
                )
            raise

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        http_status = int(response.status_code)
        severity = "medium"

        if skip_http_log and not should_log_for_frontend_skip(severity):
            return response

        log_event(
            "http_request_completed",
            method=request.method,
            path=request_path,
            query=str(request.url.query),
            http_status=http_status,
            severity=severity,
            status_code=http_status,
            duration_ms=duration_ms,
            caller=caller,
        )
        return response

    @app.get("/health")
    def health() -> dict:
        snapshot = getattr(app.state, "snapshot", {})
        return {
            "status": "ok",
            "service": "plc-api",
            "plc_ip": PLC_IP,
            "poll_interval_ms": POLL_INTERVAL_MS,
            "timestamp_utc": now_utc_iso(),
            "cache_timestamp_utc": snapshot.get("timestamp_utc"),
            "db_count": snapshot.get("db_count", 0),
            "last_refresh_error": getattr(app.state, "last_refresh_error", ""),
        }

    @app.get("/plc/cache")
    def get_cache() -> dict:
        snapshot = getattr(app.state, "snapshot", None)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="PLC cache is not ready.")
        return snapshot

    @app.get("/plc/tags")
    def get_tags(
        request: StarletteRequest,
        tag: Optional[List[str]] = Query(default=None),
        direct_read_missing: bool = Query(default=True),
    ) -> dict:
        if not tag:
            raise HTTPException(status_code=400, detail="No PLC tags were requested.")

        try:
            normalized_tags = normalize_requested_tags(tag)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
        tag_values, missing = collect_tag_values(snapshot, normalized_tags)
        source = "cache"

        if missing and direct_read_missing:
            try:
                tag_values.update(
                    read_missing_tags_direct(
                        missing,
                        emit_log=is_internal_caller(request),
                    )
                )
                missing = [tag for tag in missing if tag not in tag_values]
                source = "mixed"
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "ok": True,
            "timestamp_utc": now_utc_iso(),
            "cache_timestamp_utc": snapshot.get("timestamp_utc"),
            "source": source,
            "tag_values": tag_values,
            "missing_tags": missing,
        }

    @app.get("/plc/dashboard-snapshot")
    @app.get("/include/dashboard/plc/dashboard-snapshot")
    def get_dashboard_snapshot(
        request: StarletteRequest,
        tag: Optional[List[str]] = Query(default=None),
        direct_read_missing: bool = Query(default=True),
    ) -> dict:
        snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
        try:
            return build_dashboard_snapshot(
                snapshot,
                tag,
                direct_read_missing,
                emit_direct_read_log=is_internal_caller(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/plc/dashboard-snapshot")
    @app.post("/include/dashboard/plc/dashboard-snapshot")
    def post_dashboard_snapshot(request: StarletteRequest, payload: Optional[dict] = Body(default=None)) -> dict:
        payload = payload or {}
        tag_list = parse_dashboard_tag_list(payload.get("tags"))
        direct_read_missing = bool(payload.get("direct_read_missing", True))

        snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
        try:
            return build_dashboard_snapshot(
                snapshot,
                tag_list,
                direct_read_missing,
                emit_direct_read_log=is_internal_caller(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/plc/db2/general")
    def get_db2_general(tag: Optional[List[str]] = Query(default=None)) -> dict:
        snapshot = getattr(app.state, "snapshot", None)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="PLC cache is not ready.")
        try:
            return get_db2_payload(snapshot, tag)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/ws/plc/db2/general")
    async def ws_db2_general(websocket: WebSocket):
        await websocket.accept()

        tags = websocket.query_params.getlist("tag")
        interval_raw = websocket.query_params.get("interval_ms", str(POLL_INTERVAL_MS))
        try:
            interval_ms = int(interval_raw)
        except ValueError:
            interval_ms = POLL_INTERVAL_MS
        interval_ms = min(max(interval_ms, 250), 10000)

        try:
            while True:
                try:
                    snapshot = getattr(app.state, "snapshot", None)
                    if snapshot is None:
                        raise RuntimeError("PLC cache is not ready.")
                    payload = get_db2_payload(snapshot, tags or None)
                    await websocket.send_json({"ok": True, "data": payload})
                except Exception as exc:
                    await websocket.send_json({"ok": False, "error": str(exc), "timestamp_utc": now_utc_iso()})

                await asyncio.sleep(interval_ms / 1000)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
