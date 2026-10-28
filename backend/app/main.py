from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import check_database

app = FastAPI(
    title="Document Compliance API",
    version="0.1.0",
    description="Checks contracts against a numbered policy and routes uncertain cases to reviewers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    db = check_database()
    return {"status": "ok" if db["connected"] else "degraded", "database": db}
