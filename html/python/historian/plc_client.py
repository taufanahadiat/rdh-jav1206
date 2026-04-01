import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import snap7
from snap7.util import get_bool

from plc.db import DB2_General as db2
from historian.config import (
    API_SNAPSHOT_URL,
    API_TIMEOUT_SECONDS,
    DB_WINDER_AUX_BIT,
    DB_WINDER_NUM,
    DB_WINDER_START_BIT,
    DB_WINDER_STATUS_BYTE,
    MARKER_FIRST_CYCLE_BIT,
    MARKER_STATUS_BYTE,
    PLC_IP,
    RACK,
    SLOT,
    normalize_text,
)
from systemlog import write_event as write_system_event


def connect_plc() -> snap7.client.Client:
    plc = snap7.client.Client()
    plc.connect(PLC_IP, RACK, SLOT)
    if not plc.get_connected():
        write_system_event(
            service="historian",
            component="plc_client",
            event="plc_connect_failed",
            payload={"plc_ip": PLC_IP, "rack": RACK, "slot": SLOT},
            source_file=__file__,
            severity="critical",
            status_code=500,
            message="Failed to connect to PLC",
        )
        raise RuntimeError("Failed to connect to PLC")
    write_system_event(
        service="historian",
        component="plc_client",
        event="plc_connect_succeeded",
        payload={"plc_ip": PLC_IP, "rack": RACK, "slot": SLOT},
        source_file=__file__,
        status_code=110,
    )
    return plc


def read_product_state(plc: snap7.client.Client) -> dict[str, Any]:
    payload = db2.build_payload(plc)

    return {
        "product": normalize_text(payload.get("product")),
        "recipe": normalize_text(payload.get("recipe")),
        "campaign": normalize_text(payload.get("campaign")),
        "status": int(payload.get("status") or 0),
    }


def read_status_bits(plc: snap7.client.Client) -> dict[str, bool]:
    status_buf = plc.db_read(DB_WINDER_NUM, DB_WINDER_STATUS_BYTE, 1)
    marker_buf = plc.mb_read(MARKER_STATUS_BYTE, 1)

    return {
        "start_bit": bool(get_bool(status_buf, 0, DB_WINDER_START_BIT)),
        "aux_bit": bool(get_bool(status_buf, 0, DB_WINDER_AUX_BIT)),
        "first_cycle_bit": bool(get_bool(marker_buf, 0, MARKER_FIRST_CYCLE_BIT)),
    }


def fetch_plc_tag_values(addresses: list[str]) -> dict[str, Any]:
    payload = json.dumps(
        {
            "tags": addresses,
            "direct_read_missing": True,
        }
    ).encode("utf-8")

    request = Request(
        API_SNAPSHOT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-PLCAPI-Caller": "historian_listener",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        write_system_event(
            service="historian",
            component="plc_client",
            event="plc_api_http_error",
            payload={"http_status": exc.code, "reason": exc.reason, "address_count": len(addresses)},
            source_file=__file__,
            severity="high",
            status_code=int(exc.code),
            message=f"PLC API HTTP {exc.code}: {exc.reason}",
        )
        raise RuntimeError(f"PLC API HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        write_system_event(
            service="historian",
            component="plc_client",
            event="plc_api_unreachable",
            payload={"reason": str(exc.reason), "address_count": len(addresses)},
            source_file=__file__,
            severity="critical",
            status_code=503,
            message=f"Failed to reach PLC API: {exc.reason}",
        )
        raise RuntimeError(f"Failed to reach PLC API: {exc.reason}") from exc

    data = json.loads(body)
    if not data.get("ok", False):
        write_system_event(
            service="historian",
            component="plc_client",
            event="plc_api_invalid_payload",
            payload={"address_count": len(addresses), "body_preview": body[:200]},
            source_file=__file__,
            severity="high",
            status_code=502,
            message=f"PLC API returned an invalid snapshot payload: {body[:200]}",
        )
        raise RuntimeError(f"PLC API returned an invalid snapshot payload: {body[:200]}")
    write_system_event(
        service="historian",
        component="plc_client",
        event="plc_tag_values_fetched",
        payload={
            "address_count": len(addresses),
            "resolved_tag_count": len(data.get("tag_values", {})),
            "missing_tag_count": len(data.get("missing_tags", [])),
        },
        source_file=__file__,
        status_code=110,
    )
    return data
