import pytest
from fastapi.testclient import TestClient
from server import admin, admin_db, analytics, bootstrap_admin

ORIGIN = "https://admin.thegreatlogout.org"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_db, "DB_PATH", tmp_path / "admin.db")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing-guide.db"))
    monkeypatch.setattr(analytics, "KEY_PATH", tmp_path / "analytics.key")
    monkeypatch.setattr(bootstrap_admin, "KEY_PATH", tmp_path / "analytics.key")
    bootstrap_admin.seed()
    with admin_db.database() as db:
        db.execute(
            "INSERT INTO users(email,password_hash) VALUES (?,?)",
            ("admin@example.test", admin.password_hash.hash("a-long-test-password")),
        )
    with TestClient(admin.app, base_url=ORIGIN) as client:
        yield client
