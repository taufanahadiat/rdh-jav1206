import csv
import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import sys
from awl_import_models import Row

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    PLC_AWL_DIR,
)
from systemlog import write_event as write_system_event


SOURCE_DIR = PLC_AWL_DIR
PSQL_CANDIDATES = [
    os.getenv("PSQL_BIN", "").strip(),
    "/usr/bin/psql",
    "/usr/pgsql-15/bin/psql",
    "/usr/lib/postgresql/15/bin/psql",
]


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


def run_psql(sql: str, stdin_data: Optional[str] = None) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    cmd = [
        PSQL_BIN,
        "-h",
        DB_HOST,
        "-p",
        str(DB_PORT),
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
        write_system_event(
            service="admin",
            component="awl_import_db",
            event="psql_command_failed",
            payload={"sql": sql[:500], "stderr": proc.stderr.strip(), "stdout": proc.stdout.strip()},
            source_file=__file__,
            severity="critical",
            status_code=500,
            message=proc.stderr.strip() or proc.stdout.strip() or "`psql` failed.",
        )
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "`psql` failed.")
    write_system_event(
        service="admin",
        component="awl_import_db",
        event="psql_command_completed",
        payload={"sql": sql[:500]},
        source_file=__file__,
        status_code=130,
    )
    return proc.stdout


def run_psql_script(script: str) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    cmd = [
        PSQL_BIN,
        "-h",
        DB_HOST,
        "-p",
        str(DB_PORT),
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
        write_system_event(
            service="admin",
            component="awl_import_db",
            event="psql_script_failed",
            payload={"script_preview": script[:1000], "stderr": proc.stderr.strip(), "stdout": proc.stdout.strip()},
            source_file=__file__,
            severity="critical",
            status_code=500,
            message=proc.stderr.strip() or proc.stdout.strip() or "The `psql` script failed.",
        )
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "The `psql` script failed.")
    write_system_event(
        service="admin",
        component="awl_import_db",
        event="psql_script_completed",
        payload={"script_length": len(script)},
        source_file=__file__,
        status_code=130,
    )
    return proc.stdout


def fetch_dbmaster_map() -> dict[int, dict]:
    raw = run_psql("SELECT dbsym, id, dbname FROM public.dbmaster ORDER BY dbsym;")
    mapping: dict[int, dict] = {}
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


def rows_to_csv(rows: list[Row], dbmaster_map: dict[int, dict]) -> str:
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


def sql_literal(value: Optional[object]) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def write_to_db(rows: list[Row]) -> None:
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
    write_system_event(
        service="admin",
        component="awl_import_db",
        event="dblist_import_completed",
        payload={"row_count": len(rows), "target_dbmaster_ids": target_ids},
        source_file=__file__,
        status_code=130,
    )
