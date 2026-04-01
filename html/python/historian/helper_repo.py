from datetime import datetime
from typing import Any, Optional

from historian.config import build_rollname, normalize_text
from systemlog import write_db_event


def replace_helper_row(
    conn,
    rollname: str,
    product: str,
    recipe: str,
    campaign: str,
    started_at: datetime,
    status: Optional[int],
) -> None:
    with conn.cursor() as cur:
        # Keep helper as the single source of truth for the active roll.
        cur.execute("DELETE FROM public.helper")
        deleted_rows = cur.rowcount
        cur.execute(
            """
            INSERT INTO public.helper (rollname, product, recipe, campaign, starttime, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                normalize_text(rollname),
                normalize_text(product),
                normalize_text(recipe),
                normalize_text(campaign),
                started_at.strftime("%Y-%m-%d %H:%M:%S"),
                status,
            ),
        )
        inserted_rows = cur.rowcount
    write_db_event(
        service="historian",
        component="helper_repo",
        action="replace",
        table_name="public.helper",
        row_count=inserted_rows,
        payload={
            "deleted_rows": deleted_rows,
            "rollname": normalize_text(rollname),
            "product": normalize_text(product),
            "recipe": normalize_text(recipe),
            "campaign": normalize_text(campaign),
            "starttime": started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
        },
        source_file=__file__,
        status_code=130,
    )


def write_helper_row(conn, state: dict[str, Any], started_at: datetime) -> None:
    replace_helper_row(
        conn,
        build_rollname(started_at),
        state["product"],
        state["recipe"],
        state["campaign"],
        started_at,
        state["status"],
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
        updated_rows = cur.rowcount
    write_db_event(
        service="historian",
        component="helper_repo",
        action="update",
        table_name="public.helper",
        row_count=updated_rows,
        payload={
            "product": state["product"],
            "recipe": state["recipe"],
            "campaign": state["campaign"],
            "status": state["status"],
        },
        source_file=__file__,
        status_code=130 if updated_rows > 0 else 220,
        severity="low" if updated_rows > 0 else "medium",
    )
    return updated_rows


def clear_helper_row(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.helper")
        deleted_rows = cur.rowcount
    write_db_event(
        service="historian",
        component="helper_repo",
        action="delete",
        table_name="public.helper",
        row_count=deleted_rows,
        source_file=__file__,
        status_code=130 if deleted_rows > 0 else 220,
        severity="low" if deleted_rows > 0 else "medium",
    )
    return deleted_rows


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
        write_db_event(
            service="historian",
            component="helper_repo",
            action="select",
            table_name="public.helper",
            row_count=0,
            payload={"result": "empty"},
            source_file=__file__,
            status_code=220,
            severity="medium",
        )
        return None

    helper_row = {
        "rollname": normalize_text(row[0]),
        "product": normalize_text(row[1]),
        "recipe": normalize_text(row[2]),
        "campaign": normalize_text(row[3]),
        "starttime": row[4],
        "status": int(row[5]) if row[5] is not None else None,
    }
    write_db_event(
        service="historian",
        component="helper_repo",
        action="select",
        table_name="public.helper",
        row_count=1,
        payload={
            "rollname": helper_row["rollname"],
            "starttime": helper_row["starttime"].strftime("%Y-%m-%d %H:%M:%S")
            if helper_row["starttime"] is not None
            else "",
            "status": helper_row["status"],
        },
        source_file=__file__,
        status_code=110,
    )
    return helper_row
