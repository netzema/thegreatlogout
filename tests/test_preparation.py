import socket

import pytest

from server import admin_db, ai_client, contact_research, outreach, preparation
from test_admin import login, post
from test_outreach import draft_response, proposal


def occasion(db, cid=1, title="New public campaign"):
    return db.execute(
        "INSERT INTO opportunities(contact_id,title,source_url,reason,cta,created_at,published_at) VALUES (?,?,'https://example.org/news','Relevant public campaign','Exchange ideas',?,?)",
        (cid, title, admin_db.now(), admin_db.now()[:10]),
    ).lastrowid


def test_every_opportunity_including_same_contact_and_low_score(client, monkeypatch):
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "1")
    with admin_db.database() as db:
        ids = [occasion(db, 1, str(i)) for i in range(5)]
        db.execute(
            "UPDATE contacts SET email='existing@example.test',permission='existing' WHERE id=1"
        )
    outreach.schedule()
    outreach.schedule()
    with admin_db.database() as db:
        jobs = db.execute(
            "SELECT * FROM automation_jobs WHERE kind='prepare'"
        ).fetchall()
        assert len(jobs) == 5
    monkeypatch.setattr(ai_client, "request", draft_response)
    for oid in ids:
        assert preparation.run(1, oid) == 1
        assert preparation.run(1, oid) == 0
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 5
        assert {
            r[0] for r in db.execute("SELECT preparation_state FROM opportunities")
        } == {"ready"}
        assert {r[0] for r in db.execute("SELECT status FROM drafts")} == {"draft"}
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_button_feedback_dedup_and_ready_review_link(client, monkeypatch):
    monkeypatch.setattr(outreach, "wake_worker", lambda: None)
    token = login(client)
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute("UPDATE contacts SET email='existing@example.test' WHERE id=1")
    first = post(
        client,
        "/outreach/jobs",
        token,
        kind="draft",
        contact_id="1",
        opportunity_id=str(oid),
    )
    assert "Vorbereitung eingeplant" in first.text
    assert "Vorbereitung eingeplant" in client.get("/opportunities").text
    second = post(
        client,
        "/outreach/jobs",
        token,
        kind="draft",
        contact_id="1",
        opportunity_id=str(oid),
    )
    assert "bereits vorhanden" in second.text
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM automation_jobs").fetchone()[0] == 1
    monkeypatch.setattr(ai_client, "request", draft_response)
    preparation.run(1, oid)
    assert "Zur Freigabe" in client.get("/opportunities").text
    response = client.post(
        "/outreach/jobs",
        data={
            "csrf": token,
            "kind": "draft",
            "contact_id": "1",
            "opportunity_id": str(oid),
        },
        headers={"origin": "https://admin.thegreatlogout.org"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/review#draft-")


def test_missing_address_preserves_draft_and_retry_does_not_duplicate(
    client, monkeypatch
):
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute("UPDATE contacts SET email='' WHERE id=1")
    monkeypatch.setattr(contact_research, "enrich", lambda cid: False)
    monkeypatch.setattr(ai_client, "request", draft_response)
    preparation.run(1, oid)
    preparation.run(1, oid)
    with admin_db.database() as db:
        assert (
            db.execute("SELECT preparation_state FROM opportunities").fetchone()[0]
            == "needs_attention"
        )
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
        db.execute("UPDATE contacts SET email='verified@example.test' WHERE id=1")
        preparation.refresh(db)
        assert (
            db.execute("SELECT preparation_state FROM opportunities").fetchone()[0]
            == "ready"
        )
        db.execute("UPDATE drafts SET status='rejected'")
        preparation.refresh(db)
        assert (
            db.execute("SELECT preparation_state FROM opportunities").fetchone()[0]
            == "reviewed"
        )


def test_budget_resumes_next_day_without_discarding_work(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OUTREACH_AUTOMATION_ENABLED", "1")
    with admin_db.database() as db:
        oid = occasion(db)
        preparation.enqueue(db, 1, oid)

    def exhausted(cid):
        raise ai_client.AIBudgetExceeded(
            "Tageslimit erreicht. Fortsetzung automatisch morgen."
        )

    monkeypatch.setattr(contact_research, "enrich", exhausted)
    assert outreach.process_one()
    assert not outreach.process_one()
    with admin_db.database() as db:
        assert (
            db.execute("SELECT status FROM automation_jobs").fetchone()[0]
            == "waiting_budget"
        )
        assert (
            db.execute("SELECT preparation_state FROM opportunities").fetchone()[0]
            == "waiting_budget"
        )
        db.execute("UPDATE automation_jobs SET finished_at='2000-01-01'")
    outreach.schedule()
    with admin_db.database() as db:
        assert (
            db.execute(
                "SELECT status FROM automation_jobs WHERE kind='prepare'"
            ).fetchone()[0]
            == "queued"
        )


def test_decline_and_block_are_visible_without_drafts(client, monkeypatch):
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute("UPDATE contacts SET email='existing@example.test' WHERE id=1")
    response = proposal()
    response.update(
        should_draft=False,
        rationale="Die konkrete Quelle ist nicht ausreichend belegt.",
    )
    monkeypatch.setattr(
        ai_client,
        "request",
        lambda purpose, *a, **kw: draft_response(
            purpose, *a, candidate=response, **kw
        ),
    )
    preparation.run(1, oid)
    with admin_db.database() as db:
        o = db.execute("SELECT * FROM opportunities").fetchone()
        assert o["preparation_state"] == "needs_attention"
        assert "Quelle" in o["preparation_note"]
        db.execute("UPDATE contacts SET permission='blocked' WHERE id=1")
    with pytest.raises(ValueError):
        preparation.run(1, oid)


def test_public_evidence_enrichment_never_grants_consent_or_import_access(
    client, monkeypatch
):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='',permission='unknown',website='https://example.org',contact_url='',person='' WHERE id=1"
        )
        domains = list(db.execute("SELECT * FROM organization_domains"))
    monkeypatch.setattr(
        contact_research,
        "fetch",
        lambda url: (
            url,
            '<a href="/kontakt">Kontakt</a>'
            if url.endswith("/")
            else "<p>info [at] example.org</p>",
        ),
    )
    # Start at the normalized root, then follow its observed contact link.
    assert contact_research.enrich(1)
    with admin_db.database() as db:
        c = db.execute("SELECT * FROM contacts WHERE id=1").fetchone()
        assert c["email"] == "info@example.org"
        assert c["email_source"].endswith("https://example.org/kontakt")
        assert c["permission"] == "unknown"
        assert list(db.execute("SELECT * FROM organization_domains")) == domains
        db.execute("UPDATE contacts SET email='chosen@example.test' WHERE id=1")
    monkeypatch.setattr(
        contact_research,
        "fetch",
        lambda url: pytest.fail("Existing address must be preserved"),
    )
    assert contact_research.enrich(1)


def test_address_parsing_and_ambiguous_or_unrelated_people():
    page = contact_research.Page(
        '<script>evil@example.org</script><p>info (at) example (dot) org</p><a href="mailto:press%40example.org?subject=test">Press</a>'
    )
    assert page.addresses() == {"info@example.org", "press@example.org"}
    assert (
        contact_research.choose(
            {("stranger@example.org", "https://example.org/team")}, {"person": ""}
        )
        is None
    )
    assert (
        contact_research.choose(
            {
                ("alex.smith@example.org", "https://example.org/team"),
                ("alex.smith2@example.org", "https://example.org/team"),
            },
            {"person": "Alex Smith"},
        )
        is None
    )
    assert (
        contact_research.choose(
            {("info@elsewhere.org", "https://example.org/team")}, {"person": ""}
        )
        is None
    )


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
def test_fetch_blocks_private_dns_before_connect(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **kw: pytest.fail("Must not connect")
    )
    with pytest.raises(ValueError, match="öffentliche"):
        contact_research.fetch("https://example.org/contact")


def test_search_urls_must_be_cited_and_official(client, monkeypatch):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='',website='https://example.org',contact_url='' WHERE id=1"
        )
    visited = []

    def fetch(url):
        visited.append(url)
        return url, "No contact information"

    monkeypatch.setattr(contact_research, "fetch", fetch)
    monkeypatch.setattr(
        ai_client,
        "request",
        lambda *a, **kw: (
            {"urls": ["https://example.org/uncited", "https://elsewhere.org/contact"]},
            {"https://elsewhere.org/contact"},
        ),
    )
    assert not contact_research.enrich(1)
    assert visited == ["https://example.org/"]


def test_model_can_only_select_fetched_address_with_literal_role_evidence(
    client, monkeypatch
):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='',person='',website='https://example.org',contact_url='' WHERE id=1"
        )
    content = '<p>Official contact: Jane Example, editorial director.</p><a href="mailto:jane@work.example.net">Write to the editorial director</a>'
    monkeypatch.setattr(contact_research, "fetch", lambda url: (url, content))

    def request(purpose, *args, **kwargs):
        assert purpose == "contact_selection"
        return {
            "index": 0,
            "person": "Jane Example",
            "evidence": "Jane Example, editorial director.",
        }, set()

    monkeypatch.setattr(ai_client, "request", request)
    assert contact_research.enrich(1)
    with admin_db.database() as db:
        c = db.execute(
            "SELECT email,person,permission FROM contacts WHERE id=1"
        ).fetchone()
        assert c[0] == "jane@work.example.net" and c[1] == "Jane Example"
        assert c[2] == "unknown"


def test_model_unfounded_role_cannot_populate_address(client, monkeypatch):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='',person='',website='https://example.org',contact_url='' WHERE id=1"
        )
    monkeypatch.setattr(
        contact_research,
        "fetch",
        lambda url: (url, "<p>Someone: unrelated@example.net</p>"),
    )

    def request(purpose, *args, **kwargs):
        return (
            {
                "index": 0,
                "person": "Invented Name",
                "evidence": "Invented Name is the editorial contact.",
            }
            if purpose == "contact_selection"
            else {"urls": []}
        ), set()

    monkeypatch.setattr(ai_client, "request", request)
    assert not contact_research.enrich(1)
    with admin_db.database() as db:
        assert db.execute("SELECT email FROM contacts WHERE id=1").fetchone()[0] == ""


def test_fetch_revalidates_redirect_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda hostname, *a, **kw: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34" if hostname == "example.org" else "127.0.0.1", 80),
            )
        ],
    )

    class Sock:
        def close(self):
            pass

    connections = []

    def connect(address, **kw):
        connections.append(address)
        return Sock()

    class Response:
        status = 302

        def getheader(self, name, default=""):
            return (
                "http://private.example.net/contact" if name == "Location" else default
            )

    class Connection:
        def __init__(self, *a, **kw):
            pass

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(contact_research.http.client, "HTTPConnection", Connection)
    with pytest.raises(ValueError, match="öffentliche"):
        contact_research.fetch("http://example.org/contact")
    assert connections == [("93.184.216.34", 80)]


def test_interrupted_preparation_surfaces_failure(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    with admin_db.database() as db:
        oid = occasion(db)
        preparation.enqueue(db, 1, oid)
        db.execute("UPDATE automation_jobs SET status='running'")
        preparation.state(db, oid, "running", "In Arbeit")
    assert not outreach.process_one()
    with admin_db.database() as db:
        assert (
            db.execute("SELECT preparation_state FROM opportunities").fetchone()[0]
            == "failed"
        )


def test_local_scripts_are_limited_to_interactive_admin_pages(client):
    login(client)
    for path in ["/opportunities", "/review"]:
        policy = client.get(path).headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "unsafe-inline" not in policy
    for path in ["/", "/contacts", "/contacts/1", "/settings", "/analytics", "/guide"]:
        assert "script-src 'none'" in client.get(path).headers["content-security-policy"]


def test_approval_shows_next_step_and_tracks_edit_and_deferral(client, monkeypatch):
    token = login(client)
    with admin_db.database() as db:
        oid = occasion(db)
        db.execute(
            "UPDATE contacts SET email='review@example.test',permission='existing' WHERE id=1"
        )
    monkeypatch.setattr(ai_client, "request", draft_response)
    preparation.run(1, oid)
    response = post(client, "/drafts/1/review", token, action="approved", version=1)
    assert response.status_code == 200
    assert response.history[0].headers["location"] == "/review#draft-1"
    assert "Empfänger und Text sind freigegeben. Noch nicht versendet." in response.text
    assert response.text.index("Mailentwurf herunterladen") < response.text.index(
        "Warum dieser Vorschlag?"
    )
    assert "Freigabe ändern oder zurückstellen" in response.text
    opportunities = client.get("/opportunities")
    assert "Freigegeben - Versand ausständig" in opportunities.text
    assert "Zum Mailentwurf" in opportunities.text
    assert "Zur Freigabe</a>" not in opportunities.text
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM automation_jobs").fetchone()[0] == 0
    assert post(client, "/drafts/1/export", token, version=2).status_code == 200
    post(client, "/drafts/1/review", token, action="deferred", version=2)
    assert "Zurückgestellt" in client.get("/opportunities").text
    with admin_db.database() as db:
        db.execute("UPDATE drafts SET status='draft'")
    assert "Zur Freigabe</a>" in client.get("/opportunities").text
