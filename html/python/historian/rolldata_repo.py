import math
import re
import subprocess
from datetime import datetime
from typing import Any, Callable, Optional

from historian.config import (
    DOWNTIME_ROLLNAME,
    PLC_NOT_REACH_ROLLNAME,
    POSTCONDITION_FAILED_STATUS,
    POSTCONDITION_FAILED_SUFFIX,
    PRECONDITION_FAILED_STATUS,
    PRECONDITION_FAILED_SUFFIX,
    SERVER_SHUTDOWN_STATUS,
    TIMELINE_NORMAL_STATUS,
    normalize_text,
    resolve_timeline_status,
)
from systemlog import write_db_event, write_event as write_system_event

LAST_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")


def normalize_logged_time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is not None:
        return timestamp.astimezone().replace(tzinfo=None)
    return timestamp


def get_last_shutdown_window() -> Optional[tuple[datetime, datetime]]:
    try:
        result = subprocess.run(
            ["last", "-x", "--time-format", "iso"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        write_system_event(
            service="historian",
            component="rolldata_repo",
            event="shutdown_window_fetch_failed",
            payload={},
            source_file=__file__,
            severity="high",
            status_code=320,
        )
        return None

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("shutdown "):
            continue

        timestamps = LAST_ISO_RE.findall(line)
        if len(timestamps) < 2:
            continue

        shutdown_time = normalize_logged_time(timestamps[0])
        boot_time = normalize_logged_time(timestamps[1])
        write_system_event(
            service="historian",
            component="rolldata_repo",
            event="shutdown_window_detected",
            payload={
                "shutdown_time": shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
                "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            source_file=__file__,
            status_code=110,
        )
        return shutdown_time, boot_time

    return None


def normalize_base_rollname(rollname: str) -> str:
    normalized = normalize_text(rollname)
    changed = True
    while changed and normalized != "":
        changed = False
        for suffix in (PRECONDITION_FAILED_SUFFIX, POSTCONDITION_FAILED_SUFFIX):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].rstrip()
                changed = True
    return normalized


def build_postcondition_failed_rollname(rollname: str) -> str:
    normalized = normalize_base_rollname(rollname)
    if normalized == "":
        return POSTCONDITION_FAILED_SUFFIX.lstrip("_")
    return f"{normalized}{POSTCONDITION_FAILED_SUFFIX}"


def build_postcondition_failed_row(helper_row: dict[str, Any], started_at: datetime) -> dict[str, Any]:
    return {
        "rollname": build_postcondition_failed_rollname(helper_row.get("rollname", "")),
        "product": normalize_text(helper_row.get("product")),
        "recipe": normalize_text(helper_row.get("recipe")),
        "campaign": normalize_text(helper_row.get("campaign")),
        "starttime": started_at,
    }


def build_precondition_failed_rollname(rollname: str) -> str:
    normalized = normalize_base_rollname(rollname)
    if normalized == "":
        return PRECONDITION_FAILED_SUFFIX.lstrip("_")
    return f"{normalized}{PRECONDITION_FAILED_SUFFIX}"


def build_precondition_failed_row(
    rollname: str,
    product: str,
    recipe: str,
    campaign: str,
    started_at: datetime,
) -> dict[str, Any]:
    return {
        "rollname": build_precondition_failed_rollname(rollname),
        "product": normalize_text(product),
        "recipe": normalize_text(recipe),
        "campaign": normalize_text(campaign),
        "starttime": started_at,
        "status": PRECONDITION_FAILED_STATUS,
    }


def build_server_shutdown_row(started_at: datetime) -> dict[str, Any]:
    return {
        "rollname": normalize_text(DOWNTIME_ROLLNAME) or "Server Shutdown",
        "product": "",
        "recipe": "",
        "campaign": "",
        "starttime": started_at,
    }


def has_server_shutdown_timeline(conn, shutdown_time: datetime, boot_time: datetime) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM public.rolldata
            WHERE rollname = %s
              AND starttime = %s
              AND endtime = %s
            LIMIT 1
            """,
            (
                normalize_text(DOWNTIME_ROLLNAME) or "Server Shutdown",
                shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
                boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        return cur.fetchone() is not None


def find_postcondition_row_for_boot(conn, shutdown_time: datetime, boot_time: datetime) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, rollname, starttime, endtime
            FROM public.rolldata
            WHERE status = %s
              AND endtime = %s
              AND starttime <= %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                POSTCONDITION_FAILED_STATUS,
                boot_time.strftime("%Y-%m-%d %H:%M:%S"),
                shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": int(row[0]),
        "rollname": normalize_text(row[1]),
        "starttime": row[2],
        "endtime": row[3],
    }


def backfill_server_shutdown_timeline_if_needed(
    conn,
    dry_run: bool,
    log_event: Callable[..., None],
    shutdown_time: datetime,
    boot_time: datetime,
) -> bool:
    if has_server_shutdown_timeline(conn, shutdown_time, boot_time):
        return False

    postcondition_row = find_postcondition_row_for_boot(conn, shutdown_time, boot_time)
    if postcondition_row is None:
        return False

    shutdown_row = build_server_shutdown_row(shutdown_time)
    if dry_run:
        log_event(
            "server_shutdown_timeline_backfill_dry_run",
            based_on_postcondition_rollid=postcondition_row["id"],
            rollname=shutdown_row["rollname"],
            product="",
            recipe="",
            campaign="",
            starttime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
            endtime=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=SERVER_SHUTDOWN_STATUS,
        )
        return True

    shutdown_rollid = insert_rolldata_row(
        conn,
        shutdown_row,
        boot_time,
        status=SERVER_SHUTDOWN_STATUS,
    )
    conn.commit()
    log_event(
        "server_shutdown_timeline_backfilled",
        based_on_postcondition_rollid=postcondition_row["id"],
        shutdown_rollid=shutdown_rollid,
        rollname=shutdown_row["rollname"],
        starttime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
        endtime=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        status=SERVER_SHUTDOWN_STATUS,
    )
    return True


def insert_rolldata_row(
    conn,
    helper_row: dict[str, Any],
    ended_at: datetime,
    status: int = TIMELINE_NORMAL_STATUS,
) -> int:
    resolved_status = resolve_timeline_status(helper_row.get("rollname", ""), status)
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
                resolved_status,
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to read new rolldata id.")
    rollid = int(row[0])
    write_db_event(
        service="historian",
        component="rolldata_repo",
        action="insert",
        table_name="public.rolldata",
        row_count=1,
        payload={
            "rollid": rollid,
            "rollname": helper_row["rollname"],
            "product": helper_row["product"],
            "recipe": helper_row["recipe"],
            "campaign": helper_row["campaign"],
            "starttime": helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(helper_row["starttime"], datetime)
            else str(helper_row["starttime"]),
            "endtime": ended_at.strftime("%Y-%m-%d %H:%M:%S"),
            "status": resolved_status,
        },
        source_file=__file__,
        status_code=resolved_status,
    )
    return rollid


def recover_startup_gap(
    conn,
    dry_run: bool,
    log_event: Callable[..., None],
    fetch_helper_row: Callable[..., Optional[dict[str, Any]]],
    clear_helper_row: Callable[..., int],
) -> Optional[str]:
    helper_row = fetch_helper_row(conn)
    if helper_row is None:
        log_event("server_shutdown_recovery_skipped", reason="helper_empty")
        return None

    if helper_row.get("rollname") in ("", None) or helper_row.get("starttime") is None:
        log_event(
            "server_shutdown_recovery_skipped",
            reason="helper_invalid",
            helper_row=helper_row,
        )
        return None

    shutdown_window = get_last_shutdown_window()
    if shutdown_window is None:
        log_event("server_shutdown_recovery_skipped", reason="shutdown_window_unavailable")
        return None

    shutdown_time, boot_time = shutdown_window
    if boot_time <= shutdown_time:
        log_event(
            "server_shutdown_recovery_skipped",
            reason="invalid_shutdown_window",
            shutdown_time=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
            boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return None

    if helper_row["starttime"] >= boot_time:
        if backfill_server_shutdown_timeline_if_needed(
            conn,
            dry_run,
            log_event,
            shutdown_time,
            boot_time,
        ):
            log_event(
                "server_shutdown_recovery_backfilled",
                reason="helper_started_after_boot",
                helper_starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return None
        log_event(
            "server_shutdown_recovery_skipped",
            reason="helper_started_after_boot",
            helper_starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
            boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return None

    helper_rollname = normalize_text(helper_row.get("rollname"))
    helper_rollname_lower = helper_rollname.lower()
    postcondition_needed = helper_rollname_lower not in {
        "",
        normalize_text(DOWNTIME_ROLLNAME).lower(),
        PLC_NOT_REACH_ROLLNAME.lower(),
    }
    base_rollname = normalize_base_rollname(helper_rollname) if postcondition_needed else ""
    postcondition_row = (
        build_postcondition_failed_row(helper_row, helper_row["starttime"])
        if postcondition_needed
        else None
    )
    shutdown_row = build_server_shutdown_row(shutdown_time)

    if dry_run:
        if postcondition_row is not None:
            log_event(
                "server_shutdown_postcondition_dry_run",
                rollname=postcondition_row["rollname"],
                product=postcondition_row["product"],
                recipe=postcondition_row["recipe"],
                campaign=postcondition_row["campaign"],
                starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                endtime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
                status=POSTCONDITION_FAILED_STATUS,
            )
        log_event(
            "server_shutdown_timeline_dry_run",
            rollname=shutdown_row["rollname"],
            product="",
            recipe="",
            campaign="",
            starttime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
            endtime=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=SERVER_SHUTDOWN_STATUS,
            boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return base_rollname or None

    postcondition_rollid = None
    if postcondition_row is not None:
        postcondition_rollid = insert_rolldata_row(
            conn,
            postcondition_row,
            shutdown_time,
            status=POSTCONDITION_FAILED_STATUS,
        )
    shutdown_rollid = insert_rolldata_row(
        conn,
        shutdown_row,
        boot_time,
        status=SERVER_SHUTDOWN_STATUS,
    )
    cleared_rows = clear_helper_row(conn)
    conn.commit()
    log_event(
        "server_shutdown_recovered",
        postcondition_rollid=postcondition_rollid,
        postcondition_rollname=postcondition_row["rollname"] if postcondition_row is not None else "",
        postcondition_starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S")
        if postcondition_row is not None
        else "",
        postcondition_endtime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
        postcondition_status=POSTCONDITION_FAILED_STATUS if postcondition_row is not None else None,
        shutdown_rollid=shutdown_rollid,
        shutdown_rollname=shutdown_row["rollname"],
        shutdown_starttime=shutdown_time.strftime("%Y-%m-%d %H:%M:%S"),
        shutdown_endtime=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        shutdown_status=SERVER_SHUTDOWN_STATUS,
        boot_time=boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        cleared_helper_rows=cleared_rows,
    )
    return base_rollname or None


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


def insert_rtagroll_rows(
    conn,
    rollid: int,
    catalog_entries: list[dict[str, Any]],
    tag_values: dict[str, Any],
    event_time: datetime,
) -> dict[str, Any]:
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
        inserted_rows = cur.rowcount

    write_db_event(
        service="historian",
        component="rolldata_repo",
        action="insert",
        table_name="public.rtagroll",
        row_count=inserted_rows,
        payload={
            "rollid": rollid,
            "event_time": event_time.strftime("%Y-%m-%d %H:%M:%S"),
            "missing_count": len(missing_addresses),
            "skipped_value_count": len(skipped_values),
        },
        source_file=__file__,
        status_code=130,
    )
    return {
        "inserted_count": len(rows_to_insert),
        "missing_addresses": missing_addresses,
        "skipped_values": skipped_values,
    }
