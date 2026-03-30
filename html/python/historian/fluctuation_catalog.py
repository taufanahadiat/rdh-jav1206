import re
from typing import Any

from historian.config import (
    FUNCTION_BODY_RE,
    HISTORIAN_EXTRA_FUNCTIONS,
    HISTORIAN_MASTER_NAME,
    MASTER_CALL_RE,
    SCL_SOURCE_PATH,
    SYMBOL_TOKEN_RE,
    normalize_text,
)


def extract_function_body(scl_text: str, function_name: str) -> str:
    match = re.search(FUNCTION_BODY_RE.format(name=re.escape(function_name)), scl_text, re.S)
    if match is None:
        raise RuntimeError(f"Function body not found in SCL: {function_name}")
    return match.group("body")


def extract_active_fluctuation_functions(scl_text: str) -> list[str]:
    master_body = extract_function_body(scl_text, HISTORIAN_MASTER_NAME)
    function_names: list[str] = []

    for line in master_body.splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("//"):
            continue

        match = MASTER_CALL_RE.search(stripped)
        if match is None:
            continue

        function_name = match.group("name")
        if function_name == HISTORIAN_MASTER_NAME or function_name in function_names:
            continue
        function_names.append(function_name)

    if not function_names:
        raise RuntimeError("No active FC_Fluct functions found in FC_Fluct_Master.")

    for function_name in HISTORIAN_EXTRA_FUNCTIONS:
        try:
            extract_function_body(scl_text, function_name)
        except RuntimeError:
            continue
        if function_name not in function_names:
            function_names.append(function_name)

    return function_names


def normalize_symbolic_name(lhs: str) -> str:
    parts: list[str] = []

    for token in SYMBOL_TOKEN_RE.finditer(lhs):
        quoted = token.group(1)
        bare = token.group(2)
        index_token = token.group(3)

        if quoted is not None:
            if quoted.isdigit():
                return ""
            parts.append(quoted)
            continue

        if bare is not None:
            parts.append(bare)
            continue

        if index_token is not None and parts:
            index_value = int(index_token[1:-1])
            parts[-1] = f"{parts[-1]}[{index_value}]"

    return ".".join(parts)


def extract_fluctuation_symbolic_names(scl_text: str, function_names: list[str]) -> list[str]:
    symbolic_names: list[str] = []

    for function_name in function_names:
        body = extract_function_body(scl_text, function_name)
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith('"') or ":=" not in stripped:
                continue

            lhs = stripped.split(":=", 1)[0].strip()
            normalized = normalize_symbolic_name(lhs)
            if normalized == "" or normalized in symbolic_names:
                continue
            symbolic_names.append(normalized)

    return symbolic_names


def load_rtagroll_catalog(conn) -> dict[str, Any]:
    scl_text = SCL_SOURCE_PATH.read_text(encoding="utf-8", errors="ignore")
    function_names = extract_active_fluctuation_functions(scl_text)
    symbolic_names = extract_fluctuation_symbolic_names(scl_text, function_names)
    if not symbolic_names:
        raise RuntimeError("No fluctuation symbolic tags were extracted from SCL source.")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, address, name, type
            FROM public.dblist
            WHERE name = ANY(%s)
            ORDER BY id
            """,
            (symbolic_names,),
        )
        rows = cur.fetchall()

    entries: list[dict[str, Any]] = []
    found_names: set[str] = set()
    for row in rows:
        dbid = int(row[0])
        address = normalize_text(row[1])
        name = normalize_text(row[2])
        value_type = normalize_text(row[3])
        if address == "" or name == "":
            continue
        entries.append(
            {
                "dbid": dbid,
                "address": address,
                "name": name,
                "type": value_type,
            }
        )
        found_names.add(name)

    missing_names = [name for name in symbolic_names if name not in found_names]
    db_numbers = sorted({int(entry["address"].split(".", 1)[0][2:]) for entry in entries})

    return {
        "entries": entries,
        "missing_names": missing_names,
        "function_names": function_names,
        "symbolic_names": symbolic_names,
        "db_numbers": db_numbers,
    }
