"""Optional admin token for a public demo deployment.

When ADMIN_TOKEN is set, endpoints that spend LLM quota or delete data (upload, analyze,
batches, delete) require the header `X-Admin-Token`. Viewing and reviewing stay open so
visitors can try the reviewer workflow. When it is unset (local use), nothing is checked.
"""

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_token
    if expected and not (x_admin_token and secrets.compare_digest(x_admin_token, expected)):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Uploading, analyzing and deleting are disabled on this public demo. "
            "Browse the seeded contracts and try the review queue instead.",
        )
