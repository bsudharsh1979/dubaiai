from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP = Path(tempfile.gettempdir()) / f"rainready-test-{uuid.uuid4().hex[:8]}"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["ATTACHMENTS_DIR"] = str(_TMP / "attachments")
os.environ["RASTERS_DIR"] = str(_TMP / "rasters")
os.environ["WORKER_ENABLED"] = "false"
os.environ["MODEL_PROVIDER"] = "demo"
os.environ["DATA_MODE"] = "synthetic"
os.environ["APPROVAL_TTL_MINUTES"] = "30"

from fastapi.testclient import TestClient  # noqa: E402

from rainready import worker  # noqa: E402
from rainready.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client: TestClient, user_id: str) -> None:
    client.cookies.clear()
    r = client.post("/api/auth/demo-login", json={"user_id": user_id})
    assert r.status_code == 200, r.text


def drain(max_rounds: int = 10) -> int:
    """Run the worker synchronously until no due jobs remain."""
    total = 0
    for _ in range(max_rounds):
        n = worker.tick_once()
        total += n
        if n == 0:
            break
    return total


@pytest.fixture
def as_user(client):
    def _f(uid: str):
        login(client, uid)
        return client
    return _f
