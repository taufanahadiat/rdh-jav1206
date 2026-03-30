import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plc.db.db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=317,
            db_name="ExtCox002",
            awl_source_file="/var/www/S7_DB/DB317_ExtCox002.AWL",
        )
    )
