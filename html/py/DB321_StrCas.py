import sys

from db_awl_reader import run_db_reader


if __name__ == "__main__":
    sys.exit(
        run_db_reader(
            db_num=321,
            db_name="StrCas",
            awl_source_file="/var/www/S7_DB/DB321_StrCas.AWL",
        )
    )
