from typing import Any, Dict, List

import snap7

from plc.db import DB2_General as db2
from plc.db.db_awl_reader import calc_struct_size, parse_awl_file, read_struct
from plc.api.plc_api_app.config import DB_DIR, AWL_DIR, PLC_IP, POLL_INTERVAL_MS, SCRIPT_RE, connect_plc, log_event, now_utc_iso
from plc.api.plc_api_app.models import PlcSource


def discover_sources() -> List[PlcSource]:
    sources: List[PlcSource] = []
    for script_path in sorted(DB_DIR.glob("DB*.py")):
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
                log_event(
                    "snapshot_source_error",
                    db=f"DB{source.db_num}",
                    source_file=source.source_file,
                    message=message,
                    severity="high",
                    status_code=320,
                )
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
