import os

# Point the app at a separate test database before anything imports app.db.
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://compliance:compliance@localhost:5432/compliance")
TEST_URL = os.environ.get("TEST_DATABASE_URL", ADMIN_URL.rsplit("/", 1)[0] + "/compliance_test")
os.environ["DATABASE_URL"] = TEST_URL

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


@pytest.fixture(scope="session")
def migrated_db():
    """Create the test database if needed and apply all Alembic migrations."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'compliance_test'"))
            if not exists:
                conn.execute(text("CREATE DATABASE compliance_test"))
    except Exception as exc:
        pytest.skip(f"Postgres not reachable ({type(exc).__name__}); run `docker compose up -d db`")
    finally:
        admin.dispose()

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
def client(migrated_db, tmp_path):
    from fastapi.testclient import TestClient

    from app.db import engine
    from app.main import app
    from app.routers.documents import get_storage_dir

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE documents CASCADE"))
    app.dependency_overrides[get_storage_dir] = lambda: tmp_path
    yield TestClient(app)
    app.dependency_overrides.clear()
