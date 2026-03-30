import re
from typing import Any, Dict, List, Optional, Tuple

from plc.db import DB2_General as db2

from plc.db.db_awl_reader import read_tag_direct
from plc.api.plc_api_app.config import DIRECT_TAG_RE, PLC_IP, STRING_TAG_RE, connect_plc, now_utc_iso


def normalize_tag(raw_tag: str) -> Tuple[str, int]:
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


def normalize_requested_tags(tags: List[str]) -> List[str]:
    normalized_tags: List[str] = []
    for raw_tag in tags:
        normalized, _db_num = normalize_tag(raw_tag)
        if normalized not in normalized_tags:
            normalized_tags.append(normalized)
    return normalized_tags


def collect_tag_values(snapshot: Dict[str, Any], tags: List[str]) -> Tuple[Dict[str, Any], List[str]]:
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
        requested: List[str] = []
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


def build_dashboard_snapshot(
    snapshot: Dict[str, Any],
    tag_list: Optional[List[str]],
    direct_read_missing: bool,
) -> Dict[str, Any]:
    requested_tags = tag_list or sorted(snapshot.get("tag_values", {}).keys())
    normalized_tags = normalize_requested_tags(requested_tags)

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
        "poll_interval_ms": snapshot.get("poll_interval_ms"),
        "source": source,
        "requested_tags": normalized_tags,
        "missing_tags": missing,
        "tag_values": tag_values,
        "errors": snapshot.get("errors", {}),
    }


def parse_dashboard_tag_list(raw_tags: Any) -> Optional[List[str]]:
    if isinstance(raw_tags, str):
        return [item.strip() for item in raw_tags.split(",") if item.strip() != ""]
    if isinstance(raw_tags, list):
        return [str(item).strip() for item in raw_tags if str(item).strip() != ""]
    return None
