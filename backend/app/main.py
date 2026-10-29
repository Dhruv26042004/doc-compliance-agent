from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import check_database
from app.routers import batches, documents, metrics, reviews

app = FastAPI(
    title="Document Compliance API",
    version="0.1.0",
    description="Checks contracts against a numbered policy and routes uncertain cases to reviewers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_origin_regex=get_settings().cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(reviews.router)
app.include_router(metrics.router)
app.include_router(batches.router)


@app.get("/health")
def health() -> dict:
    db = check_database()
    return {"status": "ok" if db["connected"] else "degraded", "database": db}
