import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    API_SNAPSHOT_URL,
    API_TIMEOUT_SECONDS,
    HISTORIAN_DB_WINDER_AUX_BIT,
    HISTORIAN_DB_WINDER_NUM,
    HISTORIAN_DB_WINDER_START_BIT,
    HISTORIAN_DB_WINDER_STATUS_BYTE,
    HISTORIAN_DOWNTIME_ROLLNAME,
    HISTORIAN_EVENT_HOLDOFF_MS,
    HISTORIAN_INTERVAL_MS,
    HISTORIAN_MARKER_FIRST_CYCLE_BIT,
    HISTORIAN_MARKER_STATUS_BYTE,
    PLC_FLUCT_CATALOG_PATH,
    PLC_IP,
    PLC_RACK,
    PLC_SLOT,
    get_postgres_config,
)


RACK = PLC_RACK
SLOT = PLC_SLOT

DB_WINDER_NUM = HISTORIAN_DB_WINDER_NUM
DB_WINDER_STATUS_BYTE = HISTORIAN_DB_WINDER_STATUS_BYTE
DB_WINDER_START_BIT = HISTORIAN_DB_WINDER_START_BIT
DB_WINDER_AUX_BIT = HISTORIAN_DB_WINDER_AUX_BIT
DB330_NUM = DB_WINDER_NUM
DB330_STATUS_BYTE = DB_WINDER_STATUS_BYTE
DB330_START_BIT = DB_WINDER_START_BIT
DB330_AUX_BIT = DB_WINDER_AUX_BIT
MARKER_STATUS_BYTE = HISTORIAN_MARKER_STATUS_BYTE
MARKER_FIRST_CYCLE_BIT = HISTORIAN_MARKER_FIRST_CYCLE_BIT

RTAGROLL_CATALOG_PATH = PLC_FLUCT_CATALOG_PATH
PLC_API_SNAPSHOT_URL = API_SNAPSHOT_URL
PLC_API_TIMEOUT_SECONDS = API_TIMEOUT_SECONDS

DEFAULT_INTERVAL_MS = HISTORIAN_INTERVAL_MS
DEFAULT_EVENT_HOLDOFF_MS = HISTORIAN_EVENT_HOLDOFF_MS
DOWNTIME_ROLLNAME = HISTORIAN_DOWNTIME_ROLLNAME
_STATUS_JSON_PATH = Path(__file__).resolve().parents[1] / "systemlog_status_codes.json"
_TIMELINE_REQUIRED_KEYS = (
    "plc_not_reach_rollname",
    "timeline_normal_status",
    "server_shutdown_status",
    "plc_not_reach_status",
    "precondition_failed_suffix",
    "precondition_failed_status",
    "postcondition_failed_suffix",
    "postcondition_failed_status",
)


def _load_timeline_status_config() -> dict[str, Any]:
    try:
        raw = json.loads(_STATUS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read timeline status config JSON: {_STATUS_JSON_PATH}") from exc

    section = raw.get("historian_timeline")
    if not isinstance(section, dict):
        raise RuntimeError(
            f"Missing or invalid 'historian_timeline' section in {_STATUS_JSON_PATH}"
        )

    missing_keys = [key for key in _TIMELINE_REQUIRED_KEYS if key not in section]
    if missing_keys:
        raise RuntimeError(
            f"Missing historian_timeline keys in {_STATUS_JSON_PATH}: {', '.join(missing_keys)}"
        )

    return section


def _coerce_int(value: Any, key_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid integer value for historian_timeline.{key_name} in {_STATUS_JSON_PATH}"
        ) from exc


_TIMELINE_STATUS_CONFIG = _load_timeline_status_config()
PLC_NOT_REACH_ROLLNAME = str(_TIMELINE_STATUS_CONFIG["plc_not_reach_rollname"])
TIMELINE_NORMAL_STATUS = _coerce_int(_TIMELINE_STATUS_CONFIG["timeline_normal_status"], "timeline_normal_status")
SERVER_SHUTDOWN_STATUS = _coerce_int(_TIMELINE_STATUS_CONFIG["server_shutdown_status"], "server_shutdown_status")
PLC_NOT_REACH_STATUS = _coerce_int(_TIMELINE_STATUS_CONFIG["plc_not_reach_status"], "plc_not_reach_status")
PRECONDITION_FAILED_SUFFIX = str(_TIMELINE_STATUS_CONFIG["precondition_failed_suffix"])
PRECONDITION_FAILED_STATUS = _coerce_int(
    _TIMELINE_STATUS_CONFIG["precondition_failed_status"],
    "precondition_failed_status",
)
POSTCONDITION_FAILED_SUFFIX = str(_TIMELINE_STATUS_CONFIG["postcondition_failed_suffix"])
POSTCONDITION_FAILED_STATUS = _coerce_int(
    _TIMELINE_STATUS_CONFIG["postcondition_failed_status"],
    "postcondition_failed_status",
)


def db_config() -> dict[str, Any]:
    return get_postgres_config()


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def resolve_timeline_status(rollname: Any, default_status: int) -> int:
    normalized = normalize_text(rollname)
    normalized_lower = normalized.lower()
    if normalized_lower == normalize_text(DOWNTIME_ROLLNAME).lower():
        return SERVER_SHUTDOWN_STATUS
    if normalized_lower == normalize_text(PLC_NOT_REACH_ROLLNAME).lower():
        return PLC_NOT_REACH_STATUS
    if normalized.endswith(POSTCONDITION_FAILED_SUFFIX):
        return POSTCONDITION_FAILED_STATUS
    if normalized.endswith(PRECONDITION_FAILED_SUFFIX):
        return PRECONDITION_FAILED_STATUS
    return int(default_status)


def build_rollname(now: datetime) -> str:
    return now.strftime("A %y%m%d %H%M")
