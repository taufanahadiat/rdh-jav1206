#!/usr/bin/env python3
import asyncio
import os
from datetime import datetime, timezone
from typing import List, Optional

import snap7
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

import DB2_General as db2


PLC_IP = os.getenv("PLC_IP", db2.PLC_IP)
RACK = int(os.getenv("PLC_RACK", str(db2.RACK)))
SLOT = int(os.getenv("PLC_SLOT", str(db2.SLOT)))

app = FastAPI(title="PLC Realtime API", version="1.0.0")


def _read_db2_general(tags: Optional[List[str]] = None) -> dict:
    plc = snap7.client.Client()
    try:
        plc.connect(PLC_IP, RACK, SLOT)
        if not plc.get_connected():
            raise RuntimeError("Failed to connect to PLC")

        if tags:
            tag_values = db2.read_tags(plc, tags)
            payload = {
                "db": db2.DB_NUM,
                "source_file": "Db_General",
                "tags": tag_values,
            }
            if len(tag_values) == 1:
                only_tag = next(iter(tag_values))
                payload["tag"] = only_tag
                payload["value"] = tag_values[only_tag]
        else:
            payload = db2.build_payload(plc)

        payload["plc_ip"] = PLC_IP
        payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        return payload
    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "plc-api", "timestamp_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/plc/db2/general")
def get_db2_general(tag: Optional[List[str]] = Query(default=None)) -> dict:
    try:
        return _read_db2_general(tag)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/ws/plc/db2/general")
async def ws_db2_general(websocket: WebSocket):
    await websocket.accept()

    tags = websocket.query_params.getlist("tag")
    interval_raw = websocket.query_params.get("interval_ms", "500")
    try:
        interval_ms = int(interval_raw)
    except ValueError:
        interval_ms = 500
    interval_ms = min(max(interval_ms, 100), 10000)

    try:
        while True:
            try:
                payload = _read_db2_general(tags or None)
                await websocket.send_json({"ok": True, "data": payload})
            except Exception as exc:
                await websocket.send_json({"ok": False, "error": str(exc), "timestamp_utc": datetime.now(timezone.utc).isoformat()})

            await asyncio.sleep(interval_ms / 1000)
    except WebSocketDisconnect:
        return
