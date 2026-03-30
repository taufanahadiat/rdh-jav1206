import re
from typing import Any, Dict, List, Optional, Tuple

import snap7
from snap7.util import get_bool, get_dint, get_int, get_real, get_word

from plc.db.db_awl_layout import (
    PRIMITIVE_SIZE,
    align_even,
    calc_struct_size,
    calc_type_size,
    is_primitive,
)
from plc.db.db_awl_model import FieldDef
from plc.db.db_awl_parser import normalize_type_name


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
