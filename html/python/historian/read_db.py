import json
from pathlib import Path
from typing import Any

from historian.config import (
    normalize_text,
)

def _normalize_addresses(raw_data: Any) -> list[str]:
    if not isinstance(raw_data, list):
        raise RuntimeError("Invalid historian tag file: root JSON value must be a list of addresses.")

    addresses: list[str] = []
    for index, value in enumerate(raw_data):
        address = normalize_text(value)
        if address == "":
            raise RuntimeError(f"Invalid historian tag file: item #{index + 1} is empty.")
        addresses.append(address)

    return addresses


def load_rtagroll_catalog(path: Path, conn) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(
            f"Historian tag file not found: {path}. Create or restore the address list before starting listener."
        )

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in historian tag file: {path}") from exc

    addresses = _normalize_addresses(raw_data)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, address
            FROM public.dblist
            WHERE address = ANY(%s)
            """,
            (addresses,),
        )
        rows = cur.fetchall()

    dbid_by_address = {
        normalize_text(row[1]): int(row[0])
        for row in rows
        if normalize_text(row[1]) != ""
    }

    missing_addresses = [address for address in addresses if address not in dbid_by_address]
    if missing_addresses:
        raise RuntimeError(
            "Historian tag addresses not found in public.dblist: "
            + ", ".join(missing_addresses[:20])
        )

    entries = [
        {
            "dbid": dbid_by_address[address],
            "address": address,
        }
        for address in addresses
    ]

    return {
        "entries": entries,
    }
