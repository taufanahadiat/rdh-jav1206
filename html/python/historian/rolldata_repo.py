import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from historian.config import HISTORIAN_DOWNTIME_ROLLNAME, normalize_text


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
        "rollname": HISTORIAN_DOWNTIME_ROLLNAME,
        "product": normalize_text(metadata_source.get("product")),
        "recipe": normalize_text(metadata_source.get("recipe")),
        "campaign": normalize_text(metadata_source.get("campaign")),
        "starttime": started_at,
    }


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


def recover_startup_gap(conn, dry_run: bool, log_event: Callable[..., None], fetch_helper_row: Callable[..., Optional[dict[str, Any]]]) -> None:
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
