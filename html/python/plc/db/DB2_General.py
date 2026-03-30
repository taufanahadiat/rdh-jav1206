#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

import snap7
from snap7.util import get_int

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import PLC_IP, PLC_RACK, PLC_SLOT


RACK = PLC_RACK
SLOT = PLC_SLOT
DB_NUM = 2
STRING_LEN = 50
FIELD_SIZE = STRING_LEN + 2  # Siemens STRING header (max_len + cur_len)
STAT_OFFSET = FIELD_SIZE * 3
PAYLOAD_SIZE = STAT_OFFSET + 2


def read_s7_string(buf: bytes, offset: int, max_len: int) -> str:
    if offset + 2 > len(buf):
        return ""

    declared_max = int(buf[offset])
    cur_len = int(buf[offset + 1])
    allowed = max(0, min(max_len, declared_max))
    size = max(0, min(cur_len, allowed))

    start = offset + 2
    end = min(len(buf), start + size)
    raw = bytes(buf[start:end])
    return raw.decode("latin-1", errors="ignore").rstrip("\x00").strip()


def build_payload(plc: snap7.client.Client) -> dict:
    data = bytearray(plc.db_read(DB_NUM, 0, PAYLOAD_SIZE))

    return {
        "db": DB_NUM,
        "product": read_s7_string(data, 0, STRING_LEN),
        "recipe": read_s7_string(data, FIELD_SIZE, STRING_LEN),
        "campaign": read_s7_string(data, FIELD_SIZE * 2, STRING_LEN),
        "status": int(get_int(data, STAT_OFFSET)),
    }


TAG_PATTERN = re.compile(
    r"^DB(?P<db>\d+)\.(?:DBB(?P<byte_new>\d+)\[(?P<len_new>\d+)\]|DBS(?P<byte_old>\d+)(?:\.(?P<len_old>\d+))?)$",
    re.IGNORECASE,
)


def normalize_tag(raw_tag: str) -> tuple[str, int, int]:
    clean = re.sub(r"\s+", "", str(raw_tag or "").upper())
    m = TAG_PATTERN.match(clean)
    if not m:
        raise ValueError(f"Invalid tag format: {raw_tag}")

    db_num = int(m.group("db"))
    if db_num != DB_NUM:
        raise ValueError(f"Tag {raw_tag} does not belong to DB{DB_NUM}")

    byte_raw = m.group("byte_new") or m.group("byte_old")
    len_raw = m.group("len_new") or m.group("len_old")
    byte_offset = int(byte_raw)
    max_len = int(len_raw) if len_raw is not None else STRING_LEN
    if max_len < 1 or max_len > 254:
        raise ValueError(f"Invalid STRING length in tag: {raw_tag}")

    return f"DB{DB_NUM}.DBB{byte_offset}[{max_len}]", byte_offset, max_len


def read_tags(plc: snap7.client.Client, tags: list[str]) -> dict:
    normalized: list[tuple[str, int, int]] = [normalize_tag(tag) for tag in tags]
    if not normalized:
        return {}

    read_start = min(item[1] for item in normalized)
    read_end = max(item[1] + 2 + item[2] for item in normalized)
    read_size = max(0, read_end - read_start)
    db_data = bytes(plc.db_read(DB_NUM, read_start, read_size))

    result = {}
    for norm_tag, byte_offset, max_len in normalized:
        rel_offset = byte_offset - read_start
        result[norm_tag] = read_s7_string(db_data, rel_offset, max_len)

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Ambil tag STRING tertentu. Bisa diulang. Contoh: DB2.DBB0[50]",
    )
    args = parser.parse_args()

    plc = snap7.client.Client()
    try:
        plc.connect(PLC_IP, RACK, SLOT)
        if not plc.get_connected():
            raise RuntimeError("Failed to connect to PLC")

        if args.tag:
            tag_values = read_tags(plc, args.tag)
            payload = {
                "db": DB_NUM,
                "source_file": "Db_General",
                "tags": tag_values,
            }
            if len(tag_values) == 1:
                only_tag = next(iter(tag_values))
                payload["tag"] = only_tag
                payload["value"] = tag_values[only_tag]
        else:
            payload = build_payload(plc)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
