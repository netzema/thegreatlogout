import json

from server import admin_db, contact_research, preparation
from test_admin import login, post


def seed_draft(status="needs_review", *, opportunity=False, checked_version=1):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='recipient@example.test',permission='allowed' WHERE id=1"
        )
        oid = None
        if opportunity:
            oid = db.execute(
                """INSERT INTO opportunities
                (contact_id,title,reason,created_at,preparation_state)
                VALUES (1,'A public discussion','A relevant question',?,'ready')""",
                (admin_db.now(),),
            ).lastrowid
        did = db.execute(
            """INSERT INTO drafts
            (contact_id,opportunity_id,subject,body,rationale,editorial_status,
            editorial_report,editorial_version,created_at,updated_at)
            VALUES (1,?,'A question','Previous draft','Relevant source',?,?,?,?,?)""",
            (
                oid,
                status,
                json.dumps(
                    {
                        "summary": "Die Frage verlangt zu viel Vorarbeit.",
                        "issues": [
                            {
                                "category": "request",
                                "passage": "<script>Bitte evaluieren</script>",
                                "instruction": "Eine konkrete, leicht beantwortbare Frage stellen.",
                            }
                        ],
                    }
                ),
                checked_version,
                admin_db.now(),
                admin_db.now(),
            ),
        ).lastrowid
        if oid:
            db.execute(
                "UPDATE opportunities SET preparation_draft_id=? WHERE id=?", (did, oid)
            )
        return did, oid


def test_review_shows_current_issues_and_stale_audit(client):
    login(client)
    did, _ = seed_draft()
    html = client.get("/review").text
    assert "Text braucht Überarbeitung" in html
    assert "Die Frage verlangt zu viel Vorarbeit." in html
    assert "Eine konkrete, leicht beantwortbare Frage stellen." in html
    assert "&lt;script&gt;Bitte evaluieren&lt;/script&gt;" in html
    assert "<script>Bitte evaluieren</script>" not in html
    assert 'value="approved" disabled' in html
    with admin_db.database() as db:
        db.execute("UPDATE drafts SET version=2 WHERE id=?", (did,))
    html = client.get("/review").text
    assert "Textprüfung nicht mehr aktuell" in html
    assert "Die Frage verlangt zu viel Vorarbeit." not in html


def test_manual_edit_archives_original_and_invalidates_editorial_result(client):
    token = login(client)
    did, _ = seed_draft()
    response = post(
        client, "/drafts", token, id=did, contact_id=1, version=1,
        subject="A clear question", body="New personal draft",
    )
    assert response.status_code == 200
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
        assert draft["version"] == 2
        assert draft["body"] == "New personal draft"
        assert draft["editorial_status"] == ""
        assert draft["editorial_report"] == "{}"
        assert draft["editorial_version"] == 0
        original = db.execute("SELECT * FROM draft_revisions").fetchone()
        assert original["draft_id"] == did
        assert original["version"] == 1
        assert original["subject"] == "A question"
        assert original["body"] == "Previous draft"
        assert original["rationale"] == "Relevant source"
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM outreach_deliveries").fetchone()[0] == 0
    stale = post(
        client, "/drafts", token, id=did, contact_id=1, version=1,
        subject="Stale question", body="Stale draft",
    )
    assert stale.status_code == 409
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM draft_revisions").fetchone()[0] == 1


def test_approval_preserves_current_text_assessment_without_sending(client):
    token = login(client)
    did, _ = seed_draft("ready")
    response = post(
        client, f"/drafts/{did}/review", token, version=1, action="approved"
    )
    assert response.status_code == 200
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
        assert draft["version"] == draft["editorial_version"] == 2
        assert draft["status"] == "approved"
        assert draft["editorial_status"] == "ready"
        assert db.execute("SELECT count(*) FROM outreach_deliveries").fetchone()[0] == 0


def test_preparation_keeps_unresolved_text_visible_until_manual_edit(client, monkeypatch):
    token = login(client)
    did, oid = seed_draft(opportunity=True)
    monkeypatch.setattr(contact_research, "enrich", lambda cid: True)
    assert preparation.run(1, oid) == 0
    with admin_db.database() as db:
        preparation.refresh(db)
        row = db.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
        assert row["preparation_state"] == "needs_attention"
        assert row["preparation_note"] == "Die Frage verlangt zu viel Vorarbeit."
    assert post(
        client, "/drafts", token, id=did, contact_id=1, version=1,
        subject="A clear question", body="A human revision",
    ).status_code == 200
    with admin_db.database() as db:
        preparation.refresh(db)
        assert db.execute(
            "SELECT preparation_state FROM opportunities WHERE id=?", (oid,)
        ).fetchone()[0] == "ready"


def test_stale_editorial_result_never_becomes_ready(client):
    _, oid = seed_draft("ready", opportunity=True, checked_version=0)
    with admin_db.database() as db:
        preparation.refresh(db)
        row = db.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
        assert row["preparation_state"] == "needs_attention"
        assert "älteren Version" in row["preparation_note"]
