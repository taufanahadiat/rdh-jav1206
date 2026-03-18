#!/usr/bin/env python3
import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import snap7
from fastapi import Body
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import DB2_General as db2
from db_awl_reader import calc_struct_size, parse_awl_file, read_struct, read_tag_direct


PLC_IP = os.getenv("PLC_IP", db2.PLC_IP)
RACK = int(os.getenv("PLC_RACK", str(db2.RACK)))
SLOT = int(os.getenv("PLC_SLOT", str(db2.SLOT)))
POLL_INTERVAL_MS = min(max(int(os.getenv("PLC_POLL_INTERVAL_MS", "1000")), 250), 60000)
ALLOW_ORIGINS_RAW = os.getenv("PLC_API_ALLOW_ORIGINS", "*")

APP_DIR = Path(__file__).resolve().parent
AWL_DIR = Path("/var/www/S7_DB")
SCRIPT_RE = re.compile(r"^DB(?P<db>\d+)_(?P<name>.+)\.py$", re.IGNORECASE)
STRING_TAG_RE = re.compile(r"^DB(?P<db>\d+)\.DBB(?P<byte>\d+)\[(?P<len>\d+)\]$", re.IGNORECASE)
DIRECT_TAG_RE = re.compile(r"^DB(?P<db>\d+)\.(DBX|DBB|DBW|DBD|DBS)(?P<byte>\d+)(?:\.(?P<extra>\d+))?$", re.IGNORECASE)


@dataclass
class PlcSource:
    db_num: int
    name: str
    script_path: Path
    kind: str
    awl_path: Optional[Path] = None
    source_file: Optional[str] = None
    total_bytes: int = 0
    type_map: Dict[str, Any] = field(default_factory=dict)
    db_fields: List[Any] = field(default_factory=list)
    size_cache: Dict[str, int] = field(default_factory=dict)
    disabled_reason: str = ""


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event: str, **payload: Any) -> None:
    data = {
        "timestamp_utc": now_utc_iso(),
        "event": event,
    }
    data.update(payload)
    print(json.dumps(data, ensure_ascii=False), flush=True)


def connect_plc() -> snap7.client.Client:
    plc = snap7.client.Client()
    plc.connect(PLC_IP, RACK, SLOT)
    if not plc.get_connected():
        raise RuntimeError("Failed to connect to PLC")
    return plc


def normalize_tag(raw_tag: str) -> tuple[str, int]:
    clean = re.sub(r"\s+", "", str(raw_tag or "").upper())
    match = STRING_TAG_RE.match(clean)
    if match:
        db_num = int(match.group("db"))
        max_len = int(match.group("len"))
        if max_len < 1 or max_len > 254:
            raise ValueError(f"Invalid STRING length in tag: {raw_tag}")
        return clean, db_num

    match = DIRECT_TAG_RE.match(clean)
    if not match:
        raise ValueError(f"Invalid PLC tag format: {raw_tag}")

    db_num = int(match.group("db"))
    area = match.group(2).upper()
    byte_offset = int(match.group("byte"))
    extra = match.group("extra")

    if area == "DBX":
        if extra is None:
            raise ValueError(f"Bit offset is required for tag: {raw_tag}")
        bit_offset = int(extra)
        if bit_offset < 0 or bit_offset > 7:
            raise ValueError(f"Invalid bit offset in tag: {raw_tag}")
        return f"DB{db_num}.DBX{byte_offset}.{bit_offset}", db_num

    if area == "DBS":
        max_len = 50 if extra is None else int(extra)
        if max_len < 1 or max_len > 254:
            raise ValueError(f"Invalid STRING length in tag: {raw_tag}")
        return f"DB{db_num}.DBB{byte_offset}[{max_len}]", db_num

    if extra is not None:
        raise ValueError(f"Unexpected suffix in tag: {raw_tag}")

    return f"DB{db_num}.{area}{byte_offset}", db_num


def discover_sources() -> List[PlcSource]:
    sources: List[PlcSource] = []
    for script_path in sorted(APP_DIR.glob("DB*.py")):
        if script_path.name == "DB2_General.py":
            sources.append(
                PlcSource(
                    db_num=2,
                    name="General",
                    script_path=script_path,
                    kind="db2_general",
                    source_file=str(script_path),
                )
            )
            continue

        match = SCRIPT_RE.match(script_path.name)
        if not match:
            continue

        db_num = int(match.group("db"))
        db_name = match.group("name")
        awl_path = AWL_DIR / f"{script_path.stem}.AWL"
        if not awl_path.is_file():
            log_event("source_skipped", script=str(script_path), reason="missing_awl", awl=str(awl_path))
            continue

        with open(awl_path, "r", encoding="utf-8", errors="ignore") as handle:
            awl_text = handle.read()

        type_map, db_fields = parse_awl_file(awl_text, db_num)
        size_cache: Dict[str, int] = {}
        total_bytes = calc_struct_size(db_fields, type_map, size_cache)

        sources.append(
            PlcSource(
                db_num=db_num,
                name=db_name,
                script_path=script_path,
                kind="awl",
                awl_path=awl_path,
                source_file=str(awl_path),
                total_bytes=total_bytes,
                type_map=type_map,
                db_fields=db_fields,
                size_cache=size_cache,
            )
        )

    return sources


def read_db2_source(plc: snap7.client.Client, source: PlcSource) -> Dict[str, Any]:
    payload = db2.build_payload(plc)
    tag_values = {
        "DB2.DBB0[50]": payload.get("product"),
        "DB2.DBB52[50]": payload.get("recipe"),
        "DB2.DBB104[50]": payload.get("campaign"),
    }

    return {
        "db": source.db_num,
        "name": source.name,
        "source_file": source.source_file,
        "data": payload,
        "tag_values": tag_values,
    }


def read_awl_source(plc: snap7.client.Client, source: PlcSource) -> Dict[str, Any]:
    buffer = bytearray(plc.db_read(source.db_num, 0, source.total_bytes))
    address_map: Dict[str, Any] = {}
    result = read_struct(
        buffer,
        source.db_fields,
        source.type_map,
        0,
        source.size_cache,
        address_map=address_map,
        db_num=source.db_num,
    )

    return {
        "db": source.db_num,
        "name": source.name,
        "source_file": source.source_file,
        "total_bytes": source.total_bytes,
        "data": result,
        "tag_values": address_map,
    }


def build_snapshot(sources: List[PlcSource]) -> Dict[str, Any]:
    snapshot = {
        "ok": True,
        "plc_ip": PLC_IP,
        "timestamp_utc": now_utc_iso(),
        "poll_interval_ms": POLL_INTERVAL_MS,
        "db_count": 0,
        "dbs": {},
        "tag_values": {},
        "errors": {},
    }

    plc = connect_plc()
    try:
        for source in sources:
            if source.disabled_reason != "":
                snapshot["errors"][f"DB{source.db_num}"] = source.disabled_reason
                continue

            try:
                if source.kind == "db2_general":
                    payload = read_db2_source(plc, source)
                else:
                    payload = read_awl_source(plc, source)

                key = f"DB{source.db_num}"
                snapshot["dbs"][key] = payload
                snapshot["tag_values"].update(payload.get("tag_values", {}))
            except Exception as exc:
                message = str(exc)
                if "Address out of range" in message:
                    source.disabled_reason = message
                snapshot["errors"][f"DB{source.db_num}"] = message
        snapshot["db_count"] = len(snapshot["dbs"])
        return snapshot
    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass


def empty_snapshot(sources: List[PlcSource]) -> Dict[str, Any]:
    return {
        "ok": True,
        "plc_ip": PLC_IP,
        "timestamp_utc": now_utc_iso(),
        "poll_interval_ms": POLL_INTERVAL_MS,
        "db_count": 0,
        "dbs": {},
        "tag_values": {},
        "errors": {},
        "configured_sources": [f"DB{source.db_num}" for source in sources],
    }


def collect_tag_values(snapshot: Dict[str, Any], tags: List[str]) -> tuple[Dict[str, Any], List[str]]:
    tag_values = snapshot.get("tag_values", {})
    found: Dict[str, Any] = {}
    missing: List[str] = []

    for tag in tags:
        if tag in tag_values:
            found[tag] = tag_values[tag]
        else:
            missing.append(tag)

    return found, missing


def read_missing_tags_direct(tags: List[str]) -> Dict[str, Any]:
    if not tags:
        return {}

    normalized: Dict[int, List[str]] = {}
    for raw_tag in tags:
        tag, db_num = normalize_tag(raw_tag)
        normalized.setdefault(db_num, []).append(tag)

    result: Dict[str, Any] = {}
    plc = connect_plc()
    try:
        for db_num, db_tags in normalized.items():
            if db_num == db2.DB_NUM:
                string_tags = [tag for tag in db_tags if STRING_TAG_RE.match(tag)]
                direct_tags = [tag for tag in db_tags if tag not in string_tags]
                if string_tags:
                    result.update(db2.read_tags(plc, string_tags))
                for tag in direct_tags:
                    result[tag] = read_tag_direct(plc, tag)
                continue

            for tag in db_tags:
                result[tag] = read_tag_direct(plc, tag)
    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass

    return result


def get_db2_payload(snapshot: Dict[str, Any], tags: Optional[List[str]] = None) -> Dict[str, Any]:
    db_payload = snapshot.get("dbs", {}).get("DB2")
    if db_payload is None:
        raise RuntimeError("DB2 cache is not ready.")

    payload = {
        "db": 2,
        "plc_ip": PLC_IP,
        "timestamp_utc": snapshot.get("timestamp_utc", now_utc_iso()),
    }

    if tags:
        requested = []
        for tag in tags:
            normalized, db_num = normalize_tag(tag)
            if db_num != 2:
                raise ValueError(f"Tag {tag} does not belong to DB2")
            requested.append(normalized)

        values, missing = collect_tag_values(snapshot, requested)
        if missing:
            values.update(read_missing_tags_direct(missing))

        payload["source_file"] = db_payload.get("source_file")
        payload["tags"] = values
        if len(values) == 1:
            only_tag = next(iter(values))
            payload["tag"] = only_tag
            payload["value"] = values[only_tag]
        return payload

    payload.update(db_payload.get("data", {}))
    return payload


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


app = FastAPI(title="PLC Realtime API", version="2.0.0", lifespan=lifespan)

allow_origins = [item.strip() for item in ALLOW_ORIGINS_RAW.split(",") if item.strip() != ""]
if not allow_origins:
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
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

    normalized_tags: List[str] = []
    for raw_tag in tag:
        try:
            normalized, _db_num = normalize_tag(raw_tag)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if normalized not in normalized_tags:
            normalized_tags.append(normalized)

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


def build_dashboard_snapshot(tag_list: Optional[List[str]], direct_read_missing: bool) -> dict:
    snapshot = getattr(app.state, "snapshot", empty_snapshot([]))
    requested_tags = tag_list or sorted(snapshot.get("tag_values", {}).keys())

    normalized_tags: List[str] = []
    for raw_tag in requested_tags:
        normalized, _db_num = normalize_tag(raw_tag)
        if normalized not in normalized_tags:
            normalized_tags.append(normalized)

    tag_values, missing = collect_tag_values(snapshot, normalized_tags)
    source = "cache"
    if missing and direct_read_missing:
        tag_values.update(read_missing_tags_direct(missing))
        missing = [tag for tag in missing if tag not in tag_values]
        source = "mixed"

    return {
        "ok": True,
        "timestamp_utc": now_utc_iso(),
        "cache_timestamp_utc": snapshot.get("timestamp_utc"),
        "poll_interval_ms": snapshot.get("poll_interval_ms", POLL_INTERVAL_MS),
        "source": source,
        "requested_tags": normalized_tags,
        "missing_tags": missing,
        "tag_values": tag_values,
        "errors": snapshot.get("errors", {}),
    }


@app.get("/plc/dashboard-snapshot")
def get_dashboard_snapshot(
    tag: Optional[List[str]] = Query(default=None),
    direct_read_missing: bool = Query(default=True),
) -> dict:
    try:
        return build_dashboard_snapshot(tag, direct_read_missing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/plc/dashboard-snapshot")
def post_dashboard_snapshot(payload: Optional[dict] = Body(default=None)) -> dict:
    payload = payload or {}
    raw_tags = payload.get("tags")
    if isinstance(raw_tags, str):
        tag_list = [item.strip() for item in raw_tags.split(",") if item.strip() != ""]
    elif isinstance(raw_tags, list):
        tag_list = [str(item).strip() for item in raw_tags if str(item).strip() != ""]
    else:
        tag_list = None

    direct_read_missing = bool(payload.get("direct_read_missing", True))

    try:
        return build_dashboard_snapshot(tag_list, direct_read_missing)
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
