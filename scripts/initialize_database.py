"""Create the SQLite database and all tables.

Usage:
    python -m scripts.initialize_database
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, database  # noqa: E402


def main() -> None:
    database.initialize()
    counts = database.table_counts()
    print(f"Initialized database at {config.DB_PATH}")
    print("Table row counts:")
    for table, n in counts.items():
        print(f"  {table:20s} {n}")


if __name__ == "__main__":
    main()
