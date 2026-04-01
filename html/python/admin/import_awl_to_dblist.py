#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from awl_import_db import SOURCE_DIR, fetch_dbmaster_map, prefixed_name, rows_to_csv, write_to_db
from awl_import_parser import collect_rows
from systemlog import build_cli_payload, write_event as write_system_event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(SOURCE_DIR))
    parser.add_argument("--dbsym", action="append", type=int, default=[])
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--check-address", action="append", default=[])
    args = parser.parse_args()
    write_system_event(
        service="admin",
        component="import_awl_to_dblist",
        event="script_started",
        payload=build_cli_payload(sys.argv),
        source_file=__file__,
    )

    try:
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
            write_system_event(
                service="admin",
                component="import_awl_to_dblist",
                event="script_completed",
                payload={"mode": "check_address", "row_count": len(rows)},
                source_file=__file__,
                status_code=130,
            )
            return 0

        dbmaster_map = fetch_dbmaster_map()

        if args.write_db:
            write_to_db(rows)
            print(f"Imported {len(rows)} row(s) into public.dblist")
            write_system_event(
                service="admin",
                component="import_awl_to_dblist",
                event="script_completed",
                payload={"mode": "write_db", "row_count": len(rows)},
                source_file=__file__,
                status_code=130,
            )
            return 0

        sys.stdout.write("dbsym,address,name,type,initvalue,comment\n")
        sys.stdout.write(rows_to_csv(rows, dbmaster_map))
        write_system_event(
            service="admin",
            component="import_awl_to_dblist",
            event="script_completed",
            payload={"mode": "csv", "row_count": len(rows)},
            source_file=__file__,
            status_code=130,
        )
        return 0
    except Exception as exc:
        write_system_event(
            service="admin",
            component="import_awl_to_dblist",
            event="script_failed",
            payload={"argv": sys.argv, "message": str(exc)},
            source_file=__file__,
            severity="critical",
            status_code=500,
            message=str(exc),
        )
        raise


if __name__ == "__main__":
    sys.exit(main())
