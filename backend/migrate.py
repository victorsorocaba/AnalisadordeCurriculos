"""Apply numbered SQL migrations before starting the API."""

from pathlib import Path

import psycopg
from dotenv import load_dotenv
from backend.storage import _database_url


def migrate() -> None:
    load_dotenv()
    url = _database_url()
    if not url:
        print("PostgreSQL não configurado; migrações ignoradas.")
        return
    folder = Path(__file__).resolve().parent.parent / "migrations"
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(55261741)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            current = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(folder.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in current:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                print(f"Migração {version} aplicada")


if __name__ == "__main__":
    migrate()
