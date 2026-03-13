import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import snap7
from snap7.util import get_bool, get_int, get_word, get_dint, get_real


@dataclass
class FieldDef:
    name: str
    type_name: str
    is_array: bool = False
    array_start: int = 0
    array_end: int = 0
    nested_fields: Optional[List["FieldDef"]] = None


def normalize_type_name(type_name: str) -> str:
    s = type_name.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def strip_comment(line: str) -> str:
    if "//" in line:
        line = line.split("//", 1)[0]
    return line.strip()


def parse_field_line(line: str) -> Optional[FieldDef]:
    line = strip_comment(line)
    if not line:
        return None

    if not line.endswith(";"):
        return None

    m_array = re.match(
        r"^(\w+)\s*:\s*ARRAY\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*OF\s*([A-Za-z]+\s*\d*|BOOL|WORD|INT|DINT|REAL|BYTE|CHAR|DWORD)\s*;\s*$",
        line,
        re.IGNORECASE,
    )
    if m_array:
        return FieldDef(
            name=m_array.group(1),
            type_name=normalize_type_name(m_array.group(4)),
            is_array=True,
            array_start=int(m_array.group(2)),
            array_end=int(m_array.group(3)),
        )

    m_normal = re.match(
        r"^(\w+)\s*:\s*([A-Za-z]+\s*\d*|BOOL|WORD|INT|DINT|REAL|BYTE|CHAR|DWORD)\s*;\s*$",
        line,
        re.IGNORECASE,
    )
    if m_normal:
        return FieldDef(
            name=m_normal.group(1),
            type_name=normalize_type_name(m_normal.group(2)),
        )

    return None


def parse_struct_lines(lines: List[str], start_idx: int = 0) -> Tuple[List[FieldDef], int]:
    fields: List[FieldDef] = []
    i = start_idx

    while i < len(lines):
        raw = lines[i]
        line = strip_comment(raw)

        if not line:
            i += 1
            continue

        if re.match(r"^END_STRUCT\s*;\s*$", line, re.IGNORECASE):
            return fields, i + 1

        m_nested = re.match(r"^(\w+)\s*:\s*STRUCT\s*$", line, re.IGNORECASE)
        if m_nested:
            nested_name = m_nested.group(1)
            nested_fields, next_idx = parse_struct_lines(lines, i + 1)
            fields.append(
                FieldDef(
                    name=nested_name,
                    type_name="STRUCT",
                    nested_fields=nested_fields,
                )
            )
            i = next_idx
            continue

        field = parse_field_line(line)
        if field:
            fields.append(field)

        i += 1

    return fields, i


def parse_awl_file(text: str, db_num: int) -> Tuple[Dict[str, List[FieldDef]], List[FieldDef]]:
    type_map: Dict[str, List[FieldDef]] = {}

    type_pattern = re.compile(
        r"TYPE\s+(UDT\s+\d+).*?STRUCT(.*?)END_STRUCT\s*;\s*END_TYPE",
        re.IGNORECASE | re.DOTALL,
    )

    for match in type_pattern.finditer(text):
        udt_name = normalize_type_name(match.group(1))
        body = match.group(2)
        fields, _ = parse_struct_lines(body.splitlines())
        type_map[udt_name] = fields

    db_pattern = re.compile(
        rf"DATA_BLOCK\s+DB\s+{db_num}\b.*?STRUCT(.*?)END_STRUCT\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    db_match = db_pattern.search(text)
    if not db_match:
        raise ValueError(f"DATA_BLOCK DB {db_num} was not found in the AWL file")

    db_body = db_match.group(1)
    db_fields, _ = parse_struct_lines(db_body.splitlines())

    return type_map, db_fields


PRIMITIVE_TYPES = {"BOOL", "BYTE", "CHAR", "WORD", "INT", "DWORD", "DINT", "REAL"}

PRIMITIVE_SIZE = {
    "BOOL": 1,
    "BYTE": 1,
    "CHAR": 1,
    "WORD": 2,
    "INT": 2,
    "DWORD": 4,
    "DINT": 4,
    "REAL": 4,
}


def is_primitive(type_name: str) -> bool:
    return type_name.upper() in PRIMITIVE_TYPES


def align_even(byte_offset: int, bit_offset: int) -> Tuple[int, int]:
    if bit_offset != 0:
        byte_offset += 1
        bit_offset = 0
    if byte_offset % 2 != 0:
        byte_offset += 1
    return byte_offset, bit_offset


def finalize_struct_size(byte_offset: int, bit_offset: int) -> int:
    if bit_offset != 0:
        byte_offset += 1
    if byte_offset % 2 != 0:
        byte_offset += 1
    return byte_offset


def calc_type_size(type_name: str, type_map: Dict[str, List[FieldDef]], cache: Dict[str, int]) -> int:
    type_name = normalize_type_name(type_name)
    key_upper = type_name.upper()

    if type_name in cache:
        return cache[type_name]

    if key_upper in PRIMITIVE_SIZE:
        cache[type_name] = PRIMITIVE_SIZE[key_upper]
        return cache[type_name]

    if type_name not in type_map:
        raise ValueError(f"Unknown type: {type_name}")

    byte_offset = 0
    bit_offset = 0

    for field in type_map[type_name]:
        if field.nested_fields is not None:
            byte_offset, bit_offset = align_even(byte_offset, bit_offset)
            nested_size = calc_struct_size(field.nested_fields, type_map, cache)
            byte_offset += nested_size
            continue

        field_type = normalize_type_name(field.type_name)
        field_upper = field_type.upper()

        if field.is_array:
            count = field.array_end - field.array_start + 1

            if field_upper == "BOOL":
                for _ in range(count):
                    bit_offset += 1
                    if bit_offset >= 8:
                        byte_offset += 1
                        bit_offset = 0
            else:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                elem_size = calc_type_size(field_type, type_map, cache)
                byte_offset += elem_size * count
        else:
            if field_upper == "BOOL":
                bit_offset += 1
                if bit_offset >= 8:
                    byte_offset += 1
                    bit_offset = 0
            elif field_upper in PRIMITIVE_SIZE:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                byte_offset += PRIMITIVE_SIZE[field_upper]
            else:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                byte_offset += calc_type_size(field_type, type_map, cache)

    size = finalize_struct_size(byte_offset, bit_offset)
    cache[type_name] = size
    return size


def calc_struct_size(fields: List[FieldDef], type_map: Dict[str, List[FieldDef]], cache: Dict[str, int]) -> int:
    byte_offset = 0
    bit_offset = 0

    for field in fields:
        if field.nested_fields is not None:
            byte_offset, bit_offset = align_even(byte_offset, bit_offset)
            nested_size = calc_struct_size(field.nested_fields, type_map, cache)
            byte_offset += nested_size
            continue

        field_type = normalize_type_name(field.type_name)
        field_upper = field_type.upper()

        if field.is_array:
            count = field.array_end - field.array_start + 1

            if field_upper == "BOOL":
                for _ in range(count):
                    bit_offset += 1
                    if bit_offset >= 8:
                        byte_offset += 1
                        bit_offset = 0
            else:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                elem_size = calc_type_size(field_type, type_map, cache)
                byte_offset += elem_size * count
        else:
            if field_upper == "BOOL":
                bit_offset += 1
                if bit_offset >= 8:
                    byte_offset += 1
                    bit_offset = 0
            elif field_upper in PRIMITIVE_SIZE:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                byte_offset += PRIMITIVE_SIZE[field_upper]
            else:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                byte_offset += calc_type_size(field_type, type_map, cache)

    return finalize_struct_size(byte_offset, bit_offset)


def read_primitive(buffer: bytearray, type_name: str, byte_offset: int, bit_offset: int = 0) -> Any:
    t = type_name.upper()

    if t == "BOOL":
        return get_bool(buffer, byte_offset, bit_offset)
    if t == "BYTE":
        return buffer[byte_offset]
    if t == "CHAR":
        return chr(buffer[byte_offset])
    if t == "WORD":
        return get_word(buffer, byte_offset)
    if t == "INT":
        return get_int(buffer, byte_offset)
    if t == "DWORD":
        return int.from_bytes(buffer[byte_offset:byte_offset + 4], byteorder="big", signed=False)
    if t == "DINT":
        return get_dint(buffer, byte_offset)
    if t == "REAL":
        return get_real(buffer, byte_offset)

    raise ValueError(f"Unsupported primitive type: {type_name}")


TAG_PATTERN = re.compile(
    r"^DB(?P<db>\d+)\.(?P<kind>DBX|DBB|DBW|DBD)(?P<byte>\d+)(?:\.(?P<bit>\d+))?$",
    re.IGNORECASE,
)


def parse_tag_parts(tag: str) -> Dict[str, int]:
    raw = re.sub(r"\s+", "", tag.strip().upper())
    m = TAG_PATTERN.match(raw)
    if not m:
        raise ValueError(f"Invalid tag format: {tag}")

    db = int(m.group("db"))
    kind = m.group("kind").upper()
    byte_offset = int(m.group("byte"))
    bit_raw = m.group("bit")
    bit_offset = int(bit_raw) if bit_raw is not None else -1

    if kind == "DBX":
        if bit_offset < 0 or bit_offset > 7:
            raise ValueError(f"DBX bit must be between 0 and 7: {tag}")
    elif bit_raw is not None:
        raise ValueError(f"Tag {kind} cannot include a bit offset: {tag}")

    return {
        "db": db,
        "kind": kind,
        "byte_offset": byte_offset,
        "bit_offset": bit_offset,
    }


def normalize_tag(tag: str) -> Tuple[str, int]:
    part = parse_tag_parts(tag)
    db = part["db"]
    kind = part["kind"]
    byte_offset = part["byte_offset"]
    bit_offset = part["bit_offset"]

    if kind == "DBX":
        return f"DB{db}.DBX{byte_offset}.{bit_offset}", db

    return f"DB{db}.{kind}{byte_offset}", db


def read_tag_direct(plc: snap7.client.Client, tag: str) -> Any:
    part = parse_tag_parts(tag)
    db_num = part["db"]
    kind = part["kind"]
    byte_offset = part["byte_offset"]
    bit_offset = part["bit_offset"]

    if kind == "DBX":
        data = bytearray(plc.db_read(db_num, byte_offset, 1))
        return bool(get_bool(data, 0, bit_offset))
    if kind == "DBB":
        data = bytearray(plc.db_read(db_num, byte_offset, 1))
        return int(data[0])
    if kind == "DBW":
        data = bytearray(plc.db_read(db_num, byte_offset, 2))
        return int(get_word(data, 0))
    if kind == "DBD":
        data = bytearray(plc.db_read(db_num, byte_offset, 4))
        return float(get_real(data, 0))

    raise ValueError(f"Unsupported tag type: {tag}")


def build_address_key(db_num: int, type_name: str, byte_offset: int, bit_offset: int = 0) -> str:
    t = type_name.upper()
    if t == "BOOL":
        return f"DB{db_num}.DBX{byte_offset}.{bit_offset}"
    if t in {"BYTE", "CHAR"}:
        return f"DB{db_num}.DBB{byte_offset}"
    if t in {"WORD", "INT"}:
        return f"DB{db_num}.DBW{byte_offset}"
    if t in {"DWORD", "DINT", "REAL"}:
        return f"DB{db_num}.DBD{byte_offset}"
    raise ValueError(f"Unsupported primitive type: {type_name}")


def map_primitive_address(
    address_map: Optional[Dict[str, Any]],
    db_num: Optional[int],
    type_name: str,
    byte_offset: int,
    value: Any,
    bit_offset: int = 0,
) -> None:
    if address_map is None or db_num is None:
        return

    key = build_address_key(db_num, type_name, byte_offset, bit_offset)
    address_map[key] = value


def read_struct(
    buffer: bytearray,
    fields: List[FieldDef],
    type_map: Dict[str, List[FieldDef]],
    base_offset: int,
    size_cache: Dict[str, int],
    address_map: Optional[Dict[str, Any]] = None,
    db_num: Optional[int] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    byte_offset = 0
    bit_offset = 0

    for field in fields:
        if field.nested_fields is not None:
            byte_offset, bit_offset = align_even(byte_offset, bit_offset)
            result[field.name] = read_struct(
                buffer,
                field.nested_fields,
                type_map,
                base_offset + byte_offset,
                size_cache,
                address_map=address_map,
                db_num=db_num,
            )
            byte_offset += calc_struct_size(field.nested_fields, type_map, size_cache)
            continue

        field_type = normalize_type_name(field.type_name)
        field_upper = field_type.upper()

        if field.is_array:
            count = field.array_end - field.array_start + 1
            arr = []

            if field_upper == "BOOL":
                for _ in range(count):
                    value = read_primitive(buffer, "BOOL", base_offset + byte_offset, bit_offset)
                    arr.append(value)
                    map_primitive_address(
                        address_map=address_map,
                        db_num=db_num,
                        type_name="BOOL",
                        byte_offset=base_offset + byte_offset,
                        bit_offset=bit_offset,
                        value=value,
                    )
                    bit_offset += 1
                    if bit_offset >= 8:
                        byte_offset += 1
                        bit_offset = 0
            else:
                byte_offset, bit_offset = align_even(byte_offset, bit_offset)
                elem_size = calc_type_size(field_type, type_map, size_cache)

                for i in range(count):
                    elem_base = base_offset + byte_offset + (i * elem_size)
                    if is_primitive(field_type):
                        value = read_primitive(buffer, field_type, elem_base)
                        arr.append(value)
                        map_primitive_address(
                            address_map=address_map,
                            db_num=db_num,
                            type_name=field_type,
                            byte_offset=elem_base,
                            value=value,
                        )
                    else:
                        arr.append(
                            read_struct(
                                buffer,
                                type_map[field_type],
                                type_map,
                                elem_base,
                                size_cache,
                                address_map=address_map,
                                db_num=db_num,
                            )
                        )

                byte_offset += elem_size * count

            result[field.name] = arr
            continue

        if field_upper == "BOOL":
            value = read_primitive(buffer, "BOOL", base_offset + byte_offset, bit_offset)
            result[field.name] = value
            map_primitive_address(
                address_map=address_map,
                db_num=db_num,
                type_name="BOOL",
                byte_offset=base_offset + byte_offset,
                bit_offset=bit_offset,
                value=value,
            )
            bit_offset += 1
            if bit_offset >= 8:
                byte_offset += 1
                bit_offset = 0

        elif field_upper in PRIMITIVE_SIZE:
            byte_offset, bit_offset = align_even(byte_offset, bit_offset)
            value = read_primitive(buffer, field_type, base_offset + byte_offset)
            result[field.name] = value
            map_primitive_address(
                address_map=address_map,
                db_num=db_num,
                type_name=field_type,
                byte_offset=base_offset + byte_offset,
                value=value,
            )
            byte_offset += PRIMITIVE_SIZE[field_upper]

        else:
            byte_offset, bit_offset = align_even(byte_offset, bit_offset)
            result[field.name] = read_struct(
                buffer,
                type_map[field_type],
                type_map,
                base_offset + byte_offset,
                size_cache,
                address_map=address_map,
                db_num=db_num,
            )
            byte_offset += calc_type_size(field_type, type_map, size_cache)

    return result


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
    plc_ip: str = "169.254.254.45",
    rack: int = 0,
    slot: int = 1,
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
                    # Fallback: baca langsung offset PLC untuk jaga kompatibilitas
                    # jika layout AWL tidak sama persis dengan data block aktual PLC.
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

    except Exception as e:
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
