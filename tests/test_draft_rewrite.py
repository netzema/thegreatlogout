import json

import pytest

from server import admin_db, draft_editor, draft_rewrite, mail_threads, outreach


@pytest.fixture
def draft_db(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_db, "DB_PATH", tmp_path / "drafts.db")
    admin_db.ensure_schema()
    with admin_db.database() as db:
        db.execute(
            "INSERT INTO contacts(id,organization,email,created_at,updated_at) "
            "VALUES (1,'Beispiel','person@example.test',?,?)",
            (admin_db.now(), admin_db.now()),
        )
        db.execute(
            "INSERT INTO drafts(id,contact_id,subject,body,rationale,original_body,created_at,updated_at) "
            "VALUES (1,1,'Alt','Hallo, ich möchte Ihnen eine Frage stellen.','Alt','Ursprünglich',?,?)",
            (admin_db.now(), admin_db.now()),
        )


def outcome(status="ready"):
    return draft_editor.Outcome(
        candidate={
            "should_draft": True,
            "subject": "Neu",
            "body": "Hallo,\n\nich habe eine konkrete Frage.\nDaniel",
            "framing": "dialogue",
            "rationale": "Konkreter Bezug.",
        },
        status=status,
        review={"summary": "Text geprüft.", "issues": []},
        rounds=1,
    )


def test_rewrite_archives_and_never_approves_or_changes_original(draft_db, monkeypatch):
    monkeypatch.setattr(draft_editor, "run", lambda *a, **kw: outcome())
    assert draft_rewrite.rewrite(1) == "ready"
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts WHERE id=1").fetchone()
        assert (row["version"], row["status"], row["editorial_version"]) == (
            2,
            "draft",
            2,
        )
        assert row["body"] == outcome().candidate["body"]
        assert row["original_body"] == "Ursprünglich"
        old = db.execute("SELECT * FROM draft_revisions").fetchone()
        assert old["body"] == "Hallo, ich möchte Ihnen eine Frage stellen."
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM outreach_deliveries").fetchone()[0] == 0
    monkeypatch.setattr(
        draft_editor, "run", lambda *a, **kw: pytest.fail("Repeated review")
    )
    assert draft_rewrite.rewrite(1) == "ready"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE drafts SET version=version+1 WHERE id=1",
        "UPDATE contacts SET email='other@example.test' WHERE id=1",
        "UPDATE contacts SET permission='blocked' WHERE id=1",
        "UPDATE contacts SET notes='New context' WHERE id=1",
        "UPDATE drafts SET status='sent' WHERE id=1",
    ],
)
def test_rewrite_rejects_changed_context(draft_db, monkeypatch, change):
    def mutate(*a, **kw):
        with admin_db.database() as db:
            db.execute(change)
        return outcome()

    monkeypatch.setattr(draft_editor, "run", mutate)
    with pytest.raises(ValueError):
        draft_rewrite.rewrite(1)
    with admin_db.database() as db:
        assert db.execute("SELECT subject FROM drafts").fetchone()[0] == "Alt"
        assert db.execute("SELECT count(*) FROM draft_revisions").fetchone()[0] == 0


def test_rewrite_keeps_pinned_conversation_and_held_occasion(draft_db, monkeypatch):
    with admin_db.database() as db:
        for mid in (1, 2):
            db.execute(
                "INSERT INTO messages(id,contact_id,direction,message_id,subject,body,occurred_at) "
                "VALUES (?,1,'inbound',? ,?,'Hallo Daniel, danke!',?)",
                (
                    mid,
                    f"<{mid}@example.test>",
                    f"Unterhaltung {mid}",
                    f"2026-10-0{mid}",
                ),
            )
        db.execute("UPDATE drafts SET reply_message_id=1 WHERE id=1")
        db.execute(
            "INSERT INTO opportunities(id,contact_id,title,quality_tier,created_at) "
            "VALUES (1,1,'Schwacher Anlass','watch',?)",
            (admin_db.now(),),
        )
        db.execute("UPDATE drafts SET opportunity_id=1 WHERE id=1")

    def check(key, context, instructions, **kw):
        assert context["reply_to"]["subject"] == "Unterhaltung 1"
        assert context["occasion_review"]["allowed"] is False
        return outcome()

    monkeypatch.setattr(draft_editor, "run", check)
    draft_rewrite.rewrite(1)
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts").fetchone()
        assert draft["reply_message_id"] == 1
        assert draft["subject"] == mail_threads.subject(mail_threads.selected(db, 1, 1))
        assert (
            db.execute("SELECT quality_tier FROM opportunities").fetchone()[0]
            == "watch"
        )


@pytest.mark.parametrize("status", ["needs_review", "no_fit"])
def test_failed_review_retains_old_text_and_records_explanation(
    draft_db, monkeypatch, status
):
    monkeypatch.setattr(draft_editor, "run", lambda *a, **kw: outcome(status))
    assert draft_rewrite.rewrite(1) == status
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts").fetchone()
        assert row["subject"] == "Alt"
        assert row["editorial_status"] == status
        assert json.loads(row["editorial_report"])["summary"]
        assert (
            json.loads(row["editorial_report"])["unapplied_candidate"]["body"]
            == outcome().candidate["body"]
        )


def test_english_draft_is_unchanged_without_api(draft_db, monkeypatch):
    with admin_db.database() as db:
        db.execute(
            "UPDATE drafts SET body='Dear Alex, thank you for your message. I would like to discuss this with you.'"
        )
    monkeypatch.setattr(
        draft_editor, "run", lambda *a, **kw: pytest.fail("English edited")
    )
    assert draft_rewrite.rewrite(1) == "english"
    with admin_db.database() as db:
        assert db.execute("SELECT version FROM drafts").fetchone()[0] == 1


@pytest.mark.parametrize("include_english", [False, True])
def test_short_german_draft_uses_same_language_as_editor(
    draft_db, monkeypatch, include_english
):
    original = "Hallo Alex,\n\nvielen Dank! Passt das?\nDaniel"
    with admin_db.database() as db:
        db.execute("UPDATE drafts SET body=?", (original,))
    checked = []

    def inspect(*a, **kw):
        checked.append(kw["language"])
        assert kw["language"] == draft_editor.detect_language(original) == "de"
        return outcome()

    monkeypatch.setattr(draft_editor, "run", inspect)
    assert draft_rewrite.rewrite(1, include_english=include_english) == "ready"
    assert checked == ["de"]


@pytest.mark.parametrize("checked_version", [0, 1])
def test_due_deferral_preserves_current_assessment_but_not_stale_assessment(
    draft_db, monkeypatch, checked_version
):
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "0")
    with admin_db.database() as db:
        db.execute(
            "UPDATE drafts SET status='deferred',deferred_until='2000-01-01',"
            "editorial_status='ready',editorial_version=? WHERE id=1",
            (checked_version,),
        )
        original = dict(db.execute("SELECT * FROM drafts WHERE id=1").fetchone())
    outreach.schedule()
    outreach.schedule()
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts WHERE id=1").fetchone()
        assert draft["status"] == "draft" and draft["deferred_until"] == ""
        assert draft["version"] == 2
        assert draft["editorial_version"] == (2 if checked_version == 1 else 0)
        assert draft["editorial_status"] == "ready"
        assert draft["body"] == original["body"]
        assert draft["subject"] == original["subject"]
        assert draft["editorial_report"] == original["editorial_report"]
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM outreach_deliveries").fetchone()[0] == 0


def test_authorized_english_edit_is_reviewed_and_preserves_sent_history(
    draft_db, monkeypatch
):
    original = (
        "Dear Alex,\n\nthank you for your work. Would you share this idea?\nDaniel"
    )
    revised = "Dear Alex,\n\nI hope we can encourage others to leave these platforms. You can read more at https://thegreatlogout.org/.\nDaniel"
    with admin_db.database() as db:
        db.execute(
            "UPDATE drafts SET body=?,status='approved',approved_recipient='person@example.test'",
            (original,),
        )

    def inspect(*a, **kw):
        assert kw["language"] == "en" and kw["review_english"] is True
        return draft_editor.Outcome(
            candidate={**outcome().candidate, "body": revised},
            status="ready",
            review={"summary": "Reviewed", "natural_english": True, "issues": []},
            rounds=1,
        )

    monkeypatch.setattr(draft_editor, "run", inspect)
    assert draft_rewrite.rewrite(1, include_english=True, expected_version=1) == "ready"
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts").fetchone()
        assert row["body"] == revised and row["status"] == "draft"
        assert row["approved_recipient"] == ""
        assert row["version"] == row["editorial_version"] == 2
        assert db.execute("SELECT body FROM draft_revisions").fetchone()[0] == original
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM outreach_deliveries").fetchone()[0] == 0


def test_proofread_candidate_is_checked_again_with_version_guard(draft_db, monkeypatch):
    with admin_db.database() as db:
        db.execute("UPDATE drafts SET editorial_status='ready',editorial_version=1")
    checked = []

    def inspect(*a, **kw):
        checked.append(kw["seed"])
        return outcome()

    monkeypatch.setattr(draft_editor, "run", inspect)
    with pytest.raises(ValueError, match="Gegenlesen"):
        draft_rewrite.rewrite(1, candidate=outcome().candidate, expected_version=2)
    assert not checked
    assert (
        draft_rewrite.rewrite(1, candidate=outcome().candidate, expected_version=1)
        == "ready"
    )
    assert checked == [outcome().candidate]


def test_new_german_draft_gets_current_review(draft_db, monkeypatch):
    with admin_db.database() as db:
        db.execute("DELETE FROM drafts")
    monkeypatch.setattr(draft_editor, "run", lambda *a, **kw: outcome())
    assert outreach.generate_draft(1) == 1
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM drafts").fetchone()
        assert row["framing"] == "dialogue"
        assert row["editorial_version"] == row["version"] == 1
        assert row["editorial_status"] == "ready"
