import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import snap7

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import PLC_IP, PLC_RACK, PLC_SLOT
from systemlog import build_cli_payload, write_event as write_system_event

from plc.db.db_awl_decoder import (
    TAG_PATTERN,
    build_address_key,
    map_primitive_address,
    normalize_tag,
    parse_tag_parts,
    read_primitive,
    read_struct,
    read_tag_direct,
)
from plc.db.db_awl_layout import (
    PRIMITIVE_SIZE,
    PRIMITIVE_TYPES,
    align_even,
    calc_struct_size,
    calc_type_size,
    finalize_struct_size,
    is_primitive,
)
from plc.db.db_awl_model import FieldDef
from plc.db.db_awl_parser import (
    normalize_type_name,
    parse_awl_file,
    parse_field_line,
    parse_struct_lines,
    strip_comment,
)


def format_value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


def print_tree(data: Any, path: str = "", indent: int = 0) -> None:
    space = " " * indent

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                print(f"{space}{new_path}:")
                print_tree(value, new_path, indent + 2)
            else:
                print(f"{space}{new_path} = {format_value(value)}")

    elif isinstance(data, list):
        for idx, value in enumerate(data):
            new_path = f"{path}[{idx}]"
            if isinstance(value, (dict, list)):
                print(f"{space}{new_path}:")
                print_tree(value, new_path, indent + 2)
            else:
                print(f"{space}{new_path} = {format_value(value)}")


def run_db_reader(
    db_num: int,
    db_name: str,
    awl_source_file: str,
    plc_ip: str = PLC_IP,
    rack: int = PLC_RACK,
    slot: int = PLC_SLOT,
    argv: Optional[List[str]] = None,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--awl", default=awl_source_file, help="Path source AWL file")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Ambil tag PLC tertentu. Bisa diulang. Contoh: DB300.DBD200",
    )
    args = parser.parse_args(argv)
    cli_args = argv if argv is not None else sys.argv[1:]
    write_system_event(
        service="plc_db",
        component=f"db_awl_reader_db{db_num}",
        event="script_started",
        payload=build_cli_payload(cli_args),
        source_file=__file__,
    )

    plc = snap7.client.Client()

    try:
        with open(args.awl, "r", encoding="utf-8", errors="ignore") as f:
            awl_text = f.read()

        type_map, db_fields = parse_awl_file(awl_text, db_num)

        size_cache: Dict[str, int] = {}
        total_bytes = calc_struct_size(db_fields, type_map, size_cache)

        plc.connect(plc_ip, rack, slot)

        if not plc.get_connected():
            raise RuntimeError("Failed to connect to PLC")

        if not args.json:
            print("Connected to PLC")
            print(f"Source AWL : {args.awl}")
            print(f"DB Number  : {db_num}")
            print(f"Total Bytes: {total_bytes}")

        requested_tags: List[str] = []
        for raw_tag in args.tag:
            tag, tag_db = normalize_tag(raw_tag)
            if tag_db != db_num:
                raise ValueError(f"Tag {raw_tag} does not belong to DB{db_num}")
            requested_tags.append(tag)

        data = plc.db_read(db_num, 0, total_bytes)
        address_map: Dict[str, Any] = {}
        result = read_struct(
            data,
            db_fields,
            type_map,
            0,
            size_cache,
            address_map=address_map,
            db_num=db_num,
        )

        if requested_tags:
            selected: Dict[str, Any] = {}
            for tag in requested_tags:
                if tag in address_map:
                    selected[tag] = address_map[tag]
                else:
                    selected[tag] = read_tag_direct(plc, tag)

            output = {
                "db": db_num,
                "source_file": args.awl,
                "tags": selected,
            }
            if len(selected) == 1:
                only_tag = next(iter(selected))
                output["tag"] = only_tag
                output["value"] = selected[only_tag]
        else:
            output = {
                "db": db_num,
                "source_file": args.awl,
                "total_bytes": total_bytes,
                "data": result,
            }

        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== DB{db_num} {db_name} ===")
            print_tree(result)
        write_system_event(
            service="plc_db",
            component=f"db_awl_reader_db{db_num}",
            event="script_completed",
            payload={"db_num": db_num, "db_name": db_name, "requested_tag_count": len(requested_tags)},
            source_file=__file__,
            status_code=130,
        )

    except Exception as e:
        write_system_event(
            service="plc_db",
            component=f"db_awl_reader_db{db_num}",
            event="script_failed",
            payload={"db_num": db_num, "db_name": db_name, "message": str(e)},
            source_file=__file__,
            severity="critical",
            status_code=500,
            message=str(e),
        )
        if args.json:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
                if not args.json:
                    print("\nDisconnected")
        except Exception:
            pass

    return 0


__all__ = [
    "FieldDef",
    "PRIMITIVE_SIZE",
    "PRIMITIVE_TYPES",
    "TAG_PATTERN",
    "align_even",
    "build_address_key",
    "calc_struct_size",
    "calc_type_size",
    "finalize_struct_size",
    "format_value",
    "is_primitive",
    "map_primitive_address",
    "normalize_tag",
    "normalize_type_name",
    "parse_awl_file",
    "parse_field_line",
    "parse_struct_lines",
    "parse_tag_parts",
    "print_tree",
    "read_primitive",
    "read_struct",
    "read_tag_direct",
    "run_db_reader",
    "strip_comment",
]
