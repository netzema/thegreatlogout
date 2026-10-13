import json

import pytest

from server import (
    admin_db,
    ai_client,
    contact_research,
    discovery,
    opportunity_quality as quality,
    outreach,
    outreach_delivery,
    preparation,
)
from test_admin import login, post
from test_discovery import finding, mock_research
from test_preparation import occasion

EVIDENCE = "We organize a visible exit from addictive social platforms."


def assessment(**changes):
    values = dict(
        fit=3,
        contact_fit=3,
        opening_fit=3,
        reason="Direkter Bezug, zuständiger Veranstalter. Eine Zusage ist nicht belegt.",
        startpoint="Können wir das Material zu eurem sichtbaren Plattformausstieg beitragen?",
        source_quote=EVIDENCE,
    )
    values.update(changes)
    return quality.Assessment(**values)


@pytest.mark.parametrize(
    "changes,tier",
    [
        ({}, "good"),
        ({"fit": 2}, "watch"),
        ({"fit": 1}, "poor"),
        ({"opening_fit": 1}, "watch"),
        ({"contact_fit": 1}, "watch"),
        ({"startpoint": ""}, "watch"),
        ({"source_quote": "An invented supporting quote"}, "watch"),
    ],
)
def test_only_direct_evidenced_and_useful_openings_are_recommended(changes, tier):
    assert quality.grade(assessment(**changes), EVIDENCE)[0] == tier


def test_new_discovery_skips_adjacent_topics_and_generic_feedback_requests(
    client, monkeypatch
):
    mock_research(
        monkeypatch, [finding(fit=2), finding(opening_fit=1), finding(contact_fit=1)]
    )
    with admin_db.database() as db:
        before = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
    assert discovery.run() == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == before
        assert db.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 0


def test_reassessment_preserves_text_and_revokes_weak_approval_blocks_transport(
    client, monkeypatch
):
    token = login(client)
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute(
            "UPDATE contacts SET email='peer@example.test',permission='existing' WHERE id=1"
        )
        db.execute(
            "INSERT INTO drafts(contact_id,opportunity_id,subject,body,created_at,updated_at) VALUES (1,?,'Keep title','Keep body',?,?)",
            (oid, admin_db.now(), admin_db.now()),
        )
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="approved"
        ).status_code
        == 200
    )
    with admin_db.database() as db:
        quality.save(db, oid, assessment(opening_fit=0), EVIDENCE)
        draft = db.execute("SELECT * FROM drafts").fetchone()
        assert (draft["body"], draft["subject"], draft["version"], draft["status"]) == (
            "Keep body",
            "Keep title",
            3,
            "draft",
        )
        assert not draft["approved_recipient"]
    assert (
        post(
            client, "/drafts/1/review", token, version=3, action="approved"
        ).status_code
        == 409
    )
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "1")
    outreach.schedule()
    with admin_db.database() as db:
        assert not db.execute(
            "SELECT 1 FROM automation_jobs WHERE kind='prepare'"
        ).fetchone()
        with pytest.raises(ValueError, match="Gesprächseinstieg"):
            preparation.enqueue(db, 1, oid)
        # Even a legacy/stale approval cannot bypass the transport/export guard.
        db.execute(
            "UPDATE drafts SET status='approved',approved_recipient='peer@example.test' WHERE id=1"
        )
        with pytest.raises(outreach_delivery.DeliveryError, match="Gesprächseinstieg"):
            outreach_delivery.require_approved(db, 1, 3)
    assert post(client, "/drafts/1/export", token, version=3).status_code == 409


def test_lists_rank_fit_and_keep_weak_drafts_separate(client):
    login(client)
    with admin_db.database() as db:
        for title, a in [
            ("Excellent match", assessment()),
            ("Weak match", assessment(fit=1)),
            ("Good match", assessment(opening_fit=2, contact_fit=2)),
        ]:
            oid = occasion(db, title=title)
            quality.save(db, oid, a, EVIDENCE)
            db.execute(
                "INSERT INTO drafts(contact_id,opportunity_id,subject,body,created_at,updated_at) VALUES (1,?,?,'Body',?,?)",
                (oid, title, admin_db.now(), admin_db.now()),
            )
    page = client.get("/opportunities").text
    assert page.index("Excellent match") < page.index("Good match")
    assert "Weak match" not in page
    assert "Weak match" in client.get("/opportunities?view=held").text
    page = client.get("/review").text
    assert (
        page.index("Excellent match")
        < page.index("Good match")
        < page.index("Weak match")
    )
    assert 'id="draft-2" data-review-group="quality"' in page
    assert "Vorerst nicht anschreiben" in page


def test_reassessment_uses_public_source_not_correspondence_or_old_ai_rationale(
    client, monkeypatch
):
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute(
            "UPDATE contacts SET notes='private secret',email='private@example.test' WHERE id=1"
        )
        db.execute(
            "UPDATE opportunities SET reason='Unsupported previous AI claim' WHERE id=?",
            (oid,),
        )
    monkeypatch.setattr(
        contact_research, "fetch", lambda url: (url, "<p>" + EVIDENCE + "</p>")
    )

    def respond(purpose, instructions, data, **kwargs):
        assert purpose == "opportunity_quality"
        assert all(
            x not in json.dumps(data)
            for x in [
                "private secret",
                "private@example.test",
                "Unsupported previous AI claim",
            ]
        )
        assert EVIDENCE in data["source_text"]
        return assessment().model_dump(), set()

    monkeypatch.setattr(ai_client, "request", respond)
    assert quality.assess(oid) == "good"

    def unavailable(url):
        raise ValueError("Not accessible")

    monkeypatch.setattr(contact_research, "fetch", unavailable)
    assert quality.assess(oid) == "watch"
