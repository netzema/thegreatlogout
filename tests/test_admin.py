from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from uuid import uuid4

import pytest

from server import (
    admin,
    admin_db,
    analytics,
    bootstrap_admin,
    mail_analysis,
    mail_sync,
    maintenance,
)

ORIGIN = "https://admin.thegreatlogout.org"


def login(client):
    response = client.post(
        "/login",
        headers={"Origin": ORIGIN},
        data={"email": "admin@example.test", "password": "a-long-test-password"},
    )
    assert response.status_code == 200
    return csrf(response)


def test_review_shows_local_hint_and_escapes_mail_content(client):
    login(client)
    mail = EmailMessage()
    mail["From"] = "unknown@example.test"
    mail["To"] = "hello@thegreatlogout.org"
    mail["Subject"] = "Review fixture"
    mail.set_content("<script>alert(1)</script> Can we talk?")
    mail_sync.import_message(mail.as_bytes())
    mail_analysis.refresh_analysis()
    response = client.get("/review")
    assert response.status_code == 200
    assert "Lokaler Textauszug" in response.text
    assert "Frage erkannt" in response.text
    assert "Kontakt bewusst auswählen" in response.text
    assert "&lt;script&gt;" in response.text
    assert "<script>alert" not in response.text


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text)[1]


def post(client, url, token, **data):
    return client.post(url, headers={"Origin": ORIGIN}, data={"csrf": token, **data})


def test_private_pages_require_login_and_security(client):
    for path in [
        "/",
        "/contacts",
        "/review",
        "/analytics",
        "/guide",
        "/opportunities",
        "/settings",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    assert client.get("/openapi.json", follow_redirects=False).status_code != 200
    assert (
        client.post(
            "/login",
            data={"email": "admin@example.test", "password": "a-long-test-password"},
        ).status_code
        == 403
    )
    response = client.post(
        "/login",
        headers={"Origin": ORIGIN},
        data={"email": "admin@example.test", "password": "a-long-test-password"},
        follow_redirects=False,
    )
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Domain=" not in cookie
    for path in [
        "/",
        "/contacts",
        "/review",
        "/analytics",
        "/guide",
        "/opportunities",
        "/settings",
        "/contacts/1",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert (
        client.post("/contacts", headers={"Origin": ORIGIN}, data={}).status_code == 403
    )
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400


def test_seed_repeats_preserve_changes_and_no_invented_messages(client):
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == 21
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM contacts WHERE notes LIKE '%mehrfach%'"
            ).fetchone()[0]
            == 4
        )
        db.execute("UPDATE contacts SET notes='User edit' WHERE id=1")
    bootstrap_admin.seed()
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == 21
        assert (
            db.execute("SELECT notes FROM contacts WHERE id=1").fetchone()[0]
            == "User edit"
        )


def test_review_stale_approval_edit_invalidation_and_no_send(client):
    token = login(client)
    response = post(
        client,
        "/drafts",
        token,
        contact_id=1,
        subject="A useful question",
        body="<script>unsafe</script>",
    )
    assert "&lt;script&gt;" in response.text and "<script>unsafe" not in response.text
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="approved"
        ).status_code
        == 400
    )
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='recipient@example.test',permission='allowed' WHERE id=1"
        )
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="approved"
        ).status_code
        == 200
    )
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="rejected"
        ).status_code
        == 409
    )
    export = post(client, "/drafts/1/export", token, version=2)
    assert export.status_code == 200 and "X-Unsent: 1" in export.text
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert (
        post(
            client,
            "/drafts",
            token,
            id=1,
            version=2,
            contact_id=1,
            subject="Edited",
            body="New body",
        ).status_code
        == 200
    )
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409
    assert (
        post(
            client, "/drafts/1/review", token, version=3, action="approved"
        ).status_code
        == 200
    )
    result = post(
        client,
        "/messages",
        token,
        contact_id=1,
        draft_id=1,
        version=4,
        direction="outbound",
        occurred_at="2026-10-10",
    )
    assert result.status_code == 200
    assert (
        post(
            client,
            "/messages",
            token,
            contact_id=1,
            draft_id=1,
            version=4,
            direction="outbound",
            occurred_at="2026-10-10",
        ).status_code
        == 409
    )
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_password_change_invalidates_all_sessions(client):
    token = login(client)
    result = post(
        client,
        "/settings/password",
        token,
        old_password="a-long-test-password",
        new_password="a-different-long-password",
    )
    assert result.url.path == "/login"
    assert client.get("/contacts", follow_redirects=False).status_code == 303
    result = client.post(
        "/login",
        headers={"Origin": ORIGIN},
        data={"email": "admin@example.test", "password": "a-different-long-password"},
    )
    assert result.url.path == "/"


def event(**changes):
    value = {
        "event_id": str(uuid4()),
        "visitor_id": str(uuid4()),
        "session_id": str(uuid4()),
        "event_type": "page_view",
        "path": "/de/",
        "device_type": "mobile",
        "source": "direct",
    }
    value.update(changes)
    return value


def test_analytics_consent_origin_dedup_and_no_raw_identifiers(client):
    payload = event()
    headers = {"Origin": "https://thegreatlogout.org"}
    assert (
        client.post("/api/analytics/events", headers=headers, json=payload).status_code
        == 403
    )
    client.cookies.set("tgl_analytics_consent", "granted")
    assert (
        client.post(
            "/api/analytics/events",
            headers={"Origin": "https://admin.netzldatasolutions.at"},
            json=payload,
        ).status_code
        == 403
    )
    for _ in range(2):
        assert (
            client.post(
                "/api/analytics/events", headers=headers, json=payload
            ).status_code
            == 202
        )
    for payload_bad in [
        event(path="/x?email=bad"),
        event(campaign="person@example.test"),
        event(path="/person%40example.test"),
        event(email="person@example.test"),
        event(event_type="engagement", value=None),
    ]:
        assert (
            client.post(
                "/api/analytics/events", headers=headers, json=payload_bad
            ).status_code
            == 422
        )
    with admin_db.database() as db:
        rows = db.execute("SELECT * FROM analytics_events").fetchall()
        assert len(rows) == 1 and rows[0]["visitor_key"] != payload["visitor_id"]
        assert payload["session_id"] not in str(dict(rows[0]))
    report = analytics.report()
    assert report["views"] == report["visits"] == 1


def test_import_analytics_filtered_repeatable_and_source_unchanged(client, tmp_path):
    source = tmp_path / "source.db"
    with admin_db.database() as db:
        schema = db.execute(
            "SELECT sql FROM sqlite_master WHERE name='analytics_events'"
        ).fetchone()[0]
    with sqlite3.connect(source) as db:
        db.execute(schema)
        for site in ["thegreatlogout.org", "netzldatasolutions.at"]:
            db.execute(
                """INSERT INTO analytics_events(event_id,occurred_at,site,event_type,visitor_key,
                session_key,path,source,device_type) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    datetime.now(UTC).replace(tzinfo=None).isoformat(" "),
                    site,
                    "page_view",
                    "oldhash",
                    "oldsession",
                    "/",
                    "direct",
                    "desktop",
                ),
            )
    assert bootstrap_admin.import_analytics(source) == 1
    assert bootstrap_admin.import_analytics(source) == 0
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT count(*) FROM analytics_events").fetchone()[0] == 2
    assert analytics.report()["views"] == 1


def test_retention_and_backup(client, tmp_path):
    with admin_db.database() as db:
        db.execute(
            """INSERT INTO analytics_events(event_id,occurred_at,site,event_type,visitor_key,
            session_key,path,source,device_type) VALUES ('old',?,'thegreatlogout.org','page_view',
            'hash','session','/','direct','desktop')""",
            ((datetime.now(UTC) - timedelta(days=91)).isoformat(),),
        )
    analytics.prune()
    target = tmp_path / "backup.db"
    maintenance.backup(admin_db.DB_PATH, target)
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == 21
        assert db.execute("SELECT count(*) FROM analytics_events").fetchone()[0] == 0
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def mail(
    to="hello@thegreatlogout.org",
    sender="person@example.test",
    mid="<one@example.test>",
    ref=None,
):
    value = EmailMessage()
    value["To"], value["From"], value["Message-ID"] = to, sender, mid
    value["Subject"] = "A reply"
    if ref:
        value["In-Reply-To"] = ref
    value.set_content("Message body")
    return value.as_bytes()


class FakeIMAP:
    def __init__(self, raw):
        self.raw, self.bodies = raw, 0

    def select(self, folder, readonly):
        assert readonly is True
        return "OK", []

    def response(self, kind):
        return kind, [b"123"]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"1"]
        if args[1] == "(BODY.PEEK[])":
            self.bodies += 1
            return "OK", [(b"1", self.raw)]
        assert "HEADER.FIELDS" in args[1]
        return "OK", [(b"1 (RFC822.SIZE 500)", self.raw.split(b"\n\n")[0] + b"\n\n")]


def test_private_mail_never_fetches_body_and_uid_replay(client):
    fake = FakeIMAP(mail(to="private@other.example"))
    assert mail_sync.sync_folder(fake, "INBOX") == 0
    assert fake.bodies == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert mail_sync.sync_folder(fake, "INBOX") == 0
    assert fake.bodies == 0


def test_imap_exact_domain_matching_threading_and_dedup(client):
    fake = FakeIMAP(mail())
    assert mail_sync.sync_folder(fake, "INBOX") == 1
    assert fake.bodies == 1
    assert mail_sync.sync_folder(fake, "INBOX") == 0
    with admin_db.database() as db:
        first = db.execute("SELECT * FROM messages").fetchone()
        assert first["matched"] == 0
        db.execute(
            "UPDATE messages SET contact_id=1,matched=1 WHERE id=?", (first["id"],)
        )
    raw = mail(mid="<two@example.test>", ref="<one@example.test>")
    assert mail_sync.import_message(raw) == 1
    assert mail_sync.import_message(raw) == 0
    with admin_db.database() as db:
        assert (
            db.execute(
                "SELECT contact_id FROM messages WHERE message_id='<two@example.test>'"
            ).fetchone()[0]
            == 1
        )
    for address in [
        "hello@evilthegreatlogout.org",
        "hello@thegreatlogout.org.evil.test",
    ]:
        header = mail_sync.BytesParser(policy=mail_sync.policy.default).parsebytes(
            mail(to=address)
        )
        assert not mail_sync.permitted(header)


def test_changing_recipient_invalidates_approval(client):
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='first@example.test',permission='allowed' WHERE id=1"
        )
    post(client, "/drafts", token, contact_id=1, subject="A request", body="Test body")
    post(client, "/drafts/1/review", token, version=1, action="approved")
    response = post(
        client,
        "/contacts",
        token,
        id=1,
        organization="Test organisation",
        email="second@example.test",
        category="ngo",
        status="contacted",
        permission="allowed",
        priority=2,
    )
    assert response.status_code == 200
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409


def test_reply_review_auto_reply_and_explicit_thread_export(client):
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='person@example.test',permission='allowed' WHERE id=1"
        )
    mail_sync.import_message(mail())
    automatic = mail_sync.BytesParser(policy=mail_sync.policy.default).parsebytes(
        mail(mid="<auto@example.test>")
    )
    automatic["Auto-Submitted"] = "auto-replied"
    mail_sync.import_message(automatic.as_bytes())
    page = client.get("/review")
    assert page.text.count("Neue Antwort") == 1
    post(
        client,
        "/drafts",
        token,
        contact_id=1,
        subject="Re: A reply",
        body="Thanks",
        reply_message_id=1,
    )
    post(client, "/drafts/1/review", token, version=1, action="approved")
    exported = post(client, "/drafts/1/export", token, version=2)
    assert "In-Reply-To: <one@example.test>" in exported.text
    assert (
        post(
            client, "/messages/1/reviewed", token, message_key=stored_message_key(1)
        ).status_code
        == 200
    )
    assert "Neue Antwort" not in client.get("/review").text


def test_login_migration_does_not_overwrite_changed_local_password(client, tmp_path):
    source = tmp_path / "source-users.db"
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE users(email TEXT,password_hash TEXT,is_active INTEGER)"
        )
        db.execute(
            "INSERT INTO users VALUES (?,?,1)",
            (
                "admin@example.test",
                admin.password_hash.hash("source-original-password"),
            ),
        )
    assert bootstrap_admin.import_user(source) == 1
    # Existing campaign credentials take precedence over repeat migration.
    assert login(client)
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def stored_message_key(mid):
    with admin_db.database() as db:
        return admin.message_key(
            db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        )


def import_review_fixture(direction="inbound", mid="<review@example.test>"):
    mail = EmailMessage()
    mail["From"] = (
        "new@example.test" if direction == "inbound" else "hello@thegreatlogout.org"
    )
    mail["To"] = (
        "hello@thegreatlogout.org" if direction == "inbound" else "new@example.test"
    )
    mail["Message-ID"] = mid
    mail["Subject"] = "Review actions"
    mail.set_content("A synthetic conversation")
    mail_sync.import_message(mail.as_bytes(), sent=direction == "outbound")
    with admin_db.database() as db:
        row = db.execute(
            "SELECT id FROM messages WHERE message_id=?", (mid,)
        ).fetchone()
    return row[0], mail.as_bytes()


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
def test_new_contact_from_review_is_atomic_and_inherits_existing_outreach(
    direction, client
):
    token = login(client)
    mid, _ = import_review_fixture(direction)
    response = client.get("/review")
    assert "Neuen Kontakt anlegen" in response.text
    assert 'value="new@example.test"' in response.text
    data = {
        "message_id": mid,
        "message_key": stored_message_key(mid),
        "organization": "New organization",
        "email": "new@example.test",
        "category": "ngo",
        "status": "dialogue" if direction == "inbound" else "contacted",
        "permission": "unknown",
        "priority": 2,
    }
    assert post(client, "/contacts", token, **data).status_code == 200
    with admin_db.database() as db:
        row = db.execute(
            "SELECT c.*,m.matched FROM contacts c JOIN messages m ON c.id=m.contact_id WHERE m.id=?",
            (mid,),
        ).fetchone()
        assert row["organization"] == "New organization" and row["matched"] == 1
        assert row["permission"] == (
            "existing" if direction == "outbound" else "unknown"
        )
        count = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
    assert post(client, "/contacts", token, **data).status_code == 409
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == count


def test_new_contact_duplicate_address_does_not_lose_message(client):
    token = login(client)
    mid, _ = import_review_fixture()
    with admin_db.database() as db:
        db.execute("UPDATE contacts SET email='existing@example.test' WHERE id=1")
    response = post(
        client,
        "/contacts",
        token,
        message_id=mid,
        message_key=stored_message_key(mid),
        organization="Duplicate",
        email="EXISTING@example.test",
        category="ngo",
        status="contacted",
        permission="unknown",
        priority=2,
    )
    assert response.status_code == 409
    with admin_db.database() as db:
        assert (
            db.execute("SELECT matched FROM messages WHERE id=?", (mid,)).fetchone()[0]
            == 0
        )
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == 21


def test_remove_requires_confirmation_blocks_reimport_and_stale_form(client):
    token = login(client)
    mid, raw = import_review_fixture()
    key = stored_message_key(mid)
    assert client.get(f"/messages/{mid}/remove").status_code == 405
    assert (
        post(
            client,
            f"/messages/{mid}/remove",
            "bad-token",
            message_key=key,
            confirm="remove",
        ).status_code
        == 403
    )
    assert (
        post(client, f"/messages/{mid}/remove", token, message_key=key).status_code
        == 400
    )
    assert (
        post(
            client, f"/messages/{mid}/remove", token, message_key=key, confirm="remove"
        ).status_code
        == 200
    )
    assert mail_sync.import_message(raw) == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        marker = dict(db.execute("SELECT * FROM excluded_messages").fetchone())
        assert set(marker) == {"fingerprint", "created_at"}
        assert len(marker["fingerprint"]) == 64
    new_id, _ = import_review_fixture(mid="<different@example.test>")
    assert new_id == mid  # SQLite can reuse a deleted row ID; the form must not.
    assert (
        post(
            client, f"/messages/{mid}/remove", token, message_key=key, confirm="remove"
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            "/contacts",
            token,
            message_id=mid,
            message_key=key,
            organization="Wrong",
            email="",
            category="ngo",
            status="researched",
            permission="unknown",
            priority=2,
        ).status_code
        == 409
    )
    assert (
        post(client, f"/messages/{mid}/reviewed", token, message_key=key).status_code
        == 409
    )
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_remove_matched_reply_invalidates_draft_approval(client):
    token = login(client)
    mid, _ = import_review_fixture()
    key = stored_message_key(mid)
    assert (
        post(
            client, f"/messages/{mid}/match", token, message_key=key, contact_id=1
        ).status_code
        == 200
    )
    assert (
        post(
            client, f"/messages/{mid}/match", token, message_key=key, contact_id=2
        ).status_code
        == 409
    )
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='new@example.test',permission='allowed' WHERE id=1"
        )
    post(
        client,
        "/drafts",
        token,
        contact_id=1,
        reply_message_id=mid,
        subject="Reply",
        body="Reviewed draft",
    )
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="approved"
        ).status_code
        == 200
    )
    assert "Nachricht entfernen" in client.get("/contacts/1").text
    assert (
        post(
            client, f"/messages/{mid}/remove", token, message_key=key, confirm="remove"
        ).status_code
        == 200
    )
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts WHERE id=1").fetchone()
        assert (
            row["status"] == "draft"
            and row["reply_message_id"] is None
            and row["version"] == 3
        )
        assert row["body"] == "Reviewed draft"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409


def test_dashboard_counts_only_actionable_replies(client):
    login(client)
    with admin_db.database() as db:
        for matched, automated, reviewed, direction in [
            (1, 0, None, "inbound"),
            (1, 0, admin_db.now(), "inbound"),
            (1, 1, None, "inbound"),
            (0, 0, None, "inbound"),
            (1, 0, None, "outbound"),
        ]:
            db.execute(
                "INSERT INTO messages(contact_id,direction,subject,body,occurred_at,"
                "matched,automated,reviewed_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    1 if matched else None,
                    direction,
                    "Dashboard fixture",
                    "Synthetic message",
                    admin_db.now(),
                    matched,
                    automated,
                    reviewed,
                ),
            )
    response = client.get("/")
    assert response.context["counts"]["answers"] == 1
    assert response.context["counts"]["unmatched"] == 1
    assert len(client.get("/review").context["replies"]) == 1
