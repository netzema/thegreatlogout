import json

import pytest

from server import admin_db, ai_client, outreach, writing_style
from test_admin import login, post
from test_outreach import message, proposal


def test_note_edit_persists_escapes_and_rejects_stale_or_invalid_updates(client):
    token = login(client)
    page = client.get("/settings")
    assert "Deine Schreibnotiz" in page.text
    note = 'Persönlich schreiben. <script>alert("test")</script>'
    assert (
        post(
            client, "/settings/writing", token, writing_note=note, version=0
        ).status_code
        == 200
    )
    assert "&lt;script&gt;" in client.get("/settings").text
    assert (
        post(
            client, "/settings/writing", token, writing_note="Veraltet", version=0
        ).status_code
        == 409
    )
    assert (
        post(
            client, "/settings/writing", "wrong", writing_note="Ungültig", version=1
        ).status_code
        == 403
    )
    for invalid in ("", "x" * 6001):
        assert (
            post(
                client, "/settings/writing", token, writing_note=invalid, version=1
            ).status_code
            == 400
        )
    with admin_db.database() as db:
        assert writing_style.read(db) == (note, 1)


@pytest.mark.parametrize(
    "greeting",
    ["Hallo Alex", "Liebe Alex", "Dear Alex", "Guten Tag", "Sehr geehrte Frau Test"],
)
def test_mechanical_rules_preserve_lists_and_lowercase_after_greeting(greeting):
    original = (
        greeting
        + ",\n\nDanke für „Ideen“ — Alex’s Vorschlag; mit “Feedback”.\n- Erster Punkt\n- Zweiter Punkt"
    )
    result = writing_style.normalize(original, greeting=True)
    assert result.startswith(greeting + ",\n\ndanke")
    assert '"Ideen" - Alex\'s Vorschlag, mit "Feedback".' in result
    assert "\n- Erster Punkt\n- Zweiter Punkt" in result
    assert writing_style.normalize(result, greeting=True) == result


def test_english_opening_is_lowercase_without_changing_later_sentences():
    body = "Dear Alex,\n\nYou mentioned a meeting. I said I'd reconnect afterwards.\n\nThank you.\nDaniel"
    expected = body.replace("\n\nYou", "\n\nyou", 1)
    assert writing_style.normalize(body, greeting=True) == expected
    assert writing_style.normalize(expected, greeting=True) == expected
    assert writing_style.normalize(body) == body
    assert "auch auf Englisch" in writing_style.DEFAULT_NOTE
    assert '"You"' in writing_style.DEFAULT_NOTE


def test_note_and_person_reach_model_with_inbound_signature_but_no_addresses(
    client, monkeypatch
):
    with admin_db.database() as db:
        writing_style.save(db, "Kurz und persönlich schreiben.", 0)
        db.execute("UPDATE contacts SET person='Alex Beispiel' WHERE id=1")
        message(db, body="Hallo Alex,\nDanke!\nDaniel", days=2)
        message(
            db,
            direction="inbound",
            days=1,
            body="Hallo Daniel,\nGerne mehr Infos.\n--\nAlex Beispiel\nalex@example.test\n+43 123 456789\nAm Montag schrieb Daniel:\nPRIVATE QUOTE",
        )

    def inspect(purpose, instructions, data, **kwargs):
        assert "Kurz und persönlich schreiben." in instructions
        assert data["person"] == "Alex Beispiel"
        assert "Alex Beispiel" in data["history"][-1]["text"]
        assert all(
            x not in json.dumps(data)
            for x in ("alex@example.test", "+43 123 456789", "PRIVATE QUOTE")
        )
        return proposal(
            body="Hallo Alex,\n\nDanke für „Feedback“ — das freut mich; Alex’s Idee hilft.\nDaniel"
        ), set()

    monkeypatch.setattr(ai_client, "request", inspect)
    assert outreach.generate_draft(1) == 1
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts").fetchone()
        assert draft["body"].startswith('Hallo Alex,\n\ndanke für "Feedback" -')
        assert draft["body"] == draft["original_body"]
        assert draft["status"] == "draft"


def test_note_changed_during_generation_discards_stale_draft(client, monkeypatch):
    def changed(*args, **kwargs):
        with admin_db.database() as db:
            writing_style.save(db, "Neue Schreibnotiz", 0)
        return proposal(), set()

    monkeypatch.setattr(ai_client, "request", changed)
    with pytest.raises(ValueError, match="während der Erstellung"):
        outreach.generate_draft(1)
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


def test_current_sol_default_and_explicit_override(monkeypatch):
    monkeypatch.delenv("OUTREACH_AI_MODEL", raising=False)
    assert ai_client.model() == "gpt-6.1-sol"
    monkeypatch.setenv("OUTREACH_AI_MODEL", "explicit-test-model")
    assert ai_client.model() == "explicit-test-model"
