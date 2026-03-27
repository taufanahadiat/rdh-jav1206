#!/usr/bin/env python3
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg2
import snap7
from snap7.util import get_bool

import DB2_General as db2


PLC_IP = os.getenv("PLC_IP", db2.PLC_IP)
RACK = int(os.getenv("PLC_RACK", str(db2.RACK)))
SLOT = int(os.getenv("PLC_SLOT", str(db2.SLOT)))

DB330_NUM = 330
DB330_STATUS_BYTE = 3022
DB330_START_BIT = 0
DB330_AUX_BIT = 1
MARKER_STATUS_BYTE = 2
MARKER_FIRST_CYCLE_BIT = 0

SCL_SOURCE_PATH = Path(os.getenv("PLC_FLUCT_SCL_PATH", "/var/www/Cyclic interrupt.scl"))
PLC_API_SNAPSHOT_URL = os.getenv(
    "PLC_API_SNAPSHOT_URL",
    "http://127.0.0.1:8000/plc/dashboard-snapshot",
)
PLC_API_TIMEOUT_SECONDS = max(float(os.getenv("PLC_API_TIMEOUT_SECONDS", "5")), 1.0)

DEFAULT_INTERVAL_MS = 50
DEFAULT_EVENT_HOLDOFF_MS = 100
DOWNTIME_ROLLNAME = "Server Shutdown"

FUNCTION_BODY_RE = r'(FUNCTION(?:_BLOCK)?\s+"{name}".*?BEGIN)(?P<body>.*?)(END_FUNCTION(?:_BLOCK)?)'
MASTER_NAME = "FC_Fluct_Master"
EXTRA_FLUCTUATION_FUNCTIONS = ["FC_Fluct_DB330_Win"]
MASTER_CALL_RE = re.compile(r'"(?P<name>FC_Fluct_[^"]+)"\s*\(')
SYMBOL_TOKEN_RE = re.compile(r'"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*)|(\[[0-9]+\])')

_should_stop = False


def log_event(event: str, **payload: Any) -> None:
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
    }
    data.update(payload)
    print(json.dumps(data, ensure_ascii=False), flush=True)


def handle_signal(signum: int, _frame: Any) -> None:
    global _should_stop
    _should_stop = True
    log_event("signal", signal=signum, message="Stopping listener")


def db_config() -> dict[str, Any]:
    return {
        "host": os.getenv("PGHOST") or "127.0.0.1",
        "port": int(os.getenv("PGPORT") or "5432"),
        "dbname": os.getenv("PGDATABASE") or "jav1206",
        "user": os.getenv("PGUSER") or "jav1206",
        "password": os.getenv("PGPASSWORD") or "akpidev3",
    }


def connect_plc() -> snap7.client.Client:
    plc = snap7.client.Client()
    plc.connect(PLC_IP, RACK, SLOT)
    if not plc.get_connected():
        raise RuntimeError("Failed to connect to PLC")
    return plc


def connect_db():
    conn = psycopg2.connect(**db_config())
    conn.autocommit = False
    return conn


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def build_rollname(now: datetime) -> str:
    return now.strftime("A %y%m%d %H%M")


def read_product_state(plc: snap7.client.Client) -> dict[str, Any]:
    payload = db2.build_payload(plc)

    return {
        "product": normalize_text(payload.get("product")),
        "recipe": normalize_text(payload.get("recipe")),
        "campaign": normalize_text(payload.get("campaign")),
        "status": int(payload.get("status") or 0),
    }


def read_status_bits(plc: snap7.client.Client) -> dict[str, bool]:
    status_buf = plc.db_read(DB330_NUM, DB330_STATUS_BYTE, 1)
    marker_buf = plc.mb_read(MARKER_STATUS_BYTE, 1)

    return {
        "start_bit": bool(get_bool(status_buf, 0, DB330_START_BIT)),
        "aux_bit": bool(get_bool(status_buf, 0, DB330_AUX_BIT)),
        "first_cycle_bit": bool(get_bool(marker_buf, 0, MARKER_FIRST_CYCLE_BIT)),
    }


def write_helper_row(conn, state: dict[str, Any], started_at: datetime) -> None:
    with conn.cursor() as cur:
        # Keep helper as the single source of truth for the active roll.
        cur.execute("DELETE FROM public.helper")
        cur.execute(
            """
            INSERT INTO public.helper (rollname, product, recipe, campaign, starttime, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                build_rollname(started_at),
                state["product"],
                state["recipe"],
                state["campaign"],
                started_at.strftime("%Y-%m-%d %H:%M:%S"),
                state["status"],
            ),
        )


def update_helper_fields(conn, state: dict[str, Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_helper AS (
                SELECT ctid
                FROM public.helper
                ORDER BY starttime DESC NULLS LAST, ctid DESC
                LIMIT 1
            )
            UPDATE public.helper AS helper
            SET product = %s,
                recipe = %s,
                campaign = %s,
                status = %s
            FROM latest_helper
            WHERE helper.ctid = latest_helper.ctid
            """,
            (
                state["product"],
                state["recipe"],
                state["campaign"],
                state["status"],
            ),
        )
        return cur.rowcount


def fetch_helper_row(conn) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rollname, product, recipe, campaign, starttime, status
            FROM public.helper
            ORDER BY starttime DESC NULLS LAST, ctid DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {
        "rollname": normalize_text(row[0]),
        "product": normalize_text(row[1]),
        "recipe": normalize_text(row[2]),
        "campaign": normalize_text(row[3]),
        "starttime": row[4],
        "status": int(row[5]) if row[5] is not None else None,
    }


def get_system_boot_time() -> Optional[datetime]:
    try:
        uptime_text = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        uptime_seconds = max(float(uptime_text), 0.0)
    except (OSError, ValueError, IndexError):
        return None

    return datetime.now() - timedelta(seconds=uptime_seconds)


def fetch_latest_rolldata_row(conn) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, rollname, product, recipe, campaign, starttime, endtime, status
            FROM public.rolldata
            ORDER BY endtime DESC NULLS LAST, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": int(row[0]),
        "rollname": normalize_text(row[1]),
        "product": normalize_text(row[2]),
        "recipe": normalize_text(row[3]),
        "campaign": normalize_text(row[4]),
        "starttime": row[5],
        "endtime": row[6],
        "status": int(row[7]) if row[7] is not None else None,
    }


def build_startup_gap_row(
    helper_row: Optional[dict[str, Any]],
    latest_roll_row: dict[str, Any],
    started_at: datetime,
) -> dict[str, Any]:
    metadata_source = helper_row or latest_roll_row
    return {
        "rollname": DOWNTIME_ROLLNAME,
        "product": normalize_text(metadata_source.get("product")),
        "recipe": normalize_text(metadata_source.get("recipe")),
        "campaign": normalize_text(metadata_source.get("campaign")),
        "starttime": started_at,
    }


def recover_startup_gap(conn, dry_run: bool) -> None:
    latest_roll_row = fetch_latest_rolldata_row(conn)
    if latest_roll_row is None:
        log_event("startup_gap_recovery_skipped", reason="rolldata_empty")
        return

    last_endtime = latest_roll_row["endtime"]
    if last_endtime is None:
        log_event(
            "startup_gap_recovery_skipped",
            reason="last_endtime_missing",
            rollid=latest_roll_row["id"],
        )
        return

    boot_time = get_system_boot_time()
    if boot_time is None:
        log_event("startup_gap_recovery_skipped", reason="boot_time_unavailable")
        return

    if last_endtime >= boot_time:
        log_event(
            "startup_gap_recovery_skipped",
            reason="server_not_restarted_since_last_roll",
            last_endtime=last_endtime.strftime("%Y-%m-%d %H:%M:%S"),
            boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return

    recovered_until = datetime.now()
    if recovered_until <= last_endtime:
        log_event(
            "startup_gap_recovery_skipped",
            reason="invalid_recovery_window",
            last_endtime=last_endtime.strftime("%Y-%m-%d %H:%M:%S"),
            recovered_until=recovered_until.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return

    helper_row = fetch_helper_row(conn)
    recovery_row = build_startup_gap_row(helper_row, latest_roll_row, last_endtime)

    if dry_run:
        log_event(
            "startup_gap_recovery_dry_run",
            rollname=recovery_row["rollname"],
            product=recovery_row["product"],
            recipe=recovery_row["recipe"],
            campaign=recovery_row["campaign"],
            starttime=last_endtime.strftime("%Y-%m-%d %H:%M:%S"),
            endtime=recovered_until.strftime("%Y-%m-%d %H:%M:%S"),
            status=0,
            boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return

    rollid = insert_rolldata_row(conn, recovery_row, recovered_until, status=0)
    conn.commit()
    log_event(
        "startup_gap_recovered",
        rollid=rollid,
        rollname=recovery_row["rollname"],
        product=recovery_row["product"],
        recipe=recovery_row["recipe"],
        campaign=recovery_row["campaign"],
        starttime=last_endtime.strftime("%Y-%m-%d %H:%M:%S"),
        endtime=recovered_until.strftime("%Y-%m-%d %H:%M:%S"),
        status=0,
        boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
    )


def insert_rolldata_row(conn, helper_row: dict[str, Any], ended_at: datetime, status: int = 1) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.rolldata (rollname, product, recipe, campaign, starttime, endtime, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                helper_row["rollname"],
                helper_row["product"],
                helper_row["recipe"],
                helper_row["campaign"],
                helper_row["starttime"],
                ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                status,
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to read new rolldata id.")
    return int(row[0])


def extract_function_body(scl_text: str, function_name: str) -> str:
    match = re.search(FUNCTION_BODY_RE.format(name=re.escape(function_name)), scl_text, re.S)
    if match is None:
        raise RuntimeError(f"Function body not found in SCL: {function_name}")
    return match.group("body")


def extract_active_fluctuation_functions(scl_text: str) -> list[str]:
    master_body = extract_function_body(scl_text, MASTER_NAME)
    function_names: list[str] = []

    for line in master_body.splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("//"):
            continue

        match = MASTER_CALL_RE.search(stripped)
        if match is None:
            continue

        function_name = match.group("name")
        if function_name == MASTER_NAME or function_name in function_names:
            continue
        function_names.append(function_name)

    if not function_names:
        raise RuntimeError("No active FC_Fluct functions found in FC_Fluct_Master.")

    for function_name in EXTRA_FLUCTUATION_FUNCTIONS:
        try:
            extract_function_body(scl_text, function_name)
        except RuntimeError:
            continue
        if function_name not in function_names:
            function_names.append(function_name)

    return function_names


def normalize_symbolic_name(lhs: str) -> str:
    parts: list[str] = []

    for token in SYMBOL_TOKEN_RE.finditer(lhs):
        quoted = token.group(1)
        bare = token.group(2)
        index_token = token.group(3)

        if quoted is not None:
            if quoted.isdigit():
                return ""
            parts.append(quoted)
            continue

        if bare is not None:
            parts.append(bare)
            continue

        if index_token is not None and parts:
            index_value = int(index_token[1:-1])
            parts[-1] = f"{parts[-1]}[{index_value}]"

    return ".".join(parts)


def extract_fluctuation_symbolic_names(scl_text: str, function_names: list[str]) -> list[str]:
    symbolic_names: list[str] = []

    for function_name in function_names:
        body = extract_function_body(scl_text, function_name)
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith('"') or ":=" not in stripped:
                continue

            lhs = stripped.split(":=", 1)[0].strip()
            normalized = normalize_symbolic_name(lhs)
            if normalized == "" or normalized in symbolic_names:
                continue
            symbolic_names.append(normalized)

    return symbolic_names


def load_rtagroll_catalog(conn) -> dict[str, Any]:
    scl_text = SCL_SOURCE_PATH.read_text(encoding="utf-8", errors="ignore")
    function_names = extract_active_fluctuation_functions(scl_text)
    symbolic_names = extract_fluctuation_symbolic_names(scl_text, function_names)
    if not symbolic_names:
        raise RuntimeError("No fluctuation symbolic tags were extracted from SCL source.")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, address, name, type
            FROM public.dblist
            WHERE name = ANY(%s)
            ORDER BY id
            """,
            (symbolic_names,),
        )
        rows = cur.fetchall()

    entries: list[dict[str, Any]] = []
    found_names: set[str] = set()
    for row in rows:
        dbid = int(row[0])
        address = normalize_text(row[1])
        name = normalize_text(row[2])
        value_type = normalize_text(row[3])
        if address == "" or name == "":
            continue
        entries.append(
            {
                "dbid": dbid,
                "address": address,
                "name": name,
                "type": value_type,
            }
        )
        found_names.add(name)

    missing_names = [name for name in symbolic_names if name not in found_names]
    db_numbers = sorted({int(entry["address"].split(".", 1)[0][2:]) for entry in entries})

    return {
        "entries": entries,
        "missing_names": missing_names,
        "function_names": function_names,
        "symbolic_names": symbolic_names,
        "db_numbers": db_numbers,
    }


def fetch_plc_tag_values(addresses: list[str]) -> dict[str, Any]:
    payload = json.dumps(
        {
            "tags": addresses,
            "direct_read_missing": True,
        }
    ).encode("utf-8")

    request = Request(
        PLC_API_SNAPSHOT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=PLC_API_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"PLC API HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to reach PLC API: {exc.reason}") from exc

    data = json.loads(body)
    if not data.get("ok", False):
        raise RuntimeError(f"PLC API returned an invalid snapshot payload: {body[:200]}")
    return data


def coerce_rtagroll_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None

    text = str(value).strip()
    if text == "":
        return None

    try:
        numeric = float(text)
    except ValueError:
        return None

    return numeric if math.isfinite(numeric) else None


def insert_rtagroll_rows(conn, rollid: int, catalog_entries: list[dict[str, Any]], tag_values: dict[str, Any], event_time: datetime) -> dict[str, Any]:
    rows_to_insert: list[tuple[int, int, float, str]] = []
    missing_addresses: list[str] = []
    skipped_values: list[dict[str, Any]] = []

    for entry in catalog_entries:
        address = entry["address"]
        if address not in tag_values:
            missing_addresses.append(address)
            continue

        numeric_value = coerce_rtagroll_value(tag_values[address])
        if numeric_value is None:
            skipped_values.append(
                {
                    "address": address,
                    "name": entry["name"],
                    "value": tag_values[address],
                }
            )
            continue

        rows_to_insert.append(
            (
                rollid,
                entry["dbid"],
                numeric_value,
                event_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    if not rows_to_insert:
        raise RuntimeError("No numeric PLC values were available for rtagroll insert.")

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.rtagroll (rollid, dbid, value, timestamp)
            VALUES (%s, %s, %s, %s)
            """,
            rows_to_insert,
        )

    return {
        "inserted_count": len(rows_to_insert),
        "missing_addresses": missing_addresses,
        "skipped_values": skipped_values,
    }


def run_listener(interval_ms: int, event_holdoff_ms: int, once: bool, dry_run: bool, verbose: bool) -> int:
    plc: Optional[snap7.client.Client] = None
    conn = None
    rtagroll_catalog: Optional[dict[str, Any]] = None
    last_start_bit = False
    last_aux_bit: Optional[bool] = None
    last_first_cycle_bit: Optional[bool] = None
    last_product_state: Optional[tuple[str, str, str, int]] = None
    last_helper_event_monotonic = 0.0
    last_rolldata_event_monotonic = 0.0
    pending_rolldata_event_time: Optional[datetime] = None
    pending_rolldata_helper_row: Optional[dict[str, Any]] = None
    pending_rolldata_event_monotonic = 0.0
    startup_gap_checked = False
    holdoff_seconds = max(event_holdoff_ms, 0) / 1000

    while not _should_stop:
        try:
            if plc is None or not plc.get_connected():
                plc = connect_plc()
                last_start_bit = False
                last_aux_bit = None
                last_first_cycle_bit = None
                last_product_state = None
                last_helper_event_monotonic = 0.0
                last_rolldata_event_monotonic = 0.0
                pending_rolldata_event_time = None
                pending_rolldata_helper_row = None
                pending_rolldata_event_monotonic = 0.0
                log_event("plc_connected", plc_ip=PLC_IP, rack=RACK, slot=SLOT)

            if conn is None or conn.closed:
                conn = connect_db()
                log_event("db_connected", database=db_config()["dbname"], user=db_config()["user"])
                rtagroll_catalog = None
                if not startup_gap_checked:
                    recover_startup_gap(conn, dry_run=dry_run)
                    startup_gap_checked = True

            if rtagroll_catalog is None:
                rtagroll_catalog = load_rtagroll_catalog(conn)
                log_event(
                    "rtagroll_catalog_loaded",
                    scl_source=str(SCL_SOURCE_PATH),
                    function_count=len(rtagroll_catalog["function_names"]),
                    function_names=rtagroll_catalog["function_names"],
                    db_numbers=rtagroll_catalog["db_numbers"],
                    mapped_tags=len(rtagroll_catalog["entries"]),
                    missing_tags=len(rtagroll_catalog["missing_names"]),
                )
                if rtagroll_catalog["missing_names"]:
                    log_event(
                        "rtagroll_catalog_missing_tags",
                        count=len(rtagroll_catalog["missing_names"]),
                        names=rtagroll_catalog["missing_names"][:20],
                    )

            product_state = read_product_state(plc)
            state = read_status_bits(plc)
            product_snapshot = (
                product_state["product"],
                product_state["recipe"],
                product_state["campaign"],
                product_state["status"],
            )

            start_rising = state["start_bit"] and not last_start_bit
            aux_changed = last_aux_bit is None or state["aux_bit"] != last_aux_bit
            aux_rising = state["aux_bit"] and not bool(last_aux_bit)
            first_cycle_changed = last_first_cycle_bit is None or state["first_cycle_bit"] != last_first_cycle_bit
            first_cycle_rising = state["first_cycle_bit"] and not bool(last_first_cycle_bit)
            product_changed = last_product_state is not None and product_snapshot != last_product_state

            if verbose or aux_changed or first_cycle_changed:
                log_event(
                    "bit_state",
                    db330_dbx3022_0=state["start_bit"],
                    db330_dbx3022_1=state["aux_bit"],
                    m2_0=state["first_cycle_bit"],
                )

            if product_changed:
                if dry_run:
                    log_event(
                        "helper_fields_update_dry_run",
                        product=product_state["product"],
                        recipe=product_state["recipe"],
                        campaign=product_state["campaign"],
                        status=product_state["status"],
                    )
                else:
                    updated_rows = update_helper_fields(conn, product_state)
                    conn.commit()
                    if updated_rows > 0:
                        log_event(
                            "helper_fields_updated",
                            product=product_state["product"],
                            recipe=product_state["recipe"],
                            campaign=product_state["campaign"],
                            status=product_state["status"],
                        )
                    elif verbose:
                        log_event(
                            "helper_fields_skipped_no_row",
                            product=product_state["product"],
                            recipe=product_state["recipe"],
                            campaign=product_state["campaign"],
                            status=product_state["status"],
                        )

            if aux_rising:
                current_monotonic = time.monotonic()
                if current_monotonic - last_rolldata_event_monotonic < holdoff_seconds:
                    if verbose:
                        log_event(
                            "event_skipped_holdoff",
                            trigger="db330.dbx3022.1",
                            holdoff_ms=event_holdoff_ms,
                        )
                else:
                    pending_rolldata_event_time = datetime.now()
                    pending_rolldata_helper_row = fetch_helper_row(conn)
                    pending_rolldata_event_monotonic = current_monotonic
                    if verbose:
                        log_event(
                            "rolldata_pending",
                            trigger="db330.dbx3022.1",
                            holdoff_ms=event_holdoff_ms,
                            eventtime=pending_rolldata_event_time.strftime("%Y-%m-%d %H:%M:%S"),
                        )

            helper_trigger = ""
            if start_rising:
                helper_trigger = "db330.dbx3022.0"
            elif first_cycle_rising:
                helper_trigger = "m2.0"

            if helper_trigger != "":
                current_monotonic = time.monotonic()
                if current_monotonic - last_helper_event_monotonic < holdoff_seconds:
                    if verbose:
                        log_event(
                            "event_skipped_holdoff",
                            trigger=helper_trigger,
                            holdoff_ms=event_holdoff_ms,
                        )
                else:
                    started_at = datetime.now()
                    rollname = build_rollname(started_at)
                    if dry_run:
                        log_event(
                            "helper_save_dry_run",
                            rollname=rollname,
                            trigger=helper_trigger,
                            product=product_state["product"],
                            recipe=product_state["recipe"],
                            campaign=product_state["campaign"],
                            status=product_state["status"],
                            starttime=started_at.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        write_helper_row(conn, product_state, started_at)
                        conn.commit()
                        product_snapshot = (
                            product_state["product"],
                            product_state["recipe"],
                            product_state["campaign"],
                            product_state["status"],
                        )
                        log_event(
                            "helper_saved",
                            rollname=rollname,
                            trigger=helper_trigger,
                            product=product_state["product"],
                            recipe=product_state["recipe"],
                            campaign=product_state["campaign"],
                            status=product_state["status"],
                            starttime=started_at.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    last_helper_event_monotonic = current_monotonic

            if (
                pending_rolldata_event_time is not None
                and time.monotonic() - pending_rolldata_event_monotonic >= holdoff_seconds
            ):
                helper_row = pending_rolldata_helper_row
                if helper_row is None:
                    log_event(
                        "rolldata_skipped_no_helper",
                        trigger="db330.dbx3022.1",
                        message="Helper table is empty.",
                    )
                elif helper_row["rollname"] == "" or helper_row["starttime"] is None:
                    log_event(
                        "rolldata_skipped_invalid_helper",
                        trigger="db330.dbx3022.1",
                        helper_row=helper_row,
                    )
                else:
                    ended_at = pending_rolldata_event_time
                    if dry_run:
                        rtagroll_result = {
                            "inserted_count": len(rtagroll_catalog["entries"]) if rtagroll_catalog is not None else 0,
                            "missing_addresses": [],
                            "skipped_values": [],
                        }
                        log_event(
                            "rolldata_insert_dry_run",
                            trigger="db330.dbx3022.1",
                            rollname=helper_row["rollname"],
                            product=helper_row["product"],
                            recipe=helper_row["recipe"],
                            campaign=helper_row["campaign"],
                            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                            endtime=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                            rtagroll_count=rtagroll_result["inserted_count"],
                        )
                    else:
                        if rtagroll_catalog is None or not rtagroll_catalog["entries"]:
                            raise RuntimeError("rtagroll catalog is empty.")

                        snapshot_payload = fetch_plc_tag_values(
                            [entry["address"] for entry in rtagroll_catalog["entries"]]
                        )
                        with conn:
                            rollid = insert_rolldata_row(conn, helper_row, ended_at)
                            rtagroll_result = insert_rtagroll_rows(
                                conn,
                                rollid,
                                rtagroll_catalog["entries"],
                                snapshot_payload.get("tag_values", {}),
                                ended_at,
                            )
                        log_event(
                            "rolldata_inserted",
                            trigger="db330.dbx3022.1",
                            rollid=rollid,
                            rollname=helper_row["rollname"],
                            product=helper_row["product"],
                            recipe=helper_row["recipe"],
                            campaign=helper_row["campaign"],
                            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                            endtime=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                            rtagroll_count=rtagroll_result["inserted_count"],
                            rtagroll_missing_count=len(rtagroll_result["missing_addresses"]),
                            rtagroll_skipped_value_count=len(rtagroll_result["skipped_values"]),
                        )
                        if rtagroll_result["missing_addresses"] or rtagroll_result["skipped_values"]:
                            log_event(
                                "rtagroll_insert_partial",
                                rollid=rollid,
                                missing_addresses=rtagroll_result["missing_addresses"][:20],
                                skipped_values=rtagroll_result["skipped_values"][:10],
                            )
                    last_rolldata_event_monotonic = pending_rolldata_event_monotonic

                pending_rolldata_event_time = None
                pending_rolldata_helper_row = None
                pending_rolldata_event_monotonic = 0.0

            last_product_state = product_snapshot
            last_start_bit = state["start_bit"]
            last_aux_bit = state["aux_bit"]
            last_first_cycle_bit = state["first_cycle_bit"]

            if once:
                break

            time.sleep(max(interval_ms, 10) / 1000)
        except KeyboardInterrupt:
            log_event("keyboard_interrupt", message="Stopping listener")
            break
        except Exception as exc:
            log_event("error", message=str(exc))
            if plc is not None:
                try:
                    if plc.get_connected():
                        plc.disconnect()
                except Exception:
                    pass
                plc = None

            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None

            if once:
                return 1

            time.sleep(2)
    if plc is not None:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Listen PLC runtime start event and save helper row to PostgreSQL."
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=DEFAULT_INTERVAL_MS,
        help="Polling interval in milliseconds. Default: 50",
    )
    parser.add_argument(
        "--event-holdoff-ms",
        type=int,
        default=DEFAULT_EVENT_HOLDOFF_MS,
        help="Minimum gap between saved events in milliseconds. Default: 100",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read once and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write to PostgreSQL.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print state changes for product/recipe/campaign, both DB330 bits, and M2.0.",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    return run_listener(
        interval_ms=args.interval_ms,
        event_holdoff_ms=args.event_holdoff_ms,
        once=args.once,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
