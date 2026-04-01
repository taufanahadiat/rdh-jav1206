#!/usr/bin/env python3
import argparse
import json
import signal
import sys
import time
from datetime import datetime
from typing import Any, Optional

import psycopg2
import snap7

from systemlog import get_mapped_status_code, write_event as write_system_event
from historian.config import (
    HISTORIAN_EVENT_HOLDOFF_MS,
    HISTORIAN_INTERVAL_MS,
    PLC_NOT_REACH_ROLLNAME,
    PLC_NOT_REACH_STATUS,
    POSTCONDITION_FAILED_STATUS,
    PRECONDITION_FAILED_STATUS,
    PLC_IP,
    RACK,
    RTAGROLL_CATALOG_PATH,
    SLOT,
    TIMELINE_NORMAL_STATUS,
    build_rollname,
    db_config,
    resolve_timeline_status,
)
from historian.read_db import load_rtagroll_catalog
from historian.helper_repo import clear_helper_row, fetch_helper_row, replace_helper_row, update_helper_fields, write_helper_row
from historian.plc_client import connect_plc, fetch_plc_tag_values, read_product_state, read_status_bits
from historian.rolldata_repo import (
    build_precondition_failed_row,
    build_postcondition_failed_row,
    normalize_base_rollname,
    insert_rolldata_row,
    insert_rtagroll_rows,
    recover_startup_gap,
)


_should_stop = False
PLC_NOT_REACH_TIMEOUT_SECONDS = 60.0


def log_event(event: str, **payload: Any) -> None:
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
    }
    data.update(payload)
    print(json.dumps(data, ensure_ascii=False), flush=True)
    status_code = None
    raw_status_code = data.get("status_code")
    if raw_status_code is not None:
        try:
            status_code = int(raw_status_code)
        except (TypeError, ValueError):
            status_code = None
    elif "status" in data:
        try:
            status_code = int(data["status"])
        except (TypeError, ValueError):
            status_code = None
    if status_code is None:
        status_code = get_mapped_status_code("historian", "listener", event, data)
    write_system_event(
        service="historian",
        component="listener",
        event=event,
        payload=data,
        source_file=__file__,
        status_code=status_code,
    )


def handle_signal(signum: int, _frame: Any) -> None:
    global _should_stop
    _should_stop = True
    log_event("signal", signal=signum, message="Stopping listener")


def connect_db():
    conn = psycopg2.connect(**db_config())
    conn.autocommit = False
    return conn


def is_valid_helper_row(helper_row: Optional[dict[str, Any]]) -> bool:
    return bool(
        helper_row
        and helper_row.get("rollname")
        and helper_row.get("starttime") is not None
    )


def is_plc_unreachable_exception(exc: Exception) -> bool:
    if exc.__class__.__module__.startswith("snap7"):
        return True

    message = str(exc).lower()
    return (
        "unreachable peer" in message
        or "connection timed out" in message
        or "recv tcp" in message
        or "failed to connect to plc" in message
        or "failed to reach plc api" in message
    )


def is_production_on(product_state: dict[str, Any]) -> bool:
    try:
        return int(product_state.get("status") or 0) > 0
    except (TypeError, ValueError):
        return False


def handle_plc_not_reach_timeout(
    conn,
    dry_run: bool,
    event_time: datetime,
) -> Optional[str]:
    helper_row = fetch_helper_row(conn)
    helper_metadata = {
        "product": "",
        "recipe": "",
        "campaign": "",
    }
    if helper_row is not None:
        helper_metadata = {
            "product": helper_row.get("product", ""),
            "recipe": helper_row.get("recipe", ""),
            "campaign": helper_row.get("campaign", ""),
        }

    if not is_valid_helper_row(helper_row):
        log_event(
            "plc_not_reach_skipped_no_helper",
            message="Helper table is empty or invalid.",
        )
        if dry_run:
            log_event(
                "plc_not_reach_helper_dry_run",
                rollname=PLC_NOT_REACH_ROLLNAME,
                product=helper_metadata["product"],
                recipe=helper_metadata["recipe"],
                campaign=helper_metadata["campaign"],
                starttime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
                status=PLC_NOT_REACH_STATUS,
            )
            return None

        replace_helper_row(
            conn,
            PLC_NOT_REACH_ROLLNAME,
            helper_metadata["product"],
            helper_metadata["recipe"],
            helper_metadata["campaign"],
            event_time,
            PLC_NOT_REACH_STATUS,
        )
        conn.commit()
        log_event(
            "plc_not_reach_helper_saved",
            rollname=PLC_NOT_REACH_ROLLNAME,
            product=helper_metadata["product"],
            recipe=helper_metadata["recipe"],
            campaign=helper_metadata["campaign"],
            starttime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=PLC_NOT_REACH_STATUS,
        )
        return None

    base_rollname = normalize_base_rollname(helper_row["rollname"])
    recovery_row = build_postcondition_failed_row(helper_row, helper_row["starttime"])
    if dry_run:
        log_event(
            "plc_not_reach_postcondition_dry_run",
            rollname=recovery_row["rollname"],
            product=recovery_row["product"],
            recipe=recovery_row["recipe"],
            campaign=recovery_row["campaign"],
            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
            endtime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=POSTCONDITION_FAILED_STATUS,
        )
        log_event(
            "plc_not_reach_helper_dry_run",
            rollname=PLC_NOT_REACH_ROLLNAME,
            product=helper_metadata["product"],
            recipe=helper_metadata["recipe"],
            campaign=helper_metadata["campaign"],
            starttime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=PLC_NOT_REACH_STATUS,
        )
        return base_rollname

    rollid = insert_rolldata_row(
        conn,
        recovery_row,
        event_time,
        status=POSTCONDITION_FAILED_STATUS,
    )
    replace_helper_row(
        conn,
        PLC_NOT_REACH_ROLLNAME,
        helper_metadata["product"],
        helper_metadata["recipe"],
        helper_metadata["campaign"],
        event_time,
        PLC_NOT_REACH_STATUS,
    )
    conn.commit()
    log_event(
        "plc_not_reach_postcondition_inserted",
        rollid=rollid,
        rollname=recovery_row["rollname"],
        product=recovery_row["product"],
        recipe=recovery_row["recipe"],
        campaign=recovery_row["campaign"],
        starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
        endtime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
        status=POSTCONDITION_FAILED_STATUS,
    )
    log_event(
        "plc_not_reach_helper_saved",
        rollname=PLC_NOT_REACH_ROLLNAME,
        product=helper_metadata["product"],
        recipe=helper_metadata["recipe"],
        campaign=helper_metadata["campaign"],
        starttime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
        status=PLC_NOT_REACH_STATUS,
    )
    return base_rollname


def close_plc_not_reach_on_recovery(
    conn,
    dry_run: bool,
    event_time: datetime,
) -> bool:
    helper_row = fetch_helper_row(conn)
    if not is_valid_helper_row(helper_row):
        log_event(
            "plc_recovery_not_reach_close_skipped",
            reason="helper_invalid_or_empty",
        )
        return False

    if helper_row["rollname"] != PLC_NOT_REACH_ROLLNAME:
        log_event(
            "plc_recovery_not_reach_close_skipped",
            reason="helper_is_not_plc_not_reach",
            rollname=helper_row["rollname"],
            status=helper_row.get("status"),
        )
        return False

    if dry_run:
        log_event(
            "plc_recovery_not_reach_close_dry_run",
            rollname=helper_row["rollname"],
            product=helper_row["product"],
            recipe=helper_row["recipe"],
            campaign=helper_row["campaign"],
            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
            endtime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
            status=PLC_NOT_REACH_STATUS,
        )
        return True

    rollid = insert_rolldata_row(
        conn,
        helper_row,
        event_time,
        status=PLC_NOT_REACH_STATUS,
    )
    cleared_rows = clear_helper_row(conn)
    conn.commit()
    log_event(
        "plc_recovery_not_reach_closed",
        rollid=rollid,
        rollname=helper_row["rollname"],
        product=helper_row["product"],
        recipe=helper_row["recipe"],
        campaign=helper_row["campaign"],
        starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
        endtime=event_time.strftime("%Y-%m-%d %H:%M:%S"),
        status=PLC_NOT_REACH_STATUS,
        cleared_helper_rows=cleared_rows,
    )
    return True


def create_precondition_helper(
    conn,
    dry_run: bool,
    base_rollname: str,
    product_state: dict[str, Any],
    started_at: datetime,
    source: str,
) -> bool:
    helper_status = PRECONDITION_FAILED_STATUS

    helper_row = build_precondition_failed_row(
        base_rollname,
        product_state["product"],
        product_state["recipe"],
        product_state["campaign"],
        started_at,
    )
    if dry_run:
        log_event(
            "precondition_helper_dry_run",
            source=source,
            rollname=helper_row["rollname"],
            product=helper_row["product"],
            recipe=helper_row["recipe"],
            campaign=helper_row["campaign"],
            starttime=started_at.strftime("%Y-%m-%d %H:%M:%S"),
            status=helper_status,
        )
        return True

    replace_helper_row(
        conn,
        helper_row["rollname"],
        helper_row["product"],
        helper_row["recipe"],
        helper_row["campaign"],
        started_at,
        helper_status,
    )
    conn.commit()
    log_event(
        "precondition_helper_saved",
        source=source,
        rollname=helper_row["rollname"],
        product=helper_row["product"],
        recipe=helper_row["recipe"],
        campaign=helper_row["campaign"],
        starttime=started_at.strftime("%Y-%m-%d %H:%M:%S"),
        status=helper_status,
    )
    return True


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
    plc_unreachable_since_monotonic: Optional[float] = None
    plc_not_reach_timeout_handled = False
    pending_precondition_rollname = ""
    pending_precondition_source = ""

    while not _should_stop:
        try:
            just_reconnected = False
            if conn is None or conn.closed:
                conn = connect_db()
                database_config = db_config()
                log_event("db_connected", database=database_config["dbname"], user=database_config["user"])
                rtagroll_catalog = None
                if not startup_gap_checked:
                    recovered_rollname = recover_startup_gap(
                        conn,
                        dry_run=dry_run,
                        log_event=log_event,
                        fetch_helper_row=fetch_helper_row,
                        clear_helper_row=clear_helper_row,
                    )
                    if recovered_rollname:
                        pending_precondition_rollname = recovered_rollname
                        pending_precondition_source = "server_shutdown_recovery"
                    startup_gap_checked = True

            if plc is None or not plc.get_connected():
                plc = connect_plc()
                just_reconnected = plc_unreachable_since_monotonic is not None
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

            if rtagroll_catalog is None:
                rtagroll_catalog = load_rtagroll_catalog(RTAGROLL_CATALOG_PATH, conn)
                log_event(
                    "rtagroll_catalog_loaded",
                    catalog_source=str(RTAGROLL_CATALOG_PATH),
                    mapped_tags=len(rtagroll_catalog["entries"]),
                )

            product_state = read_product_state(plc)
            state = read_status_bits(plc)
            product_snapshot = (
                product_state["product"],
                product_state["recipe"],
                product_state["campaign"],
                product_state["status"],
            )

            if plc_unreachable_since_monotonic is not None and just_reconnected:
                log_event(
                    "plc_reconnected",
                    timeout_seconds=PLC_NOT_REACH_TIMEOUT_SECONDS,
                    timeout_handled=plc_not_reach_timeout_handled,
                )
                if plc_not_reach_timeout_handled:
                    close_plc_not_reach_on_recovery(
                        conn,
                        dry_run,
                        datetime.now(),
                    )
                if plc_not_reach_timeout_handled and pending_precondition_rollname:
                    if is_production_on(product_state):
                        create_precondition_helper(
                            conn,
                            dry_run,
                            pending_precondition_rollname,
                            product_state,
                            datetime.now(),
                            pending_precondition_source or "plc_not_reach_recovery",
                        )
                    else:
                        log_event(
                            "precondition_helper_skipped",
                            source=pending_precondition_source or "plc_not_reach_recovery",
                            reason="plc_not_in_production",
                            rollname=pending_precondition_rollname,
                            plc_status=product_state.get("status"),
                            product=product_state.get("product", ""),
                            recipe=product_state.get("recipe", ""),
                            campaign=product_state.get("campaign", ""),
                        )
                    pending_precondition_rollname = ""
                    pending_precondition_source = ""
                plc_unreachable_since_monotonic = None
                plc_not_reach_timeout_handled = False
            elif pending_precondition_rollname:
                if is_production_on(product_state):
                    create_precondition_helper(
                        conn,
                        dry_run,
                        pending_precondition_rollname,
                        product_state,
                        datetime.now(),
                        pending_precondition_source or "server_shutdown_recovery",
                    )
                else:
                    log_event(
                        "precondition_helper_skipped",
                        source=pending_precondition_source or "server_shutdown_recovery",
                        reason="plc_not_in_production",
                        rollname=pending_precondition_rollname,
                        plc_status=product_state.get("status"),
                        product=product_state.get("product", ""),
                        recipe=product_state.get("recipe", ""),
                        campaign=product_state.get("campaign", ""),
                    )
                pending_precondition_rollname = ""
                pending_precondition_source = ""

            start_rising = state["start_bit"] and not last_start_bit
            aux_changed = last_aux_bit is None or state["aux_bit"] != last_aux_bit
            aux_rising = state["aux_bit"] and not bool(last_aux_bit)
            first_cycle_changed = last_first_cycle_bit is None or state["first_cycle_bit"] != last_first_cycle_bit
            first_cycle_rising = state["first_cycle_bit"] and not bool(last_first_cycle_bit)
            product_changed = last_product_state is not None and product_snapshot != last_product_state

            if verbose or aux_changed or first_cycle_changed:
                log_event(
                    "bit_state",
                    db_winder_dbx3022_0=state["start_bit"],
                    db_winder_dbx3022_1=state["aux_bit"],
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
                            trigger="db_winder.dbx3022.1",
                            holdoff_ms=event_holdoff_ms,
                        )
                else:
                    pending_rolldata_event_time = datetime.now()
                    pending_rolldata_helper_row = fetch_helper_row(conn)
                    pending_rolldata_event_monotonic = current_monotonic
                    if verbose:
                        log_event(
                            "rolldata_pending",
                            trigger="db_winder.dbx3022.1",
                            holdoff_ms=event_holdoff_ms,
                            eventtime=pending_rolldata_event_time.strftime("%Y-%m-%d %H:%M:%S"),
                        )

            helper_trigger = ""
            if start_rising:
                helper_trigger = "db_winder.dbx3022.0"
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
                        trigger="db_winder.dbx3022.1",
                        message="Helper table is empty.",
                    )
                elif helper_row["rollname"] == "" or helper_row["starttime"] is None:
                    log_event(
                        "rolldata_skipped_invalid_helper",
                        trigger="db_winder.dbx3022.1",
                        helper_row=helper_row,
                    )
                else:
                    ended_at = pending_rolldata_event_time
                    helper_rollname = str(helper_row.get("rollname") or "")
                    rolldata_status = resolve_timeline_status(helper_rollname, TIMELINE_NORMAL_STATUS)
                    if dry_run:
                        rtagroll_result = {
                            "inserted_count": len(rtagroll_catalog["entries"]) if rtagroll_catalog is not None else 0,
                            "missing_addresses": [],
                            "skipped_values": [],
                        }
                        log_event(
                            "rolldata_insert_dry_run",
                            trigger="db_winder.dbx3022.1",
                            rollname=helper_row["rollname"],
                            product=helper_row["product"],
                            recipe=helper_row["recipe"],
                            campaign=helper_row["campaign"],
                            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                            endtime=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                            status=rolldata_status,
                            rtagroll_count=rtagroll_result["inserted_count"],
                        )
                    else:
                        if rtagroll_catalog is None or not rtagroll_catalog["entries"]:
                            raise RuntimeError("rtagroll catalog is empty.")

                        snapshot_payload = fetch_plc_tag_values(
                            [entry["address"] for entry in rtagroll_catalog["entries"]]
                        )
                        with conn:
                            rollid = insert_rolldata_row(conn, helper_row, ended_at, status=rolldata_status)
                            rtagroll_result = insert_rtagroll_rows(
                                conn,
                                rollid,
                                rtagroll_catalog["entries"],
                                snapshot_payload.get("tag_values", {}),
                                ended_at,
                            )
                        log_event(
                            "rolldata_inserted",
                            trigger="db_winder.dbx3022.1",
                            rollid=rollid,
                            rollname=helper_row["rollname"],
                            product=helper_row["product"],
                            recipe=helper_row["recipe"],
                            campaign=helper_row["campaign"],
                            starttime=helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S"),
                            endtime=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                            status=rolldata_status,
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
            unreachable_error = is_plc_unreachable_exception(exc)
            if not unreachable_error:
                log_event("error", message=str(exc))
            if unreachable_error:
                current_monotonic = time.monotonic()
                if plc_unreachable_since_monotonic is None:
                    plc_unreachable_since_monotonic = current_monotonic
                    log_event(
                        "plc_unreachable_detected",
                        timeout_seconds=PLC_NOT_REACH_TIMEOUT_SECONDS,
                        message=str(exc),
                    )

                outage_seconds = current_monotonic - plc_unreachable_since_monotonic
                if outage_seconds >= PLC_NOT_REACH_TIMEOUT_SECONDS and not plc_not_reach_timeout_handled:
                    transition_conn = None
                    try:
                        transition_conn = connect_db()
                        timeout_event_time = datetime.now()
                        recovered_rollname = handle_plc_not_reach_timeout(
                            transition_conn,
                            dry_run,
                            timeout_event_time,
                        )
                        plc_not_reach_timeout_handled = True
                        if recovered_rollname:
                            pending_precondition_rollname = recovered_rollname
                            pending_precondition_source = "plc_not_reach_recovery"
                        log_event(
                            "plc_not_reach_timeout_handled",
                            timeout_seconds=PLC_NOT_REACH_TIMEOUT_SECONDS,
                            endtime=timeout_event_time.strftime("%Y-%m-%d %H:%M:%S"),
                            status=POSTCONDITION_FAILED_STATUS,
                        )
                    except Exception as transition_exc:
                        log_event(
                            "plc_not_reach_timeout_failed",
                            timeout_seconds=PLC_NOT_REACH_TIMEOUT_SECONDS,
                            message=str(transition_exc),
                        )
                    finally:
                        if transition_conn is not None:
                            try:
                                transition_conn.close()
                            except Exception:
                                pass

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
        default=HISTORIAN_INTERVAL_MS,
        help=f"Polling interval in milliseconds. Default: {HISTORIAN_INTERVAL_MS}",
    )
    parser.add_argument(
        "--event-holdoff-ms",
        type=int,
        default=HISTORIAN_EVENT_HOLDOFF_MS,
        help=f"Minimum gap between saved events in milliseconds. Default: {HISTORIAN_EVENT_HOLDOFF_MS}",
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
        help="Print state changes for product/recipe/campaign, both DB_WINDER bits, and M2.0.",
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
