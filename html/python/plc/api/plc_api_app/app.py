import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

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


async def refresh_snapshot_forever(app: FastAPI) -> None:
    while True:
        try:
            snapshot = await asyncio.to_thread(build_snapshot, app.state.sources)
            app.state.snapshot = snapshot
            app.state.last_refresh_error = ""
        except Exception as exc:
            app.state.last_refresh_error = str(exc)
            log_event("refresh_error", message=str(exc))
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sources = discover_sources()
    app.state.sources = sources
    app.state.snapshot = empty_snapshot(sources)
    app.state.last_refresh_error = ""
    log_event(
        "sources_loaded",
        count=len(sources),
        poll_interval_ms=POLL_INTERVAL_MS,
        dbs=[f"DB{source.db_num}" for source in sources],
    )

    try:
        app.state.snapshot = await asyncio.to_thread(build_snapshot, sources)
    except Exception as exc:
        app.state.last_refresh_error = str(exc)
        log_event("initial_refresh_error", message=str(exc))

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
    def get_tags(tag: Optional[List[str]] = Query(default=None), direct_read_missing: bool = Query(default=True)) -> dict:
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
                tag_values.update(read_missing_tags_direct(missing))
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
    def get_dashboard_snapshot(
        tag: Optional[List[str]] = Query(default=None),
        direct_read_missing: bool = Query(default=True),
    ) -> dict:
        snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
        try:
            return build_dashboard_snapshot(snapshot, tag, direct_read_missing)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/plc/dashboard-snapshot")
    def post_dashboard_snapshot(payload: Optional[dict] = Body(default=None)) -> dict:
        payload = payload or {}
        tag_list = parse_dashboard_tag_list(payload.get("tags"))
        direct_read_missing = bool(payload.get("direct_read_missing", True))

        snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
        try:
            return build_dashboard_snapshot(snapshot, tag_list, direct_read_missing)
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
