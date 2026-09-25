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

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./socratic_debugger.db"

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
