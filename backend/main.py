import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.db import Base, engine, ensure_columns
import models  # noqa: F401 -- import so Base.metadata knows about all tables
from api import problems, sessions, attempts, tutor, users, leetcode

app = FastAPI(title="Socratic Debugger")

# Only the local dev UI and Chrome extension pages may call the API from a
# browser. (Extension pages also bypass CORS via host_permissions; this keeps
# arbitrary websites out.) Add more origins with CORS_EXTRA_ORIGINS=a,b.
_extra = [o.strip() for o in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *_extra],
    allow_origin_regex=r"^chrome-extension://[a-z]{32}$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # SQLite convenience: create tables if they don't exist. Replace with
    # Alembic migrations before this ever touches Postgres/production.
    Base.metadata.create_all(bind=engine)
    ensure_columns()  # adds new columns to an existing database file


app.include_router(problems.router)
app.include_router(sessions.router)
app.include_router(attempts.router)
app.include_router(tutor.router)
app.include_router(users.router)
app.include_router(leetcode.router)


@app.get("/health")
def health():
    return {"status": "ok"}
