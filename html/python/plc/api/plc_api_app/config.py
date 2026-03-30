import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import snap7

from config import (
    API_ALLOW_ORIGINS,
    PLC_AWL_DIR,
    PLC_DB_SCRIPT_DIR,
    PLC_IP,
    PLC_POLL_INTERVAL_MS,
    PLC_RACK,
    PLC_SLOT,
)


RACK = PLC_RACK
SLOT = PLC_SLOT
POLL_INTERVAL_MS = min(max(int(PLC_POLL_INTERVAL_MS), 250), 60000)
ALLOW_ORIGINS_RAW = API_ALLOW_ORIGINS

PYTHON_DIR = Path(__file__).resolve().parents[3]
DB_DIR = PLC_DB_SCRIPT_DIR
AWL_DIR = PLC_AWL_DIR
SCRIPT_RE = re.compile(r"^DB(?P<db>\d+)_(?P<name>.+)\.py$", re.IGNORECASE)
STRING_TAG_RE = re.compile(r"^DB(?P<db>\d+)\.DBB(?P<byte>\d+)\[(?P<len>\d+)\]$", re.IGNORECASE)
DIRECT_TAG_RE = re.compile(
    r"^DB(?P<db>\d+)\.(DBX|DBB|DBW|DBD|DBS)(?P<byte>\d+)(?:\.(?P<extra>\d+))?$",
    re.IGNORECASE,
)


def build_allow_origins(raw_value: str = ALLOW_ORIGINS_RAW) -> List[str]:
    origins = [item.strip() for item in raw_value.split(",") if item.strip() != ""]
    return origins or ["*"]


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
