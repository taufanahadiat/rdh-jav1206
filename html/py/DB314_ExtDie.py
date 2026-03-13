import sys

from db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=314,
            db_name="ExtDie",
            awl_source_file="/var/www/S7_DB/DB314_ExtDie.AWL",
        )
    )
