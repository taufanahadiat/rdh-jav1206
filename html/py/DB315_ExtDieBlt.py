import sys

from db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=315,
            db_name="ExtDieBlt",
            awl_source_file="/var/www/S7_DB/DB315_ExtDieBlt.AWL",
        )
    )
