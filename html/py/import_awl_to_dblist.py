#!/usr/bin/env python3
import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DB_HOST = os.getenv("PGHOST", "127.0.0.1")
DB_PORT = os.getenv("PGPORT", "5432")
DB_NAME = os.getenv("PGDATABASE", "jav1206")
DB_USER = os.getenv("PGUSER", "jav1206")
DB_PASS = os.getenv("PGPASSWORD", "akpidev3")

SOURCE_DIR = Path("/var/www/S7_DB")
PSQL_CANDIDATES = [
    os.getenv("PSQL_BIN", "").strip(),
    "/usr/bin/psql",
    "/usr/pgsql-15/bin/psql",
    "/usr/lib/postgresql/15/bin/psql",
]

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


@dataclass
class Node:
    kind: str
    name: str = ""
    data_type: str = ""
    comment: str = ""
    init: str = ""
    array_start: int = 0
    array_end: int = 0
    children: List["Node"] = field(default_factory=list)


@dataclass
class Cursor:
    byte: int = 0
    bit: int = 0

    def clone(self) -> "Cursor":
        return Cursor(self.byte, self.bit)


@dataclass
class Row:
    dbsym: int
    address: str
    name: str
    data_type: str
    initvalue: str
    comment: str


def resolve_psql_bin() -> str:
    for candidate in PSQL_CANDIDATES:
        if not candidate:
            continue
        resolved = os.path.realpath(candidate)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    which_psql = shutil.which("psql")
    if which_psql:
        resolved = os.path.realpath(which_psql)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    raise RuntimeError("The `psql` binary was not found.")


PSQL_BIN = resolve_psql_bin()


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


def parse_struct(lines: List[str], start_index: int) -> tuple[List[Node], int]:
    nodes: List[Node] = []
    idx = start_index
    while idx < len(lines):
        code, comment = split_code_comment(lines[idx])
        if not code:
            idx += 1
            continue

        if END_STRUCT_RE.match(code):
            return nodes, idx + 1

        m = NAMED_STRUCT_RE.match(code)
        if m:
            children, next_idx = parse_struct(lines, idx + 1)
            nodes.append(Node(kind="struct", name=m.group(1), comment=comment, children=children))
            idx = next_idx
            continue

        m = ARRAY_RE.match(code)
        if m:
            nodes.append(
                Node(
                    kind="array",
                    name=m.group(1),
                    data_type=canonical_type(m.group(4)),
                    comment=comment,
                    init=(m.group(5) or "").strip(),
                    array_start=int(m.group(2)),
                    array_end=int(m.group(3)),
                )
            )
            idx += 1
            continue

        m = UDT_RE.match(code)
        if m:
            nodes.append(
                Node(
                    kind="udt",
                    name=m.group(1),
                    data_type=f"UDT {m.group(2)}",
                    comment=comment,
                    init=(m.group(3) or "").strip(),
                )
            )
            idx += 1
            continue

        m = FIELD_RE.match(code)
        if m:
            nodes.append(
                Node(
                    kind="field",
                    name=m.group(1),
                    data_type=canonical_type(m.group(2)),
                    comment=comment,
                    init=(m.group(3) or "").strip(),
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


def parse_udts(lines: List[str]) -> Dict[str, Node]:
    udts: Dict[str, Node] = {}
    idx = 0
    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        m = TYPE_RE.match(code)
        if not m:
            idx += 1
            continue

        udt_num = m.group(1)
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


def parse_data_block(lines: List[str]) -> tuple[int, Node, Dict[str, str]]:
    dbsym = None
    struct_node = None
    assignments: Dict[str, str] = {}
    idx = 0

    while idx < len(lines):
        code, _ = split_code_comment(lines[idx])
        m = DATA_BLOCK_RE.match(code)
        if m:
            dbsym = int(m.group(1))
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
        m = ASSIGN_RE.match(code)
        if m:
            assignments[m.group(1)] = m.group(2).strip()

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
    udts: Dict[str, Node],
    cursor: Cursor,
    assignments: Dict[str, str],
    prefix: str,
    rows: List[Row],
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
            expand_node(child, dbsym, udt_def.children and udts, cursor, assignments, next_prefix, rows)
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


def parse_awl_file(path: Path) -> List[Row]:
    lines = path.read_text(encoding="latin-1").splitlines()
    udts = parse_udts(lines)
    dbsym, struct_node, assignments = parse_data_block(lines)
    cursor = Cursor()
    rows: List[Row] = []
    expand_node(struct_node, dbsym, udts, cursor, assignments, "", rows, is_root=True)
    return rows


def collect_rows(source_dir: Path, filter_dbsym: Optional[set[int]] = None) -> List[Row]:
    rows: List[Row] = []
    for path in sorted(source_dir.glob("DB*_*.AWL")):
        file_rows = parse_awl_file(path)
        if filter_dbsym is not None and file_rows:
            if file_rows[0].dbsym not in filter_dbsym:
                continue
        rows.extend(file_rows)
    return rows


def run_psql(sql: str, stdin_data: Optional[str] = None) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS
    cmd = [
        PSQL_BIN,
        "-h",
        DB_HOST,
        "-p",
        DB_PORT,
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-v",
        "ON_ERROR_STOP=1",
        "-At",
        "-c",
        sql,
    ]
    proc = subprocess.run(
        cmd,
        input=stdin_data,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "`psql` failed.")
    return proc.stdout


def fetch_dbmaster_map() -> Dict[int, dict]:
    raw = run_psql("SELECT dbsym, id, dbname FROM public.dbmaster ORDER BY dbsym;")
    mapping: Dict[int, dict] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        dbsym_text, id_text, dbname_text = line.split("|", 2)
        mapping[int(dbsym_text)] = {
            "id": int(id_text),
            "dbname": dbname_text.strip(),
        }
    return mapping


def prefixed_name(dbname: str, name: str) -> str:
    clean_dbname = dbname.strip()
    clean_name = name.strip()
    if not clean_dbname:
        return clean_name
    if not clean_name:
        return clean_dbname
    if clean_name.startswith(clean_dbname + "."):
        return clean_name
    return f"{clean_dbname}.{clean_name}"


def rows_to_csv(rows: Iterable[Row], dbmaster_map: Dict[int, dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        dbmaster = dbmaster_map.get(row.dbsym)
        if dbmaster is None:
            raise ValueError(f"The dbmaster entry for DB{row.dbsym} was not found.")
        writer.writerow(
            [
                dbmaster["id"],
                row.address,
                prefixed_name(str(dbmaster["dbname"]), row.name),
                row.data_type,
                row.initvalue,
                row.comment,
            ]
        )
    return buffer.getvalue()


def run_psql_script(script: str) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS
    cmd = [
        PSQL_BIN,
        "-h",
        DB_HOST,
        "-p",
        DB_PORT,
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    proc = subprocess.run(
        cmd,
        input=script,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "The `psql` script failed.")
    return proc.stdout


def sql_literal(value: Optional[object]) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def write_to_db(rows: List[Row]) -> None:
    dbmaster_map = fetch_dbmaster_map()
    target_ids = sorted({int(dbmaster_map[row.dbsym]["id"]) for row in rows if row.dbsym in dbmaster_map})
    if not target_ids:
        raise ValueError("No matching dbmasterid values were found for the parsed data.")

    target_id_list = ", ".join(str(item) for item in target_ids)

    run_psql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_dblist_address_unique "
        "ON public.dblist (address);"
    )

    batch_size = 500
    script_parts = [
        "BEGIN;",
        """CREATE TEMP TABLE tmp_dblist_import (
  source_order integer,
  dbmasterid integer,
  address varchar(255),
  name varchar(255),
  type varchar(100),
  initvalue text,
  comment text
) ON COMMIT DROP;""",
    ]

    staged_rows = []
    for order_index, row in enumerate(rows, start=1):
        dbmaster = dbmaster_map.get(row.dbsym)
        if dbmaster is None:
            raise ValueError(f"The dbmaster entry for DB{row.dbsym} was not found.")
        dbmasterid = int(dbmaster["id"])
        staged_rows.append(
            "("
            + ", ".join(
                [
                    str(order_index),
                    str(dbmasterid),
                    sql_literal(row.address),
                    sql_literal(prefixed_name(str(dbmaster["dbname"]), row.name)),
                    sql_literal(row.data_type),
                    sql_literal(row.initvalue),
                    sql_literal(row.comment),
                ]
            )
            + ")"
        )

    for start in range(0, len(staged_rows), batch_size):
        chunk = staged_rows[start : start + batch_size]
        script_parts.append(
            "INSERT INTO tmp_dblist_import (source_order, dbmasterid, address, name, type, initvalue, comment) VALUES\n"
            + ",\n".join(chunk)
            + ";"
        )

    script_parts.append(
        f"""DELETE FROM public.dblist AS d
WHERE d.dbmasterid IN ({target_id_list})
  AND NOT EXISTS (
    SELECT 1
    FROM tmp_dblist_import AS t
    WHERE t.address = d.address
  );
UPDATE public.dblist AS d
SET dbmasterid = t.dbmasterid,
    name = t.name,
    type = t.type,
    initvalue = t.initvalue,
    comment = t.comment
FROM tmp_dblist_import AS t
WHERE d.address = t.address;
INSERT INTO public.dblist (dbmasterid, address, name, type, initvalue, comment)
SELECT t.dbmasterid, t.address, t.name, t.type, t.initvalue, t.comment
FROM tmp_dblist_import AS t
WHERE NOT EXISTS (
  SELECT 1
  FROM public.dblist AS d
  WHERE d.address = t.address
);
UPDATE public.dblist
SET id = id + 1000000;
WITH ordered AS (
  SELECT d.id AS old_id, row_number() OVER (ORDER BY t.source_order) AS new_id
  FROM public.dblist AS d
  JOIN tmp_dblist_import AS t ON t.address = d.address
)
UPDATE public.dblist AS d
SET id = o.new_id
FROM ordered AS o
WHERE d.id = o.old_id;
SELECT setval(pg_get_serial_sequence('public.dblist', 'id'), COALESCE((SELECT MAX(id) FROM public.dblist), 1), true);
COMMIT;"""
    )
    run_psql_script("\n".join(script_parts) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(SOURCE_DIR))
    parser.add_argument("--dbsym", action="append", type=int, default=[])
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--check-address", action="append", default=[])
    args = parser.parse_args()

    filter_dbsym = set(args.dbsym) if args.dbsym else None
    rows = collect_rows(Path(args.source_dir), filter_dbsym=filter_dbsym)

    if args.check_address:
        dbmaster_map = fetch_dbmaster_map()
        wanted = set(args.check_address)
        for row in rows:
            if row.address in wanted:
                dbmaster = dbmaster_map.get(row.dbsym)
                if dbmaster is None:
                    continue
                print(
                    f"{row.address}|{prefixed_name(str(dbmaster['dbname']), row.name)}|"
                    f"{row.data_type}|{row.initvalue}|{row.comment}"
                )
        return 0

    dbmaster_map = fetch_dbmaster_map()

    if args.write_db:
        write_to_db(rows)
        print(f"Imported {len(rows)} row(s) into public.dblist")
        return 0

    sys.stdout.write("dbsym,address,name,type,initvalue,comment\n")
    sys.stdout.write(rows_to_csv(rows, dbmaster_map))
    return 0


if __name__ == "__main__":
    sys.exit(main())
