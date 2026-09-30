#!/usr/bin/env python
"""Wait until PostgreSQL accepts connections (used by Docker entrypoint)."""
import os
import sys
import time

import psycopg


def main() -> int:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    dbname = os.environ["POSTGRES_DB"]
    user = os.environ["POSTGRES_USER"]
    password = os.environ.get("POSTGRES_PASSWORD", "")

    max_attempts = int(os.environ.get("DB_WAIT_MAX_ATTEMPTS", "30"))
    delay_seconds = float(os.environ.get("DB_WAIT_DELAY_SECONDS", "2"))

    for attempt in range(1, max_attempts + 1):
        try:
            with psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=3,
            ):
                print("Database is ready.", flush=True)
                return 0
        except psycopg.Error as exc:
            print(
                f"Database not ready (attempt {attempt}/{max_attempts}): {exc}",
                flush=True,
            )
            if attempt == max_attempts:
                return 1
            time.sleep(delay_seconds)

    return 1


if __name__ == "__main__":
    sys.exit(main())
