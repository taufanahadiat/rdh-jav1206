import json
import os
import socket
import threading
import time
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from config import DB_APP_NAME, SYSTEMLOG_ENABLED, SYSTEMLOG_TABLE, get_postgres_config


SEVERITY_RANKS = {
    "low": 10,
    "medium": 20,
    "high": 30,
    "critical": 40,
    "crucial": 50,
}
DEFAULT_STATUS_CODES = {
    "low": 100,
    "medium": 200,
    "high": 300,
    "critical": 400,
    "crucial": 500,
}
_INIT_LOCK = threading.Lock()
_READY = False
_DISABLED_UNTIL = 0.0
_HOSTNAME = socket.gethostname()
_COALESCE_LOCK = threading.Lock()
_COALESCE_STATE: dict[str, dict[str, float]] = {}
_COALESCE_WINDOWS_SECONDS = {
    "low": 2.0,
    "medium": 2.0,
    "high": 5.0,
    "critical": 10.0,
    "crucial": 3.0,
}
_COALESCE_EVENT_WINDOWS_SECONDS = {
    ("plc_api", "plc_api_app", "refresh_error"): 20.0,
    ("historian", "listener", "error"): 20.0,
}
_COALESCE_STALE_SECONDS = 600.0
_COALESCE_MAX_KEYS = 4000
_STATUS_CODE_MAP_PATH = Path(__file__).resolve().with_name("systemlog_status_codes.json")
_STATUS_CODE_MAP_LOCK = threading.Lock()
_STATUS_CODE_MAP_MTIME = -1.0
_STATUS_CODE_MAP: dict[str, Any] = {}
_VOLATILE_PAYLOAD_KEYS = {
    "timestamp",
    "timestamp_utc",
    "duration_ms",
    "eventtime",
    "_",
}


def json_dumps_default(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_severity(value: Optional[str]) -> str:
    normalized = str(value or "low").strip().lower()
    return normalized if normalized in SEVERITY_RANKS else "low"


def _parse_int_status(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_status_code_map() -> dict[str, Any]:
    global _STATUS_CODE_MAP_MTIME
    global _STATUS_CODE_MAP

    try:
        mtime = float(_STATUS_CODE_MAP_PATH.stat().st_mtime)
    except OSError:
        mtime = -1.0

    with _STATUS_CODE_MAP_LOCK:
        if _STATUS_CODE_MAP_MTIME == mtime:
            return _STATUS_CODE_MAP

        if mtime < 0:
            _STATUS_CODE_MAP = {}
            _STATUS_CODE_MAP_MTIME = mtime
            return _STATUS_CODE_MAP

        try:
            raw = json.loads(_STATUS_CODE_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            _STATUS_CODE_MAP = {}
            _STATUS_CODE_MAP_MTIME = mtime
            return _STATUS_CODE_MAP

        if isinstance(raw, dict) and isinstance(raw.get("status_codes"), dict):
            mapping = raw["status_codes"]
        elif isinstance(raw, dict):
            mapping = raw
        else:
            mapping = {}

        _STATUS_CODE_MAP = mapping
        _STATUS_CODE_MAP_MTIME = mtime
        return _STATUS_CODE_MAP


def _resolve_payload_pointer(payload: Optional[dict[str, Any]], pointer: str) -> Any:
    if payload is None:
        return None
    current: Any = payload
    for part in pointer.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_mapped_status(value: Any, payload: Optional[dict[str, Any]]) -> Optional[int]:
    numeric = _parse_int_status(value)
    if numeric is not None:
        return numeric

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("$payload."):
            payload_value = _resolve_payload_pointer(payload, text[len("$payload."):])
            return _parse_int_status(payload_value)
    return None


def get_mapped_status_code(
    service: str,
    component: str,
    event: str,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    mapping = _read_status_code_map()
    if not isinstance(mapping, dict):
        return None

    service_key = str(service or "").strip()
    component_key = str(component or "").strip()
    event_key = str(event or "").strip()

    for service_name in (service_key, "*"):
        service_map = mapping.get(service_name)
        if not isinstance(service_map, dict):
            continue
        for component_name in (component_key, "*"):
            component_map = service_map.get(component_name)
            if not isinstance(component_map, dict):
                continue
            mapped_value = component_map.get(event_key)
            if mapped_value is None:
                mapped_value = component_map.get("*")
            resolved = _resolve_mapped_status(mapped_value, payload)
            if resolved is not None:
                return resolved

    return None


def infer_severity(event: str) -> str:
    event_lower = str(event or "").strip().lower()
    if any(token in event_lower for token in ("fatal", "panic", "crash", "uncaught")):
        return "crucial"
    if any(token in event_lower for token in ("error", "failed", "failure", "timeout", "unreachable", "shutdown")):
        return "critical"
    if any(token in event_lower for token in ("recovered", "recovery", "reconnected", "precondition", "postcondition")):
        return "high"
    if any(token in event_lower for token in ("skipped", "invalid", "missing", "not_ready", "not_running")):
        return "medium"
    return "low"


def infer_status_code(event: str, severity: str, payload: Optional[dict[str, Any]]) -> int:
    if payload is not None:
        explicit = payload.get("status_code")
        if explicit is not None:
            try:
                return int(explicit)
            except (TypeError, ValueError):
                pass

    event_lower = str(event or "").strip().lower()
    if "http_request" in event_lower and payload is not None:
        http_status = payload.get("http_status")
        if http_status is not None:
            try:
                return int(http_status)
            except (TypeError, ValueError):
                pass

    if "connected" in event_lower or "loaded" in event_lower:
        return 110
    if "saved" in event_lower or "inserted" in event_lower or "updated" in event_lower:
        return 130
    if "skipped" in event_lower or "invalid" in event_lower or "missing" in event_lower:
        return 220
    if "recovered" in event_lower or "reconnected" in event_lower or "precondition" in event_lower:
        return 330
    if "timeout" in event_lower or "shutdown" in event_lower or "postcondition" in event_lower:
        return 430
    if "error" in event_lower or "failed" in event_lower:
        return 530 if severity == "crucial" else 500
    return DEFAULT_STATUS_CODES.get(severity, 100)


def _normalize_payload_for_signature(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value.keys()):
            key_text = str(key)
            if key_text.lower() in _VOLATILE_PAYLOAD_KEYS:
                continue
            normalized[key_text] = _normalize_payload_for_signature(value[key])
        return normalized
    if isinstance(value, list):
        return [_normalize_payload_for_signature(item) for item in value]
    return value


def _build_coalesce_signature(row: dict[str, Any]) -> str:
    fingerprint_payload = {
        "service": row["service"],
        "component": row["component"],
        "event": row["event"],
        "severity": row["severity"],
        "status_code": row["status_code"],
        "message": row["message"],
        "source_file": row["source_file"],
        "payload": _normalize_payload_for_signature(row["payload"]),
    }
    serialized = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return sha1(serialized.encode("utf-8")).hexdigest()


def _trim_coalesce_state(now_monotonic: float) -> None:
    stale_before = now_monotonic - _COALESCE_STALE_SECONDS
    stale_keys = [key for key, data in _COALESCE_STATE.items() if float(data.get("last_seen", 0.0)) < stale_before]
    for key in stale_keys:
        _COALESCE_STATE.pop(key, None)

    if len(_COALESCE_STATE) <= _COALESCE_MAX_KEYS:
        return

    sorted_items = sorted(_COALESCE_STATE.items(), key=lambda item: float(item[1].get("last_seen", 0.0)))
    drop_count = len(_COALESCE_STATE) - _COALESCE_MAX_KEYS
    for key, _ in sorted_items[:drop_count]:
        _COALESCE_STATE.pop(key, None)


def _should_write_with_coalesce(row: dict[str, Any]) -> tuple[bool, int]:
    default_window = float(_COALESCE_WINDOWS_SECONDS.get(row["severity"], 0.0))
    specific_window = float(
        _COALESCE_EVENT_WINDOWS_SECONDS.get(
            (row["service"], row["component"], row["event"]),
            0.0,
        )
    )
    window_seconds = max(default_window, specific_window)
    if window_seconds <= 0.0:
        return True, 0

    signature = _build_coalesce_signature(row)
    now_monotonic = time.monotonic()

    with _COALESCE_LOCK:
        entry = _COALESCE_STATE.get(signature)
        if entry is None:
            _COALESCE_STATE[signature] = {
                "last_logged": now_monotonic,
                "last_seen": now_monotonic,
                "suppressed": 0.0,
            }
            if len(_COALESCE_STATE) > _COALESCE_MAX_KEYS:
                _trim_coalesce_state(now_monotonic)
            return True, 0

        entry["last_seen"] = now_monotonic
        if now_monotonic - float(entry.get("last_logged", 0.0)) < window_seconds:
            entry["suppressed"] = float(entry.get("suppressed", 0.0)) + 1.0
            return False, 0

        suppressed_count = int(entry.get("suppressed", 0.0))
        entry["suppressed"] = 0.0
        entry["last_logged"] = now_monotonic
        if len(_COALESCE_STATE) > _COALESCE_MAX_KEYS:
            _trim_coalesce_state(now_monotonic)
        return True, suppressed_count


def build_db_config(dbname: str) -> dict[str, Any]:
    config = get_postgres_config().copy()
    config["dbname"] = dbname
    if DB_APP_NAME:
        config["application_name"] = f"{DB_APP_NAME}-systemlog"
    else:
        config["application_name"] = "systemlog"
    return config


def get_systemlog_db_config() -> dict[str, Any]:
    return build_db_config(get_postgres_config()["dbname"])


def ensure_database_ready() -> bool:
    global _READY
    global _DISABLED_UNTIL

    if not SYSTEMLOG_ENABLED:
        return False
    if _READY:
        return True
    if time.monotonic() < _DISABLED_UNTIL:
        return False

    with _INIT_LOCK:
        if _READY:
            return True
        if time.monotonic() < _DISABLED_UNTIL:
            return False

        try:
            initialize_systemlog_table()
            _READY = True
            return True
        except Exception:
            _DISABLED_UNTIL = time.monotonic() + 30.0
            return False


def initialize_systemlog_table() -> None:
    conn = psycopg2.connect(**get_systemlog_db_config())
    try:
        conn.autocommit = True
        ensure_table_exists(conn)
    finally:
        conn.close()


def initialize_systemlog_database() -> None:
    initialize_systemlog_table()


def ensure_table_exists(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS public.{table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    service VARCHAR(100) NOT NULL,
                    component VARCHAR(150) NOT NULL DEFAULT '',
                    event VARCHAR(150) NOT NULL,
                    severity VARCHAR(16) NOT NULL,
                    severity_rank SMALLINT NOT NULL,
                    status_code INTEGER NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    source_file TEXT NOT NULL DEFAULT '',
                    hostname VARCHAR(255) NOT NULL DEFAULT '',
                    process_id INTEGER NOT NULL DEFAULT 0,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            ).format(table_name=sql.Identifier(SYSTEMLOG_TABLE))
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {index_name} ON public.{table_name} (created_at DESC)"
            ).format(
                index_name=sql.Identifier(f"{SYSTEMLOG_TABLE}_created_at_idx"),
                table_name=sql.Identifier(SYSTEMLOG_TABLE),
            )
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {index_name} ON public.{table_name} (service, event)"
            ).format(
                index_name=sql.Identifier(f"{SYSTEMLOG_TABLE}_service_event_idx"),
                table_name=sql.Identifier(SYSTEMLOG_TABLE),
            )
        )


def write_event(
    *,
    service: str,
    event: str,
    payload: Optional[dict[str, Any]] = None,
    component: str = "",
    source_file: str = "",
    severity: Optional[str] = None,
    status_code: Optional[int] = None,
    message: str = "",
) -> bool:
    if not ensure_database_ready():
        return False

    payload_data = dict(payload or {})
    severity_name = normalize_severity(severity or payload_data.get("severity") or infer_severity(event))
    status_value = _parse_int_status(status_code)
    if status_value is None:
        status_value = _parse_int_status(payload_data.get("status_code"))
    if status_value is None:
        status_value = get_mapped_status_code(service, component, event, payload_data)
    if status_value is None:
        status_value = infer_status_code(event, severity_name, payload_data)

    if not message:
        payload_message = payload_data.get("message")
        if payload_message is not None:
            message = str(payload_message)

    row = {
        "service": str(service or "").strip() or "python",
        "component": str(component or "").strip(),
        "event": str(event or "").strip() or "event",
        "severity": severity_name,
        "severity_rank": SEVERITY_RANKS[severity_name],
        "status_code": int(status_value),
        "message": str(message or ""),
        "source_file": str(source_file or ""),
        "hostname": _HOSTNAME,
        "process_id": os.getpid(),
        "payload": payload_data,
    }

    should_write, suppressed_count = _should_write_with_coalesce(row)
    if not should_write:
        return True
    if suppressed_count > 0:
        row["payload"] = dict(row["payload"])
        row["payload"]["suppressed_duplicates"] = suppressed_count

    try:
        with psycopg2.connect(**get_systemlog_db_config()) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO public.{table_name}
                        (service, component, event, severity, severity_rank, status_code, message, source_file, hostname, process_id, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(table_name=sql.Identifier(SYSTEMLOG_TABLE)),
                    (
                        row["service"],
                        row["component"],
                        row["event"],
                        row["severity"],
                        row["severity_rank"],
                        row["status_code"],
                        row["message"],
                        row["source_file"],
                        row["hostname"],
                        row["process_id"],
                        Json(row["payload"], dumps=json_dumps_default),
                    ),
                )
        return True
    except Exception:
        return False


def build_cli_payload(argv: list[str]) -> dict[str, Any]:
    return {
        "argv": argv,
        "timestamp_utc": utc_now_iso(),
    }


def write_db_event(
    *,
    service: str,
    component: str,
    action: str,
    table_name: str,
    row_count: int = 0,
    payload: Optional[dict[str, Any]] = None,
    source_file: str = "",
    status_code: Optional[int] = None,
    severity: Optional[str] = None,
    message: str = "",
) -> bool:
    event_payload = dict(payload or {})
    event_payload.update(
        {
            "table_name": table_name,
            "row_count": int(row_count),
        }
    )
    return write_event(
        service=service,
        component=component,
        event=f"db_{action}",
        payload=event_payload,
        source_file=source_file,
        status_code=status_code,
        severity=severity,
        message=message,
    )


def safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)
