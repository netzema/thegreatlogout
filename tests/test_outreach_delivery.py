import smtplib
import socketserver
import ssl
import subprocess
import threading
from email import policy
from email.parser import BytesParser

import pytest

from server import admin_db, mail_sync, outreach_delivery as delivery
from test_admin import login, post

REAL_ARCHIVE = delivery.archive


@pytest.fixture
def approved(client, monkeypatch):
    monkeypatch.setenv("OUTREACH_DIRECT_SEND_ENABLED", "1")
    monkeypatch.setenv("OUTREACH_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("OUTREACH_SMTP_PORT", "587")
    monkeypatch.setenv("OUTREACH_SMTP_USER", "sender@example.test")
    monkeypatch.setenv("OUTREACH_SMTP_PASSWORD", "synthetic-password")
    monkeypatch.setenv("OUTREACH_FROM", "sender@example.test")
    monkeypatch.setenv("OUTREACH_REPLY_TO", "reply@example.test")
    token = login(client)
    with admin_db.database() as db:
        db.execute(
            "UPDATE contacts SET email='recipient@example.test',permission='existing' WHERE id=1"
        )
        previous = db.execute(
            "INSERT INTO messages(contact_id,direction,message_id,subject,body,occurred_at) VALUES (1,'inbound','<earlier@example.test>','Earlier','A reply',?)",
            (admin_db.now(),),
        ).lastrowid
        db.execute(
            "INSERT INTO drafts(contact_id,subject,body,reply_message_id,created_at,updated_at) VALUES (1,'A precise question',?,?,?,?)",
            (
                "Dear Alex,\n\nyour research matters. <No tracking> & no extra text.\n\nDaniel",
                previous,
                admin_db.now(),
                admin_db.now(),
            ),
        )
    assert (
        post(
            client, "/drafts/1/review", token, action="approved", version=1
        ).status_code
        == 200
    )
    return token


class SMTP:
    outcome = "sent"
    calls = []

    def __init__(self, *a, **kw):
        self.calls.append("connect")
        if self.outcome == "connect_error":
            raise OSError("sensitive server details")

    def ehlo(self):
        return 250, b"OK"

    def starttls(self, **kw):
        self.calls.append("tls")
        if self.outcome == "no_tls":
            raise smtplib.SMTPNotSupportedError("No TLS")

    def login(self, *args):
        assert "tls" in self.calls
        self.calls.append("auth")
        if self.outcome == "auth_error":
            raise smtplib.SMTPAuthenticationError(535, b"private response")

    def mail(self, sender):
        self.calls.append("mail")
        return (550 if self.outcome == "sender_rejected" else 250), b"OK"

    def rcpt(self, recipient):
        self.calls.append("rcpt")
        return (550 if self.outcome == "recipient_rejected" else 250), b"OK"

    def data(self, raw):
        self.calls.append("data")
        self.raw = raw
        if self.outcome == "timeout":
            raise TimeoutError("private content must not escape")
        if self.outcome == "data_rejected":
            raise smtplib.SMTPDataError(554, b"private provider reason")
        return 250, b"Accepted"

    def close(self):
        if self.outcome == "close_error":
            raise OSError("Already disconnected")


@pytest.fixture
def transport(monkeypatch):
    SMTP.calls = []
    SMTP.outcome = "sent"
    monkeypatch.setattr(delivery.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(delivery, "archive", lambda row: "done")
    return SMTP


def test_explicit_send_records_acceptance_once_and_keeps_thread(
    approved, client, transport, monkeypatch
):
    assert "Jetzt senden" in client.get("/review").text
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 200
    )
    assert "Vom Mailserver zum Versand angenommen" in client.get("/contacts/1").text
    assert transport.calls.count("data") == 1
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM outreach_deliveries").fetchone()
        raw = row["mime"]
        assert row["status"] == "sent" and row["accepted_at"]
        assert db.execute("SELECT status FROM drafts").fetchone()[0] == "sent"
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 1
        )
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert msg["To"] == "recipient@example.test"
    assert (
        msg["From"] == "sender@example.test" and msg["Reply-To"] == "reply@example.test"
    )
    assert msg["In-Reply-To"] == msg["References"] == "<earlier@example.test>"
    assert msg["Message-ID"] == "<tgl-draft-1-v2@thegreatlogout.org>"
    assert msg["X-Unsent"] is None
    assert (
        "your research matters. <No tracking> & no extra text."
        in msg.get_body(("plain",)).get_content()
    )
    markup = msg.get_body(("html",)).get_content()
    assert "&lt;No tracking&gt; &amp;" in markup
    assert "<img" not in markup and "http" not in markup
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 200
    )
    assert transport.calls.count("data") == 1
    monkeypatch.setattr(mail_sync, "permitted", lambda *a, **kw: True)
    assert mail_sync.import_message(raw, sent=True) == 0
    with admin_db.database() as db:
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "outcome",
    [
        "connect_error",
        "no_tls",
        "auth_error",
        "sender_rejected",
        "recipient_rejected",
        "data_rejected",
    ],
)
def test_definite_failures_are_retryable_without_send_record(
    approved, client, transport, outcome
):
    transport.outcome = outcome
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 200
    )
    with admin_db.database() as db:
        r = db.execute("SELECT * FROM outreach_deliveries").fetchone()
        assert r["status"] == "failed" and not r["accepted_at"]
        assert "private" not in r["note"] and "sensitive" not in r["note"]
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 0
        )
    transport.outcome = "sent"
    assert delivery.send(1, 2, 1) == "sent"


def test_unknown_never_retries_and_locks_mutations(approved, client, transport):
    transport.outcome = "timeout"
    assert delivery.send(1, 2, 1) == "unknown"
    assert delivery.send(1, 2, 1) == "unknown"
    assert transport.calls.count("data") == 1
    for route, data in [
        ("/drafts/1/review", dict(version=2, action="approved")),
        ("/drafts/1/export", dict(version=2)),
        (
            "/messages",
            dict(
                contact_id=1,
                draft_id=1,
                version=2,
                direction="outbound",
                occurred_at="2026-10-11",
            ),
        ),
        (
            "/drafts",
            dict(contact_id=1, id=1, version=2, subject="Changed", body="Changed"),
        ),
    ]:
        assert post(client, route, approved, **data).status_code == 409
    assert "Versandstatus unklar" in client.get("/review").text
    assert "Jetzt senden" not in client.get("/review").text
    with admin_db.database() as db:
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 0
        )
        assert db.execute("SELECT version FROM drafts").fetchone()[0] == 2
    assert (
        post(
            client,
            "/drafts/1/delivery-resolve",
            approved,
            confirm="checked",
            decision="not_sent",
            note="Provider confirmed no acceptance.",
        ).status_code
        == 200
    )
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 409
    )
    assert (
        post(
            client, "/drafts/1/review", approved, version=3, action="approved"
        ).status_code
        == 200
    )
    transport.outcome = "sent"
    assert delivery.send(1, 4, 1) == "sent"


def test_unknown_can_be_explicitly_confirmed_without_smtp(approved, client, transport):
    transport.outcome = "timeout"
    delivery.send(1, 2, 1)
    assert (
        post(
            client,
            "/drafts/1/delivery-resolve",
            approved,
            confirm="checked",
            decision="sent",
            occurred_at="2026-10-11",
            note="Provider confirms acceptance.",
        ).status_code
        == 200
    )
    with admin_db.database() as db:
        assert db.execute("SELECT status FROM drafts").fetchone()[0] == "sent"
        assert (
            db.execute("SELECT source FROM messages WHERE draft_id=1").fetchone()[0]
            == "smtp-confirmed"
        )
    assert transport.calls.count("data") == 1


def test_close_error_does_not_undo_acceptance(approved, transport):
    transport.outcome = "close_error"
    assert delivery.send(1, 2, 1) == "sent"
    assert delivery.send(1, 2, 1) == "sent"
    assert transport.calls.count("data") == 1


def test_stale_version_block_objection_and_disabled_feature(
    approved, client, transport, monkeypatch
):
    assert (
        post(
            client, "/drafts/1/send", "bad-csrf", version=2, confirm="send"
        ).status_code
        == 403
    )
    assert (
        post(client, "/drafts/1/send", approved, version=1, confirm="send").status_code
        == 409
    )
    assert post(client, "/drafts/1/send", approved, version=2).status_code == 409
    monkeypatch.setenv("OUTREACH_DIRECT_SEND_ENABLED", "0")
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 409
    )
    monkeypatch.setenv("OUTREACH_DIRECT_SEND_ENABLED", "1")
    with admin_db.database() as db:
        db.execute("UPDATE contacts SET permission='blocked' WHERE id=1")
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 409
    )
    with admin_db.database() as db:
        db.execute("UPDATE contacts SET permission='existing' WHERE id=1")
        db.execute("UPDATE messages SET analysis_kind='contact_objection' WHERE id=1")
    assert (
        post(client, "/drafts/1/send", approved, version=2, confirm="send").status_code
        == 409
    )
    assert not transport.calls


def test_claim_is_durable_and_interrupted_sends_cannot_restart(approved, transport):
    row, new = delivery.claim(1, 2, 1)
    assert new
    assert not delivery.claim(1, 2, 1)[1]
    with admin_db.database() as db:
        db.execute(
            "UPDATE outreach_deliveries SET updated_at='2000-01-01T00:00:00+00:00'"
        )
        delivery.recover_stalled(db)
        assert (
            db.execute("SELECT status FROM outreach_deliveries").fetchone()[0]
            == "unknown"
        )
    assert delivery.send(1, 2, 1) == "unknown"
    assert not transport.calls


def test_parallel_click_cannot_enter_transport(approved, transport):
    with delivery.delivery_lock(1):
        with pytest.raises(delivery.DeliveryError, match="gerade verarbeitet"):
            delivery.send(1, 2, 1)
    assert not transport.calls


def test_archive_failure_keeps_sent_state_and_can_retry_copy_only(
    approved, client, monkeypatch, transport
):
    module = delivery
    monkeypatch.setattr(module, "archive", REAL_ARCHIVE)
    monkeypatch.setenv("OUTREACH_IMAP_USER", "sender@example.test")
    monkeypatch.setenv("OUTREACH_IMAP_PASSWORD", "synthetic-password")

    class IMAP:
        found = False
        fail = True
        appends = 0

        def __init__(self, *a, **kw):
            if self.fail:
                raise OSError("private IMAP error")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, *args):
            pass

        def select(self, folder, readonly):
            assert readonly
            return "OK", []

        def uid(self, *args):
            return "OK", [b"1" if self.found else b""]

        def append(self, *args):
            IMAP.appends += 1
            IMAP.found = True
            return "OK", []

    monkeypatch.setattr(module.imaplib, "IMAP4_SSL", IMAP)
    assert module.send(1, 2, 1) == "sent"
    with admin_db.database() as db:
        assert (
            db.execute("SELECT archive_status FROM outreach_deliveries").fetchone()[0]
            == "failed"
        )
        row = dict(db.execute("SELECT * FROM outreach_deliveries").fetchone())
    IMAP.fail = False
    assert module.archive(row) == module.archive(row) == "done"
    assert IMAP.appends == 1
    assert transport.calls.count("data") == 1


def test_real_smtp_starttls_and_mime_on_local_server(approved, tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    client_tls = ssl.create_default_context(cafile=str(cert))
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def reply(self, line):
            self.wfile.write(line + b"\r\n")
            self.wfile.flush()

        def handle(self):
            secure = False
            self.reply(b"220 local.test SMTP")
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                command = line.split(b" ", 1)[0].strip().upper()
                if command == b"EHLO":
                    self.reply(b"250-local.test")
                    self.reply(b"250-AUTH PLAIN" if secure else b"250-STARTTLS")
                    self.reply(b"250 OK")
                elif command == b"STARTTLS":
                    self.reply(b"220 Begin TLS")
                    self.connection = tls.wrap_socket(self.connection, server_side=True)
                    self.rfile = self.connection.makefile("rb")
                    self.wfile = self.connection.makefile("wb")
                    secure = True
                elif command == b"AUTH":
                    assert secure
                    self.reply(b"235 Authenticated")
                elif command in {b"MAIL", b"RCPT"}:
                    assert secure
                    self.reply(b"250 OK")
                elif command == b"DATA":
                    self.reply(b"354 Send content")
                    lines = []
                    while (part := self.rfile.readline()) != b".\r\n":
                        assert part
                        lines.append(part[1:] if part.startswith(b"..") else part)
                    received.append(b"".join(lines))
                    self.reply(b"250 Accepted")
                else:
                    self.reply(b"221 Bye")
                    break

    real_smtp = smtplib.SMTP
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(
            delivery.smtplib,
            "SMTP",
            lambda *a, **kw: real_smtp(
                "127.0.0.1", server.server_address[1], timeout=5
            ),
        )
        monkeypatch.setattr(delivery.ssl, "create_default_context", lambda: client_tls)
        monkeypatch.setattr(delivery, "archive", lambda row: "done")
        try:
            assert delivery.send(1, 2, 1) == "sent"
            assert delivery.send(1, 2, 1) == "sent"
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert len(received) == 1
    message = BytesParser(policy=policy.default).parsebytes(received[0])
    assert message["To"] == "recipient@example.test"
    assert message.get_body(("plain",)) and message.get_body(("html",))


def test_objection_arriving_during_smtp_setup_prevents_data(
    approved, transport, monkeypatch
):
    original = transport.rcpt

    def rcpt(self, address):
        with admin_db.database() as db:
            db.execute(
                "UPDATE messages SET analysis_kind='contact_objection' WHERE id=1"
            )
        return original(self, address)

    monkeypatch.setattr(transport, "rcpt", rcpt)
    assert delivery.send(1, 2, 1) == "failed"
    assert "data" not in transport.calls


def test_database_failure_after_acceptance_does_not_allow_resend(
    approved, transport, monkeypatch
):
    def crash(*args, **kwargs):
        raise RuntimeError("Synthetic storage failure")

    monkeypatch.setattr(delivery, "finish", crash)
    with pytest.raises(RuntimeError):
        delivery.send(1, 2, 1)
    assert delivery.send(1, 2, 1) == "sending"
    assert transport.calls.count("data") == 1
    with admin_db.database() as db:
        assert (
            db.execute("SELECT count(*) FROM messages WHERE draft_id=1").fetchone()[0]
            == 0
        )


def test_inflight_send_blocks_contact_edit(approved, client, transport):
    delivery.claim(1, 2, 1)
    with admin_db.database() as db:
        contact = dict(db.execute("SELECT * FROM contacts WHERE id=1").fetchone())
    data = {
        k: contact[k]
        for k in [
            "id",
            "organization",
            "person",
            "email",
            "category",
            "status",
            "permission",
            "priority",
            "notes",
            "next_step",
            "next_date",
        ]
    }
    data["email"] = "changed@example.test"
    assert post(client, "/contacts", approved, **data).status_code == 409
    assert not transport.calls
