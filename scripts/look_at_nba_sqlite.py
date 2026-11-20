from pathlib import Path
import sqlite3
import pandas as pd

sqlite_conn = sqlite3.connect((Path(__file__).resolve().parents[1] / "data/raw/nba.sqlite").as_uri() + "?mode=ro", uri=True)

tables = pd.read_sql_query("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name NOT LIKE 'sqlite_%'
    ORDER BY name
""", sqlite_conn)

print(tables.to_string(index=False))

for table in tables["name"]:
    columns = pd.read_sql_query(
        f'PRAGMA table_info("{table}")',
        sqlite_conn
    )

    count = sqlite_conn.execute(
        f'SELECT COUNT(*) FROM "{table}"'
    ).fetchone()[0]

    print(f"{table}: {count:,} rows, {len(columns)} columns")