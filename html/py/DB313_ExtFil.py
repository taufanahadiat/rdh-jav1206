import sys

from db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=313,
            db_name="ExtFil",
            awl_source_file="/var/www/S7_DB/DB313_ExtFil.AWL",
        )
    )
