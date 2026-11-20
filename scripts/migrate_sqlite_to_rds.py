"""Copy SQLite tables and rows to a new MySQL database on an existing RDS instance.

Install: python -m pip install sqlalchemy pymysql
Run:     python scripts/migrate_sqlite_to_rds.py

Copies columns and data, not indexes, keys, defaults, views, or triggers.
The destination database must not already exist. If a run fails, choose a
different database name for a fresh attempt; partial results are left in place.
"""

import getpass
import os
from pathlib import Path
import re
import sqlite3

from sqlalchemy import Column, MetaData, Table, create_engine, func, select
from sqlalchemy.dialects.mysql import BIGINT, DOUBLE, LONGBLOB, LONGTEXT
from sqlalchemy.engine import URL


SQLITE_PATH = Path(__file__).resolve().parents[1] / "data/raw/nba.sqlite"
RDS_HOST = os.environ.get("RDS_HOST", "").strip()
RDS_USER = os.environ.get("RDS_USER", "").strip()
BATCH_SIZE = 1000


def mysql_type(sqlite_type):
    """Map SQLite storage affinities to broad MySQL data types."""
    declared_type = sqlite_type.upper()
    if "INT" in declared_type:
        return BIGINT()
    if any(word in declared_type for word in ("CHAR", "CLOB", "TEXT")):
        return LONGTEXT()
    if "BLOB" in declared_type or not declared_type:
        return LONGBLOB()
    if any(word in declared_type for word in ("REAL", "FLOA", "DOUB")):
        return DOUBLE()
    # Keep numeric/date-like declarations as text to avoid guessing precision
    # or parsing dates. These columns can be typed deliberately after copying.
    return LONGTEXT()


def main():
    # 1. Choose the source file and the new database name.
    if not SQLITE_PATH.is_file():
        raise FileNotFoundError(SQLITE_PATH)

    database = input("New MySQL database name [nba_source]: ").strip() or "nba_source"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", database):
        raise ValueError("Use a letter first, then letters, numbers, or underscores (max 64).")

    # 2. Connect to the existing RDS server without selecting a database yet.
    url = URL.create(
        "mysql+pymysql",
        username=RDS_USER or input("RDS user: ").strip(),
        password=getpass.getpass("MySQL password: "),
        host=RDS_HOST or input("RDS host: ").strip(),
        port=3306,
        query={"charset": "utf8mb4"},
    )
    server = create_engine(url, pool_pre_ping=True)
    source = sqlite3.connect(SQLITE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    destination = None
    try:
        # Hold one read snapshot for consistent counts and rows throughout.
        source.execute("BEGIN")
        tables = source.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if not tables:
            raise ValueError("The SQLite file contains no user tables.")

        # 3. Create a new database. Stop if that name already exists.
        with server.begin() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")

        destination = create_engine(url.set(database=database), pool_pre_ping=True)
        print(f"Created {database}. Copying {len(tables)} tables.", flush=True)

        # 4. Copy each table, including tables with no rows.
        for (table_name,) in tables:
            quoted_name = '"' + table_name.replace('"', '""') + '"'
            columns = source.execute(f"PRAGMA table_info({quoted_name})").fetchall()

            mysql_table = Table(table_name, MetaData())
            column_names = []
            for column in columns:
                # SQLite PRAGMA returns the name and declared type in positions 1 and 2.
                column_name = column[1]
                column_type = mysql_type(column[2])
                mysql_table.append_column(Column(column_name, column_type))
                column_names.append(column_name)

            source_count = source.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()[0]
            cursor = source.execute(f"SELECT * FROM {quoted_name}")
            copied_rows = 0
            mysql_table.create(destination, checkfirst=False)

            with destination.begin() as conn:
                while True:
                    rows = cursor.fetchmany(BATCH_SIZE)
                    if not rows:
                        break

                    records = [dict(zip(column_names, row)) for row in rows]
                    conn.execute(mysql_table.insert(), records)
                    copied_rows += len(rows)
                    print(f"{table_name}: {copied_rows:,} / {source_count:,} rows", flush=True)

                # 5. Check the row count before committing this table's inserts.
                count_query = select(func.count()).select_from(mysql_table)
                target_count = conn.execute(count_query).scalar_one()
                if target_count != source_count:
                    raise RuntimeError(
                        f"{table_name}: expected {source_count} rows, found {target_count}"
                    )
            print(f"Verified {table_name}: {target_count:,} rows", flush=True)

        print(f"Migration completed and row counts verified: {database}")
    finally:
        source.close()
        server.dispose()
        if destination is not None:
            destination.dispose()


if __name__ == "__main__":
    main()
