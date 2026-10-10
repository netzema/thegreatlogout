import json
from datetime import timedelta

import pytest

from server import admin_db, ai_client, discovery, outreach
from test_admin import login
from test_outreach import proposal


def finding(**changes):
    value = dict(
        title="New initiative for digital autonomy",
        kind="campaign",
        source_url="https://initiative.example.org/launch",
        published_at=str(outreach.today()),
        event_at="",
        reason="Directly relevant public initiative",
        cta="Exchange campaign materials",
        framing="collaboration",
        fit=3,
        contact=dict(
            organization="New Public Initiative",
            person="Alex Example",
            category="ngo",
            source_url="https://initiative.example.org/launch",
            website="https://initiative.example.org/",
            contact_url="https://initiative.example.org/contact",
            relationship="Organizes the initiative",
        ),
    )
    value.update(changes)
    return value


def mock_research(monkeypatch, findings):
    calls = []
    sources = {
        "https://initiative.example.org/launch",
        "https://initiative.example.org/",
        "https://initiative.example.org/contact",
        "https://initiative.example.org/event",
    }

    def respond(purpose, instructions, data, **kwargs):
        calls.append(purpose)
        assert "contacts" not in data and "organizations" not in data
        assert "untrusted" in instructions
        assert "private@example.test" not in json.dumps(data)
        if purpose == "discovery_extract":
            assert len(data["research"]) == 3 and kwargs["schema"]
            return {"opportunities": findings}, set()
        assert kwargs["search"] is True
        return "Source-backed synthetic research", sources

    monkeypatch.setattr(ai_client, "request", respond)
    return calls


def test_broad_search_creates_contact_from_empty_database_and_is_idempotent(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(admin_db, "DB_PATH", tmp_path / "empty.db")
    admin_db.ensure_schema()
    calls = mock_research(monkeypatch, [finding()])
    assert outreach.radar() == 1
    assert calls == [
        "discovery_events",
        "discovery_publications",
        "discovery_debates",
        "discovery_extract",
    ]
    assert outreach.radar() == 0
    with admin_db.database() as db:
        contact = db.execute("SELECT * FROM contacts").fetchone()
        assert contact["permission"] == "unknown" and contact["status"] == "researched"
        assert contact["email"] == "" and contact["person"] == "Alex Example"
        assert contact["contact_url"] == "https://initiative.example.org/contact"
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == 1
        assert db.execute("SELECT discovered_new FROM opportunities").fetchone()[0] == 1
        assert (
            db.execute("SELECT count(*) FROM organization_domains").fetchone()[0] == 0
        )
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


@pytest.mark.parametrize("state", ["blocked", "paused", "closed", "objection"])
def test_discovery_preserves_existing_blocks_and_never_recreates_them(
    client, monkeypatch, state
):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET organization='New Public Initiative',notes='private@example.test' WHERE id=1"
        )
        if state == "blocked":
            db.execute("UPDATE contacts SET permission='blocked' WHERE id=1")
        elif state == "objection":
            db.execute(
                "INSERT INTO messages(contact_id,direction,subject,body,occurred_at,analysis_kind) "
                "VALUES (1,'inbound','No','Stop',?,'contact_objection')",
                (admin_db.now(),),
            )
        else:
            db.execute("UPDATE contacts SET status=? WHERE id=1", (state,))
        count = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
    mock_research(monkeypatch, [finding()])
    assert outreach.radar() == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == count
        assert db.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 0


def test_sources_dates_and_fit_checked_before_creating_contacts(client, monkeypatch):
    good = finding()
    bad = [
        finding(source_url="https://invented.example.org/news"),
        finding(
            contact=dict(
                good["contact"], source_url="https://invented.example.org/person"
            )
        ),
        finding(published_at="2020-01-01"),
        finding(published_at=str(outreach.today() + timedelta(days=1))),
        finding(kind="event", event_at=str(outreach.today() - timedelta(days=1))),
        finding(kind="viral", fit=1),
    ]
    with admin_db.database() as db:
        count = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
    mock_research(monkeypatch, bad)
    assert outreach.radar() == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM contacts").fetchone()[0] == count


def test_uncited_contact_routes_are_not_invented_and_aliases_reuse_contact(
    client, monkeypatch
):
    good = finding()
    mock_research(
        monkeypatch,
        [
            finding(
                contact=dict(
                    good["contact"],
                    contact_url="https://initiative.example.org/invented",
                )
            )
        ],
    )
    assert outreach.radar() == 1
    with admin_db.database() as db:
        c = db.execute(
            "SELECT * FROM contacts WHERE discovery_key IS NOT NULL"
        ).fetchone()
        assert c["contact_url"] == ""
        cid = c["id"]
        db.execute(
            "UPDATE contacts SET organization='Owner renamed it',person='Keep my chosen person' WHERE id=?",
            (cid,),
        )
    mock_research(
        monkeypatch,
        [
            finding(
                contact=dict(
                    good["contact"], organization="An alias for the same initiative"
                )
            )
        ],
    )
    assert outreach.radar() == 0
    with admin_db.database() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM contacts WHERE discovery_key IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute("SELECT person FROM contacts WHERE id=?", (cid,)).fetchone()[0]
            == "Keep my chosen person"
        )


def test_upcoming_event_with_older_announcement_queues_review_draft_and_expires(
    client, monkeypatch
):
    event = finding(
        kind="event",
        source_url="https://initiative.example.org/event",
        published_at=str(outreach.today() - timedelta(days=60)),
        event_at=str(outreach.today() + timedelta(days=20)),
    )
    mock_research(monkeypatch, [event])
    assert outreach.radar() == 1
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "1")
    outreach.schedule()
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM opportunities").fetchone()
        context, _, _ = outreach.draft_context(db, row["contact_id"], row["id"])
        assert context["opportunity"]["event_at"] == event["event_at"]
        assert (
            db.execute(
                "SELECT count(*) FROM automation_jobs WHERE kind='draft'"
            ).fetchone()[0]
            == 1
        )
        cid, oid = row["contact_id"], row["id"]
    monkeypatch.setattr(ai_client, "request", lambda *a, **kw: (proposal(), set()))
    assert outreach.generate_draft(cid, oid) == 1
    with admin_db.database() as db:
        assert db.execute("SELECT status FROM drafts").fetchone()[0] == "draft"
        assert (
            db.execute("SELECT permission FROM contacts WHERE id=?", (cid,)).fetchone()[
                0
            ]
            == "unknown"
        )
        db.execute(
            "UPDATE opportunities SET event_at=?",
            (str(outreach.today() - timedelta(days=1)),),
        )
        with pytest.raises(ValueError, match="aktuell"):
            outreach.draft_context(db, cid, oid)


def test_new_contact_and_opportunity_are_visible_with_provenance(client, monkeypatch):
    mock_research(monkeypatch, [finding()])
    assert outreach.radar() == 1
    login(client)
    page = client.get("/opportunities")
    assert (
        "Neuer Kontakt entdeckt" in page.text and "New Public Initiative" in page.text
    )
    with admin_db.database() as db:
        cid = db.execute("SELECT contact_id FROM opportunities").fetchone()[0]
    page = client.get(f"/contacts/{cid}")
    assert "Öffentliche Kontaktseite" in page.text
    assert "https://initiative.example.org/contact" in page.text


def test_shared_social_host_is_not_an_organization_identity():
    assert discovery.site_host("https://www.youtube.com/@one") == ""
    assert discovery.site_host("https://www.youtube.com/@two") == ""
    assert (
        discovery.site_host("https://www.initiative.example.org/")
        == "initiative.example.org"
    )


def test_discovery_gets_slots_alongside_existing_dialogue(client, monkeypatch):
    from test_outreach import message

    with admin_db.database() as db:
        message(db, cid=1, direction="inbound", days=1)
        for cid in (2, 3, 4, 5):
            db.execute(
                "INSERT INTO opportunities(contact_id,title,score,source_url,published_at,created_at) "
                "VALUES (?,'New public event',85,'https://example.org/news',?,?)",
                (cid, str(outreach.today()), admin_db.now()),
            )
        db.execute(
            "INSERT INTO drafts(contact_id,subject,body,created_at,updated_at) "
            "VALUES (5,'Already awaiting review','An existing draft',?,?)",
            (admin_db.now(), admin_db.now()),
        )
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "1")
    outreach.schedule()
    with admin_db.database() as db:
        jobs = db.execute(
            "SELECT contact_id FROM automation_jobs WHERE kind='draft' ORDER BY id"
        ).fetchall()
        assert len(jobs) == 3
        assert jobs[0][0] != 1 and jobs[1][0] != 1 and jobs[2][0] == 1
        assert all(j[0] != 5 for j in jobs)
