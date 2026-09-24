from __future__ import annotations

import sqlite3
import time

from fastapi.testclient import TestClient

import server.app as service


ORIGIN = "https://thegreatlogout.org"


def make_client(tmp_path, monkeypatch):
    database_path = tmp_path / "thegreatlogout.db"
    sent_messages: list[dict] = []

    def fake_send(_token, payload):
        sent_messages.append(payload)
        return {"MessageID": "test-message-id"}

    monkeypatch.setattr(service, "DATABASE_PATH", database_path)
    monkeypatch.setattr(service, "POSTMARK_SERVER_TOKEN", "test-token")
    monkeypatch.setattr(service, "MIN_FILL_SECONDS", 0)
    monkeypatch.setattr(service, "send_postmark_message", fake_send)
    return TestClient(service.app), database_path, sent_messages


def signup_payload(**overrides):
    payload = {
        "email": "person@example.com",
        "firstName": "Alex",
        "logoutDate": "2026-10-01",
        "guideLength": 7,
        "language": "en",
        "consent": True,
        "website": "",
        "startedAt": int(time.time() * 1000) - 3000,
    }
    payload.update(overrides)
    return payload


def test_signup_schedules_sequence_and_sends_welcome(tmp_path, monkeypatch):
    client, database_path, sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        response = client.post(
            "/api/guide/subscribe",
            headers={"Origin": ORIGIN},
            json=signup_payload(),
        )

    assert response.status_code == 202
    assert response.json() == {"ok": True}
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "person@example.com"
    assert sent_messages[0]["TrackOpens"] is False
    assert sent_messages[0]["TrackLinks"] == "None"

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0] == 1
        scheduled = connection.execute("SELECT COUNT(*) FROM email_sends").fetchone()[0]
        sent = connection.execute(
            "SELECT COUNT(*) FROM email_sends WHERE sent_at IS NOT NULL"
        ).fetchone()[0]
    assert scheduled == 25
    assert sent == 1


def test_duplicate_active_signup_is_idempotent(tmp_path, monkeypatch):
    client, database_path, sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        first = client.post(
            "/subscribe", headers={"Origin": ORIGIN}, json=signup_payload()
        )
        second = client.post(
            "/subscribe", headers={"Origin": ORIGIN}, json=signup_payload()
        )

    assert first.status_code == second.status_code == 202
    assert len(sent_messages) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0] == 1


def test_honeypot_accepts_without_storing(tmp_path, monkeypatch):
    client, database_path, sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        response = client.post(
            "/api/guide/subscribe",
            headers={"Origin": ORIGIN},
            json=signup_payload(website="https://spam.invalid"),
        )

    assert response.status_code == 202
    assert sent_messages == []
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0] == 0


def test_disallowed_origin_is_rejected(tmp_path, monkeypatch):
    client, _database_path, sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        response = client.post(
            "/api/guide/subscribe",
            headers={"Origin": "https://attacker.invalid"},
            json=signup_payload(),
        )

    assert response.status_code == 403
    assert sent_messages == []


def test_unsubscribe_stops_future_messages(tmp_path, monkeypatch):
    client, database_path, _sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        client.post(
            "/api/guide/subscribe",
            headers={"Origin": ORIGIN},
            json=signup_payload(language="de"),
        )
        with sqlite3.connect(database_path) as connection:
            token = connection.execute(
                "SELECT unsubscribe_token FROM subscribers"
            ).fetchone()[0]
        response = client.get("/api/guide/unsubscribe", params={"token": token})

    assert response.status_code == 200
    assert "Du bist abgemeldet" in response.text
    with sqlite3.connect(database_path) as connection:
        status = connection.execute("SELECT status FROM subscribers").fetchone()[0]
    assert status == "unsubscribed"


def test_post_svg_escapes_user_text(tmp_path, monkeypatch):
    client, _database_path, _sent_messages = make_client(tmp_path, monkeypatch)

    with client:
        response = client.get(
            "/api/guide/post.svg",
            params={"text": "<script>alert(1)</script>", "format": "vertical"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'height="1920"' in response.text
