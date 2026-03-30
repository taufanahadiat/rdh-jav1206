import re
from pathlib import Path
from typing import Optional

from awl_import_models import Cursor, Node, Row


TYPE_RE = re.compile(r"^TYPE\s+UDT\s+(\d+)\s*$", re.IGNORECASE)
DATA_BLOCK_RE = re.compile(r"^DATA_BLOCK\s+DB\s+(\d+)\s*$", re.IGNORECASE)
END_TYPE_RE = re.compile(r"^END_TYPE\s*$", re.IGNORECASE)
STRUCT_START_RE = re.compile(r"^STRUCT\s*$", re.IGNORECASE)
NAMED_STRUCT_RE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*STRUCT\s*$", re.IGNORECASE)
END_STRUCT_RE = re.compile(r"^END_STRUCT\s*;\s*$", re.IGNORECASE)
ARRAY_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*:\s*ARRAY\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*OF\s+((?:UDT\s+\d+)|[A-Z_]+)\s*(?:\:=\s*(.+?))?\s*;\s*$",
    re.IGNORECASE,
)
UDT_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*:\s*UDT\s+(\d+)\s*(?:\:=\s*(.+?))?\s*;\s*$",
    re.IGNORECASE,
)
FIELD_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*:\s*([A-Z_]+)\s*(?:\:=\s*(.+?))?\s*;\s*$",
    re.IGNORECASE,
)
ASSIGN_RE = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[\d+\])*)\s*:=\s*(.+?)\s*;\s*$")

TYPE_CANON = {
    "BOOL": "BOOL",
    "BYTE": "BYTE",
    "WORD": "WORD",
    "DWORD": "DWORD",
    "CHAR": "CHAR",
    "INT": "INT",
    "DINT": "DINT",
    "REAL": "REAL",
}


def split_code_comment(raw_line: str) -> tuple[str, str]:
    line = raw_line.rstrip("\n").rstrip("\r")
    if "//" not in line:
        return line.strip(), ""
    code, comment = line.split("//", 1)
    return code.strip(), comment.strip()


def canonical_type(raw_type: str) -> str:
    clean = re.sub(r"\s+", " ", raw_type.strip().upper())
    return TYPE_CANON.get(clean, clean)


def align_even(cursor: Cursor) -> None:
    if cursor.bit:
        cursor.byte += 1
        cursor.bit = 0
    if cursor.byte % 2:
        cursor.byte += 1


def flush_bits(cursor: Cursor) -> None:
    if cursor.bit:
        cursor.byte += 1
        cursor.bit = 0


def parse_struct(lines: list[str], start_index: int) -> tuple[list[Node], int]:
    nodes: list[Node] = []
    idx = start_index
    while idx < len(lines):
        code, comment = split_code_comment(lines[idx])
        if not code:
            idx += 1
            continue

        if END_STRUCT_RE.match(code):
            return nodes, idx + 1

        match = NAMED_STRUCT_RE.match(code)
        if match:
            children, next_idx = parse_struct(lines, idx + 1)
            nodes.append(Node(kind="struct", name=match.group(1), comment=comment, children=children))
            idx = next_idx
            continue

        match = ARRAY_RE.match(code)
        if match:
            nodes.append(
                Node(
                    kind="array",
                    name=match.group(1),
                    data_type=canonical_type(match.group(4)),
                    comment=comment,
                    init=(match.group(5) or "").strip(),
                    array_start=int(match.group(2)),
                    array_end=int(match.group(3)),
                )
            )
            idx += 1
            continue

        match = UDT_RE.match(code)
        if match:
            nodes.append(
                Node(
                    kind="udt",
                    name=match.group(1),
                    data_type=f"UDT {match.group(2)}",
                    comment=comment,
                    init=(match.group(3) or "").strip(),
                )
            )
            idx += 1
            continue

        match = FIELD_RE.match(code)
        if match:
            nodes.append(
                Node(
                    kind="field",
                    name=match.group(1),
                    data_type=canonical_type(match.group(2)),
                    comment=comment,
                    init=(match.group(3) or "").strip(),
                )
            )
            idx += 1
            continue

        if STRUCT_START_RE.match(code):
            children, next_idx = parse_struct(lines, idx + 1)
            nodes.extend(children)
            idx = next_idx
            continue

        raise ValueError(f"Failed to parse the declaration on line {idx + 1}: {lines[idx].rstrip()}")

    raise ValueError("The STRUCT block is missing a closing `END_STRUCT ;`.")


def parse_udts(lines: list[str]) -> dict[str, Node]:
    udts: dict[str, Node] = {}
    idx = 0
    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        match = TYPE_RE.match(code)
        if not match:
            idx += 1
            continue

        udt_num = match.group(1)
        idx += 1
        while idx < len(lines):
            code, _ = split_code_comment(lines[idx])
            if not code:
                idx += 1
                continue
            if STRUCT_START_RE.match(code):
                children, idx = parse_struct(lines, idx + 1)
                udts[udt_num] = Node(kind="struct", name=f"UDT {udt_num}", children=children)
                break
            idx += 1

        while idx < len(lines):
            code, _ = split_code_comment(lines[idx])
            idx += 1
            if END_TYPE_RE.match(code):
                break

    return udts


def parse_data_block(lines: list[str]) -> tuple[int, Node, dict[str, str]]:
    dbsym = None
    struct_node = None
    assignments: dict[str, str] = {}
    idx = 0

    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        match = DATA_BLOCK_RE.match(code)
        if match:
            dbsym = int(match.group(1))
            idx += 1
            break
        idx += 1

    if dbsym is None:
        raise ValueError("The DATA_BLOCK DB section was not found.")

    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        if STRUCT_START_RE.match(code):
            children, idx = parse_struct(lines, idx + 1)
            struct_node = Node(kind="struct", name=f"DB {dbsym}", children=children)
            break
        idx += 1

    if struct_node is None:
        raise ValueError("The DATA_BLOCK STRUCT section was not found.")

    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        if code.upper() == "BEGIN":
            idx += 1
            break
        idx += 1

    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        idx += 1
        if not code:
            continue
        match = ASSIGN_RE.match(code)
        if match:
            assignments[match.group(1)] = match.group(2).strip()

    return dbsym, struct_node, assignments


def scalar_address(dbsym: int, data_type: str, cursor: Cursor) -> str:
    dtype = canonical_type(data_type)
    if dtype == "BOOL":
        address = f"DB{dbsym}.DBX{cursor.byte}.{cursor.bit}"
        cursor.bit += 1
        if cursor.bit >= 8:
            cursor.byte += 1
            cursor.bit = 0
        return address

    if dtype in {"BYTE", "CHAR"}:
        flush_bits(cursor)
        address = f"DB{dbsym}.DBB{cursor.byte}"
        cursor.byte += 1
        return address

    if dtype in {"WORD", "INT"}:
        align_even(cursor)
        address = f"DB{dbsym}.DBW{cursor.byte}"
        cursor.byte += 2
        return address

    if dtype in {"DWORD", "DINT", "REAL"}:
        align_even(cursor)
        address = f"DB{dbsym}.DBD{cursor.byte}"
        cursor.byte += 4
        return address

    raise ValueError(f"Unsupported data type: {data_type}")


def merge_path(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def expand_node(
    node: Node,
    dbsym: int,
    udts: dict[str, Node],
    cursor: Cursor,
    assignments: dict[str, str],
    prefix: str,
    rows: list[Row],
    is_root: bool = False,
) -> None:
    if node.kind == "struct":
        if not is_root:
            align_even(cursor)
        next_prefix = merge_path(prefix, node.name) if node.name and not is_root else prefix
        for child in node.children:
            expand_node(child, dbsym, udts, cursor, assignments, next_prefix, rows)
        if not is_root:
            align_even(cursor)
        return

    if node.kind == "udt":
        align_even(cursor)
        udt_num = node.data_type.split()[-1]
        udt_def = udts.get(udt_num)
        if udt_def is None:
            raise ValueError(f"UDT {udt_num} was not found for DB{dbsym}.{prefix}.{node.name}")
        next_prefix = merge_path(prefix, node.name)
        for child in udt_def.children:
            expand_node(child, dbsym, udts, cursor, assignments, next_prefix, rows)
        align_even(cursor)
        return

    if node.kind == "field":
        field_name = merge_path(prefix, node.name)
        address = scalar_address(dbsym, node.data_type, cursor)
        initvalue = assignments.get(field_name, node.init)
        rows.append(
            Row(
                dbsym=dbsym,
                address=address,
                name=field_name,
                data_type=node.data_type,
                initvalue=initvalue,
                comment=node.comment,
            )
        )
        return

    if node.kind == "array":
        base_type = node.data_type
        field_name = merge_path(prefix, node.name)
        if base_type.startswith("UDT "):
            align_even(cursor)
            udt_num = base_type.split()[-1]
            udt_def = udts.get(udt_num)
            if udt_def is None:
                raise ValueError(f"UDT {udt_num} was not found for array {field_name} in DB{dbsym}")
            for index in range(node.array_start, node.array_end + 1):
                item_prefix = f"{field_name}[{index}]"
                for child in udt_def.children:
                    expand_node(child, dbsym, udts, cursor, assignments, item_prefix, rows)
                align_even(cursor)
            return

        if canonical_type(base_type) in {"WORD", "INT", "DWORD", "DINT", "REAL"}:
            align_even(cursor)
        elif canonical_type(base_type) in {"BYTE", "CHAR"}:
            flush_bits(cursor)

        for index in range(node.array_start, node.array_end + 1):
            item_name = f"{field_name}[{index}]"
            address = scalar_address(dbsym, base_type, cursor)
            initvalue = assignments.get(item_name, node.init)
            rows.append(
                Row(
                    dbsym=dbsym,
                    address=address,
                    name=item_name,
                    data_type=f"ARRAY OF {base_type}",
                    initvalue=initvalue,
                    comment=node.comment,
                )
            )
        return

    raise ValueError(f"Unknown node kind: {node.kind}")


def parse_awl_file(path: Path) -> list[Row]:
    lines = path.read_text(encoding="latin-1").splitlines()
    udts = parse_udts(lines)
    dbsym, struct_node, assignments = parse_data_block(lines)
    cursor = Cursor()
    rows: list[Row] = []
    expand_node(struct_node, dbsym, udts, cursor, assignments, "", rows, is_root=True)
    return rows


def collect_rows(source_dir: Path, filter_dbsym: Optional[set[int]] = None) -> list[Row]:
    rows: list[Row] = []
    for path in sorted(source_dir.glob("DB*_*.AWL")):
        file_rows = parse_awl_file(path)
        if filter_dbsym is not None and file_rows:
            if file_rows[0].dbsym not in filter_dbsym:
                continue
        rows.extend(file_rows)
    return rows
