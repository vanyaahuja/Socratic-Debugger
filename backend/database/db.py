"""
Database engine + session factory.

Migration note: the only line that's SQLite-specific is DATABASE_URL and the
`connect_args` below (SQLite needs check_same_thread=False for FastAPI's
threaded request handling; Postgres doesn't). When you migrate, swap
DATABASE_URL to a postgres:// URL, drop connect_args, and nothing else in
the app needs to change -- every other file imports SessionLocal/Base from
here, never sqlite3 directly.

SQLite-specific behavior worth knowing about now (so it doesn't surprise you
later): foreign keys are NOT enforced by default in SQLite unless you turn
them on per-connection (done below via the event listener). Postgres
enforces them always. Without this, you could silently insert an Attempt
with a bogus session_id.
"""

import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Overridable so tests can use a throwaway database.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./socratic_debugger.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. SQLAlchemy's create_all() only creates
# missing *tables*, so an existing socratic_debugger.db would otherwise be
# missing these and every query touching them would fail. This is a deliberately
# tiny stand-in for Alembic: additive ALTER TABLE only, never destructive.
_ADDED_COLUMNS = {
    "users": [("token_hash", "VARCHAR(64)")],
    "problems": [
        ("source", "VARCHAR(20) NOT NULL DEFAULT 'local'"),
        ("external_slug", "VARCHAR(200)"),
        ("external_id", "VARCHAR(20)"),
        ("url", "VARCHAR(300)"),
    ],
    "sessions": [
        ("state", "VARCHAR(20) NOT NULL DEFAULT 'READY'"),
        ("state_updated_at", "DATETIME"),
    ],
    "attempts": [
        ("verdict", "VARCHAR(24)"),
        ("verdict_source", "VARCHAR(16)"),
        ("code_hash", "VARCHAR(64)"),
        ("feedback", "TEXT"),
    ],
}
_ADDED_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_token_hash ON users (token_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_problems_source_slug ON problems (source, external_slug)",
]


def ensure_columns() -> None:
    """Call after Base.metadata.create_all(). Safe to run on every startup."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for stmt in _ADDED_INDEXES:
            conn.execute(text(stmt))
