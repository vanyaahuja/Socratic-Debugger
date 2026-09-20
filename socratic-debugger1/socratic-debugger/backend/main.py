from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.db import Base, engine
import models  # noqa: F401 -- import so Base.metadata knows about all tables
from api import problems, sessions, attempts, tutor, users

app = FastAPI(title="Socratic Debugger")

app.add_middleware(
    CORSMiddleware,
    # NOTE: allow_origins=["*"] is fine for local/dev use (this app has no
    # auth/cookies yet). In a cloud IDE, the frontend's forwarded URL is
    # unpredictable, so pinning to one origin like localhost:5173 breaks
    # things. Tighten this to your actual frontend origin(s) before any
    # real deployment.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # SQLite convenience: create tables if they don't exist. Replace with
    # Alembic migrations before this ever touches Postgres/production.
    Base.metadata.create_all(bind=engine)


app.include_router(problems.router)
app.include_router(sessions.router)
app.include_router(attempts.router)
app.include_router(tutor.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}
