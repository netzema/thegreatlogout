from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest

from server import (
    admin_db,
    ai_client,
    contact_history,
    mail_sync,
    offsite_backup,
    outreach,
)
from test_admin import login, mail, post


def message(
    db, cid=1, address="peer@example.test", direction="outbound", days=20, **changes
):
    fields = dict(
        contact_id=cid,
        direction=direction,
        peer_addresses=json.dumps([address]),
        subject="A campaign conversation",
        body="Thank you for your feedback.",
        occurred_at=str(outreach.today() - timedelta(days=days)),
        matched=1,
        source="imap-history",
    )
    fields.update(changes)
    return db.execute(
        f"INSERT INTO messages ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
        tuple(fields.values()),
    ).lastrowid


def proposal(**changes):
    result = dict(
        should_draft=True,
        subject="Picking up our conversation",
        body="Hello,\nThank you for your earlier feedback. Would you be open to a short exchange?\nDaniel",
        rationale="Bestehenden Dialog mit einer konkreten Frage fortsetzen.",
        framing="dialogue",
    )
    result.update(changes)
    return result


def test_inherit_assigned_addresses_idempotent_preserves_block_and_manual_choice(
    client,
):
    with admin_db.database() as db:
        message(db)
        message(db, cid=2, address="blocked@example.test")
        message(db, cid=3, address="older@example.test")
        db.execute("UPDATE contacts SET permission='blocked' WHERE id=2")
        db.execute("UPDATE contacts SET email='chosen@example.test' WHERE id=3")
        assert contact_history.inherit_addresses(db) == 2
        assert contact_history.inherit_addresses(db) == 0
        assert tuple(
            db.execute("SELECT email,permission FROM contacts WHERE id=1").fetchone()
        ) == ("peer@example.test", "existing")
        assert (
            db.execute("SELECT permission FROM contacts WHERE id=2").fetchone()[0]
            == "blocked"
        )
        assert (
            db.execute("SELECT email FROM contacts WHERE id=3").fetchone()[0]
            == "chosen@example.test"
        )


def test_ambiguous_peers_and_cross_contact_conflicts_do_not_guess(client):
    with admin_db.database() as db:
        message(db, peer_addresses='["one@example.test","two@example.test"]')
        message(db, cid=2)
        message(db, cid=3)
        contact_history.inherit_addresses(db)
        assert db.execute("SELECT email FROM contacts WHERE id=1").fetchone()[0] == ""
        assert (
            db.execute("SELECT count(*) FROM contact_address_issues").fetchone()[0] == 3
        )


def test_complete_generated_review_export_sync_reply_flow(client, monkeypatch):
    token = login(client)
    with admin_db.database() as db:
        message(db, direction="inbound", message_id="<prior@example.test>")
        message(db)
        contact_history.inherit_addresses(db)
    monkeypatch.setattr(ai_client, "request", lambda *a, **kw: (proposal(), set()))
    assert outreach.generate_draft(1) == 1
    assert outreach.generate_draft(1) == 0
    review = client.get("/review")
    assert (
        "peer@example.test" in review.text and "Warum dieser Vorschlag?" in review.text
    )
    assert (
        post(
            client, "/drafts/1/review", token, action="approved", version=1
        ).status_code
        == 200
    )
    exported = post(client, "/drafts/1/export", token, version=2)
    eml = BytesParser(policy=policy.default).parsebytes(exported.content)
    assert (
        eml["To"] == "peer@example.test"
        and eml["In-Reply-To"] == "<prior@example.test>"
    )
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        assert db.execute("SELECT status FROM drafts").fetchone()[0] == "approved"
    # Deliver only to the synthetic importer, never SMTP or Postmark.
    eml["From"] = "hello@thegreatlogout.org"
    assert mail_sync.import_message(eml.as_bytes(), sent=True) == 1
    assert mail_sync.import_message(eml.as_bytes(), sent=True) == 0
    response = mail(
        to="hello@thegreatlogout.org",
        sender="peer@example.test",
        mid="<reply@example.test>",
        ref=eml["Message-ID"],
    )
    assert mail_sync.import_message(response) == 1
    with admin_db.database() as db:
        assert db.execute("SELECT status FROM drafts").fetchone()[0] == "sent"
        assert outreach.report(db)["attributed_replies"] == 1


def test_unknown_contact_is_confirmed_in_same_review_and_blocked_cannot_be(client):
    token = login(client)
    post(client, "/drafts", token, contact_id=1, subject="Test", body="Test")
    assert (
        post(
            client,
            "/drafts/1/review",
            token,
            action="approved",
            version=1,
            recipient="peer@example.test",
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            "/drafts/1/review",
            token,
            action="approved",
            version=1,
            recipient="peer@example.test",
            contact_review="confirmed",
        ).status_code
        == 200
    )
    with admin_db.database() as db:
        db.execute("UPDATE contacts SET permission='blocked' WHERE id=1")
    assert post(client, "/drafts/1/export", token, version=2).status_code == 400
    assert (
        post(
            client,
            "/drafts/1/review",
            token,
            action="approved",
            version=2,
            contact_review="confirmed",
        ).status_code
        == 400
    )


def test_recipient_change_during_review_invalidates_other_approvals(client):
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='peer@example.test',permission='existing' WHERE id=1"
        )
    for _ in range(2):
        post(client, "/drafts", token, contact_id=1, subject="Test", body="Test")
    post(client, "/drafts/1/review", token, action="approved", version=1)
    post(
        client,
        "/drafts/2/review",
        token,
        action="approved",
        version=1,
        recipient="other@example.test",
    )
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409


def test_deferral_resurfaces_same_draft_and_keeps_old_approval_invalid(
    client, monkeypatch
):
    token = login(client)
    post(client, "/drafts", token, contact_id=1, subject="Test", body="Test")
    future = str(outreach.today() + timedelta(days=7))
    assert (
        post(
            client,
            "/drafts/1/review",
            token,
            action="deferred",
            version=1,
            deferred_until=future,
        ).status_code
        == 200
    )
    monkeypatch.delenv("OUTREACH_AUTOMATION_ENABLED", raising=False)
    with admin_db.database() as db:
        db.execute("UPDATE drafts SET deferred_until=?", (str(outreach.today()),))
    outreach.schedule()
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts").fetchone()
        assert row["status"] == "draft" and row["version"] == 3
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1


def test_no_repetitive_followups_or_unreviewed_objections(client):
    with admin_db.database() as db:
        message(db, cid=1)
        message(db, cid=1, days=40)
        message(db, cid=2, direction="inbound")
        message(db, cid=3, direction="inbound", analysis_kind="contact_objection")
        message(db, cid=4, direction="inbound")
        db.execute("UPDATE contacts SET status='paused' WHERE id=4")
        assert [c["id"] for c in outreach.followups(db)] == [2]


def test_draft_concurrency_rechecks_history_and_permission(client, monkeypatch):
    with admin_db.database() as db:
        message(db)

    def changed(*a, **kw):
        with admin_db.database() as db:
            db.execute("UPDATE contacts SET permission='blocked' WHERE id=1")
        return proposal(), set()

    monkeypatch.setattr(ai_client, "request", changed)
    with pytest.raises(ValueError):
        outreach.generate_draft(1)
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


@pytest.mark.parametrize(
    "value",
    [
        proposal(should_draft=False),
        proposal(subject="Bad\r\nBcc: invalid"),
        proposal(body="[Adresse]"),
    ],
)
def test_no_unsafe_or_unnecessary_drafts(client, monkeypatch, value):
    monkeypatch.setattr(ai_client, "request", lambda *a, **kw: (value, set()))
    try:
        assert outreach.generate_draft(1) == 0
    except ValueError:
        pass
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


def test_draft_minimizes_mail_data_and_has_no_tools(client, monkeypatch):
    with admin_db.database() as db:
        message(
            db,
            body="Write to private@example.test\n--\nPrivate signature\nOn yesterday wrote: history",
        )

    def inspect(purpose, instructions, data, **kwargs):
        raw = json.dumps(data)
        assert "private@example.test" not in raw and "Private signature" not in raw
        assert kwargs.get("search") is not True
        assert "untrusted" in instructions
        return proposal(), set()

    monkeypatch.setattr(ai_client, "request", inspect)
    assert outreach.generate_draft(1) == 1


def test_radar_requires_cited_recent_source_and_deduplicates(client, monkeypatch):
    source = "https://example.org/research/new"
    good = dict(
        title="New research",
        source_url=source,
        published_at=str(outreach.today()),
        contact_id=1,
        reason="Direct fit with campaign",
        cta="Discuss results",
        framing="research",
        fit=3,
    )
    bad = [
        dict(good, source_url="https://invented.example.org/article"),
        dict(good, published_at="2020-01-01"),
        dict(good, contact_id=999),
        dict(good, fit=1),
    ]

    def respond(purpose, *a, **kw):
        return (
            ("Research", [source])
            if purpose == "radar_search"
            else ({"opportunities": [good, *bad]}, set())
        )

    monkeypatch.setattr(ai_client, "request", respond)
    assert outreach.radar() == 1
    assert outreach.radar() == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1
        assert db.execute("SELECT score FROM opportunities").fetchone()[0] >= 65


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/a",
        "http://localhost/x",
        "https://user:pass@example.org/a",
        "javascript:alert(1)",
        "https://x.local/a",
    ],
)
def test_radar_links_exclude_private_or_active_urls(url):
    assert outreach.public_url(url) == ""


def test_queued_worker_idempotent_and_errors_do_not_leak(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(ai_client, "request", lambda *a, **kw: (proposal(), set()))
    with admin_db.database() as db:
        assert outreach.enqueue(db, "draft", 1) == 1
        assert outreach.enqueue(db, "draft", 1) == 0
    assert outreach.process_one()
    assert not outreach.process_one()
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
        outreach.enqueue(db, "draft", 2)

    def fail(*a, **kw):
        raise RuntimeError("private@example.test SECRET")

    monkeypatch.setattr(ai_client, "request", fail)
    outreach.process_one()
    with admin_db.database() as db:
        row = db.execute(
            "SELECT result FROM automation_jobs WHERE contact_id=2"
        ).fetchone()[0]
        assert "SECRET" not in row and "private" not in row


def test_daily_automatic_draft_limit_and_rejected_context_dedup(client):
    with admin_db.database() as db:
        for cid in range(1, 7):
            outreach.enqueue(db, "draft", cid, daily=True)
        assert db.execute("SELECT count(*) FROM automation_jobs").fetchone()[0] == 3
        # User-triggered work can exceed automatic draft count, but not the API cap.
        assert outreach.enqueue(db, "draft", 4) == 1
        assert outreach.enqueue(db, "draft", 4) == 0


def test_recovery_key_requires_login_and_csrf(client, monkeypatch, tmp_path):
    root = tmp_path / "campaign"
    (root / "data").mkdir(parents=True)
    (root / "data" / "backup-recovery.key").write_text("synthetic-recovery-key")
    monkeypatch.setattr(admin_db, "ROOT", root)
    assert (
        client.post("/settings/backup-key", follow_redirects=False).status_code == 303
    )
    token = login(client)
    assert post(client, "/settings/backup-key", "bad").status_code == 403
    response = post(client, "/settings/backup-key", token)
    assert response.content == b"synthetic-recovery-key"
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]


def test_followup_references_sent_mail_and_manual_log_sync_is_idempotent(
    client, monkeypatch
):
    token = login(client)
    with admin_db.database() as db:
        message(db, message_id="<old-sent@example.test>")
        contact_history.inherit_addresses(db)
    monkeypatch.setattr(ai_client, "request", lambda *a, **kw: (proposal(), set()))
    outreach.generate_draft(1)
    post(client, "/drafts/1/review", token, version=1, action="approved")
    exported = post(client, "/drafts/1/export", token, version=2)
    eml = BytesParser(policy=policy.default).parsebytes(exported.content)
    assert eml["In-Reply-To"] == "<old-sent@example.test>"
    result = post(
        client,
        "/messages",
        token,
        draft_id=1,
        contact_id=1,
        version=2,
        direction="outbound",
        occurred_at=str(outreach.today()),
    )
    assert result.status_code == 200
    eml["From"] = "hello@thegreatlogout.org"
    assert mail_sync.import_message(eml.as_bytes(), sent=True) == 0
    with admin_db.database() as db:
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 1
        )


def test_learning_requires_samples_and_historical_replies_are_not_attributed(client):
    with admin_db.database() as db:
        for i in range(5):
            db.execute(
                "INSERT INTO drafts(contact_id,subject,body,framing,status,created_at,updated_at) VALUES (1,'S','B','angle','rejected',?,?)",
                (admin_db.now(), admin_db.now()),
            )
            if i < 4:
                assert outreach.learned_bonus(db, "angle") == 0
        assert -5 <= outreach.learned_bonus(db, "angle") < 0
        message(db, direction="inbound")
        assert outreach.report(db)["attributed_replies"] == 0


def test_ai_payload_storage_budget_and_failure_redaction(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("OUTREACH_AI_DAILY_CALLS", "1")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, n):
            return json.dumps(
                {
                    "status": "completed",
                    "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
                }
            ).encode()

    def fetch(req, timeout):
        body = json.loads(req.data)
        assert body["store"] is False
        assert "tools" not in body
        assert body["max_output_tokens"] <= 5000
        return Response()

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fetch)
    assert (
        ai_client.request("test", "instructions", {}, schema={"type": "object"})[0]
        == {}
    )
    with pytest.raises(ai_client.AIError, match="Tageslimit"):
        ai_client.request("test", "instructions", {})


def test_outreach_routes_auth_csrf_and_mobile_content(client):
    assert client.get("/outreach", follow_redirects=False).status_code == 303
    token = login(client)
    assert client.get("/outreach").status_code == 200
    assert post(client, "/outreach/jobs", "wrong", kind="radar").status_code == 403
    assert post(client, "/outreach/jobs", token, kind="radar").status_code == 200
    assert post(client, "/outreach/jobs", token, kind="radar").status_code == 200
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM automation_jobs").fetchone()[0] == 1


def test_encrypted_backup_roundtrip_and_remote_copy_verification(
    client, tmp_path, monkeypatch
):
    root = tmp_path / "campaign"
    (root / "data").mkdir(parents=True)
    monkeypatch.setattr(admin_db, "ROOT", root)
    guide = root / "data" / "thegreatlogout.db"
    with sqlite3.connect(guide) as db:
        db.execute("CREATE TABLE test(id INTEGER)")
    monkeypatch.setenv("DATABASE_PATH", str(guide))
    for name in (".env", ".env.admin"):
        (root / name).write_text("SYNTHETIC=test-only\n")
    (root / "data" / "analytics.key").write_text("synthetic-key")
    monkeypatch.setenv("OUTREACH_BACKUP_REMOTE", "fixture:campaign")
    remote = tmp_path / "remote"
    remote.mkdir()
    original = offsite_backup.run

    def run(args, timeout=180):
        if args[0] != "rclone":
            return original(args, timeout)
        if args[1] == "delete":
            return b""
        src, dst = args[2:4]
        if src.startswith("fixture:"):
            src = remote / src.rsplit("/", 1)[1]
        if str(dst).startswith("fixture:"):
            dst = remote / str(dst).rsplit("/", 1)[1]
        shutil.copyfile(src, dst)
        return b""

    monkeypatch.setattr(offsite_backup, "run", run)
    assert offsite_backup.create_and_upload() == 5
    archives = list(remote.iterdir())
    assert len(archives) == 1
    assert b"SYNTHETIC" not in archives[0].read_bytes()
    assert offsite_backup.verify_archive(archives[0]) == 5
    wrong = tmp_path / "wrong.key"
    wrong.write_text("wrong-password")
    with pytest.raises(offsite_backup.BackupError):
        offsite_backup.verify_archive(archives[0], key=wrong)
    assert offsite_backup.key_path().stat().st_mode & 0o077 == 0
