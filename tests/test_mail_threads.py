import json
from email import policy
from email.parser import BytesParser

import pytest

from server import admin_db, ai_client, mail_threads, outreach, outreach_delivery
from test_admin import login, post
from test_outreach import message, proposal


def test_generation_keeps_subject_and_finds_older_reply_for_selected_recipient(
    client, monkeypatch
):
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='peer@example.test',permission='existing' WHERE id=1"
        )
        previous = message(
            db,
            message_id="<root@example.test>",
            subject="Our existing conversation",
            days=30,
        )
        for n in range(5):
            message(db, days=n + 1)
        message(
            db,
            days=0,
            address="different@example.test",
            message_id="<other@example.test>",
        )
    received = []

    def generate(*args, **kwargs):
        received.append(args[2])
        return proposal(subject="An unrelated new subject"), set()

    monkeypatch.setattr(ai_client, "request", generate)
    assert outreach.generate_draft(1) == 1
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts").fetchone()
        assert draft["subject"] == "Re: Our existing conversation"
        assert draft["reply_message_id"] == previous
    assert received[0]["reply_to"]["subject"] == "Our existing conversation"


def test_references_reconstruct_missing_local_chain_and_sanitize(client):
    with admin_db.database() as db:
        message(db, message_id="<root@example.test>")
        message(
            db, message_id="<middle@example.test>", in_reply_to="<root@example.test>"
        )
        last = message(
            db, message_id="<last@example.test>", in_reply_to="<middle@example.test>"
        )
        row = mail_threads.selected(db, 1, last)
        assert mail_threads.references(db, row) == [
            "<root@example.test>",
            "<middle@example.test>",
            "<last@example.test>",
        ]
        db.execute(
            "UPDATE messages SET references_json=? WHERE id=?",
            (
                json.dumps(
                    [
                        "<root@example.test>",
                        "<bad@example.test>\r\nBcc: hidden@example.test",
                        None,
                        "<root@example.test>",
                    ]
                ),
                last,
            ),
        )
        assert mail_threads.references(db, mail_threads.selected(db, 1, last)) == [
            "<root@example.test>",
            "<last@example.test>",
        ]
        with pytest.raises(ValueError):
            mail_threads.selected(db, 2, last)


def test_reply_choice_review_export_and_manual_log_preserve_same_thread(client):
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='peer@example.test',permission='existing' WHERE id=1"
        )
        mid = message(
            db,
            message_id="<last@example.test>",
            subject="Re: Existing subject",
            references_json='["<root@example.test>","<middle@example.test>"]',
        )
    assert (
        post(
            client,
            "/drafts",
            token,
            contact_id=1,
            subject="Ignore new title",
            body="Approved words",
            reply_message_id=mid,
        ).status_code
        == 200
    )
    page = client.get("/review").text
    assert "Antwort im bisherigen Verlauf" in page and 'name="reply_message_id"' in page
    assert f"/contacts/1#message-{mid}" in page
    assert (
        post(
            client, "/drafts/1/review", token, version=1, action="approved"
        ).status_code
        == 200
    )
    exported = BytesParser(policy=policy.default).parsebytes(
        post(client, "/drafts/1/export", token, version=2).content
    )
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts").fetchone()
        direct = outreach_delivery.render_message(
            db,
            draft,
            {"sender": "sender@example.test", "reply_to": "sender@example.test"},
        )
        for header in ["Subject", "In-Reply-To", "References"]:
            assert direct[header] == exported[header]
        assert direct["Subject"] == "Re: Existing subject"
        assert (
            direct["References"]
            == "<root@example.test> <middle@example.test> <last@example.test>"
        )
        assert (
            direct.get_body(preferencelist=("plain",)).get_content().strip()
            == "Approved words"
        )
    assert (
        post(
            client,
            "/messages",
            token,
            contact_id=1,
            draft_id=1,
            direction="outbound",
            version=2,
            occurred_at="2026-10-11",
        ).status_code
        == 200
    )
    with admin_db.database() as db:
        sent = db.execute("SELECT * FROM messages WHERE draft_id=1").fetchone()
        assert sent["in_reply_to"] == "<last@example.test>"
        assert (
            json.loads(sent["references_json"]) == str(exported["References"]).split()
        )


def test_switch_to_new_conversation_invalidates_approval_and_omits_thread_headers(
    client,
):
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='peer@example.test',permission='existing' WHERE id=1"
        )
        mid = message(db, message_id="<prior@example.test>")
    post(
        client,
        "/drafts",
        token,
        contact_id=1,
        subject="New title",
        body="Same words",
        reply_message_id=mid,
    )
    post(client, "/drafts/1/review", token, version=1, action="approved")
    assert (
        post(
            client,
            "/drafts",
            token,
            contact_id=1,
            id=1,
            version=2,
            subject="Separate topic",
            body="Same words",
            reply_message_id="",
        ).status_code
        == 200
    )
    assert post(client, "/drafts/1/export", token, version=2).status_code == 409
    with admin_db.database() as db:
        draft = db.execute("SELECT * FROM drafts").fetchone()
        assert draft["status"] == "draft" and draft["version"] == 3
        assert draft["subject"] == "Separate topic" and draft["body"] == "Same words"
        assert not draft["approved_recipient"] and mail_threads.headers(db, draft) == {}
    assert "Neue Unterhaltung" in client.get("/review").text


@pytest.mark.parametrize(
    "changes",
    [
        dict(message_id="not-an-id"),
        dict(message_id="<bad@example.test>\nBcc: other@example.test"),
        dict(message_id="<auto@example.test>", automated=1),
        dict(cid=2, message_id="<other@example.test>"),
    ],
)
def test_invalid_or_other_contact_reply_cannot_be_saved(client, changes):
    token = login(client)
    with admin_db.database() as db:
        mid = message(db, **changes)
    assert (
        post(
            client,
            "/drafts",
            token,
            contact_id=1,
            subject="Subject",
            body="Words",
            reply_message_id=mid,
        ).status_code
        == 400
    )
    with admin_db.database() as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0
