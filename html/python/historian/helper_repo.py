from datetime import datetime
from typing import Any, Optional

from historian.config import build_rollname, normalize_text


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
