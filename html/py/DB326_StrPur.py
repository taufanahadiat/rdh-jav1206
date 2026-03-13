import sys

from db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=326,
            db_name="StrPur",
            awl_source_file="/var/www/S7_DB/DB326_StrPur.AWL",
        )
    )
