import re
from typing import Dict, List, Optional, Tuple

from plc.db.db_awl_model import FieldDef


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
