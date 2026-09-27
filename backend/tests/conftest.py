import os
import tempfile

# Must be set before app modules are imported (engine is created at import).
os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="vgvault-test-")
os.environ.pop("DATABASE_URL", None)

import pytest
from fastapi.testclient import TestClient

from app.core.db import Base, engine
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:  # runs lifespan: migrations + seed
        yield c
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")


@pytest.fixture
def admin(client):
    r = client.post("/api/setup", json={"username": "admin", "password": "password123"})
    assert r.status_code == 201
    return client


def login(client, username, password="password123"):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
