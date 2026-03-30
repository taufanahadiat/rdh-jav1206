from typing import Dict, List, Tuple

from plc.db.db_awl_model import FieldDef
from plc.db.db_awl_parser import normalize_type_name


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
