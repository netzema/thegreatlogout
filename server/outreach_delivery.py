"""Explicit, review-bound SMTP submission. No automatic sending or retry worker."""

import html
import fcntl
from contextlib import contextmanager
import imaplib
import json
import os
import smtplib
import ssl
import time
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime

from server import admin_db as storage
from server import mail_threads, opportunity_quality as quality
from server.contact_history import valid_address
from server.outreach import eligible


class DeliveryError(Exception):
    """Contains only a fixed, safe explanation for the admin interface."""


def configuration():
    return {
        "host": os.getenv("OUTREACH_SMTP_HOST", "smtp.mailbox.org"),
        "port": os.getenv("OUTREACH_SMTP_PORT", "587"),
        "user": os.getenv("OUTREACH_SMTP_USER", os.getenv("OUTREACH_IMAP_USER", "")),
        "password": os.getenv(
            "OUTREACH_SMTP_PASSWORD", os.getenv("OUTREACH_IMAP_PASSWORD", "")
        ),
        "sender": os.getenv("OUTREACH_FROM", ""),
        "reply_to": os.getenv("OUTREACH_REPLY_TO", ""),
    }


def available():
    cfg = configuration()
    return (
        os.getenv("OUTREACH_DIRECT_SEND_ENABLED") == "1"
        and bool(cfg["user"] and cfg["password"] and cfg["host"])
        and cfg["port"] in {"465", "587"}
        and valid_address(cfg["sender"])
        and valid_address(cfg["reply_to"])
    )


def assert_editable(db, draft_id=None, *, contact_id=None):
    sql = "SELECT 1 FROM outreach_deliveries s JOIN drafts d ON d.id=s.draft_id WHERE s.status IN ('sending','unknown') AND "
    if db.execute(
        sql + ("d.contact_id=?" if contact_id else "d.id=?"), (contact_id or draft_id,)
    ).fetchone():
        raise DeliveryError(
            "Versand läuft oder sein Ergebnis ist noch unklar. Zuerst den Versandstatus prüfen."
        )


def require_approved(db, did, version):
    draft = db.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
    if not draft or draft["status"] != "approved" or draft["version"] != version:
        raise DeliveryError(
            "Aktuelle Freigabe erforderlich. Bitte den Entwurf neu laden."
        )
    try:
        quality.require_draft(db, draft)
    except ValueError as exc:
        raise DeliveryError(str(exc)) from exc
    contact = db.execute(
        "SELECT * FROM contacts WHERE id=?", (draft["contact_id"],)
    ).fetchone()
    if (
        not eligible(db, contact["id"])
        or contact["permission"] not in {"allowed", "existing"}
        or not valid_address(draft["approved_recipient"])
        or draft["approved_recipient"] != contact["email"]
    ):
        raise DeliveryError(
            "Empfänger oder Kontaktberechtigung haben sich geändert. Erneute Prüfung erforderlich."
        )
    conflict = db.execute(
        "SELECT id FROM contacts WHERE lower(email)=lower(?) AND id!=? UNION SELECT contact_id FROM contact_addresses WHERE address=? AND contact_id!=?",
        (
            draft["approved_recipient"],
            contact["id"],
            draft["approved_recipient"],
            contact["id"],
        ),
    ).fetchone()
    if conflict:
        raise DeliveryError("Empfängeradresse ist einem anderen Kontakt zugeordnet.")
    return draft


def render_message(db, draft, cfg):
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = cfg["sender"]
    message["To"] = draft["approved_recipient"]
    message["Reply-To"] = cfg["reply_to"]
    message["Subject"] = draft["subject"]
    message["Date"] = format_datetime(datetime.now(UTC))
    message["Message-ID"] = (
        f"<tgl-draft-{draft['id']}-v{draft['version']}@thegreatlogout.org>"
    )
    try:
        mail_threads.apply_headers(db, message, draft)
    except ValueError as exc:
        raise DeliveryError(str(exc)) from exc
    message.set_content(draft["body"], cte="quoted-printable")
    # The same approved words in both formats, without trackers or external images.
    message.add_alternative(
        '<!doctype html><html><body><div style="white-space:pre-wrap;font-family:Arial,sans-serif;line-height:1.5">'
        + html.escape(draft["body"])
        + "</div></body></html>",
        subtype="html",
        cte="quoted-printable",
    )
    return message


def claim(did, version, uid):
    if not available():
        raise DeliveryError(
            "Direkter Versand ist noch nicht aktiviert oder der Postfachzugang fehlt."
        )
    cfg = configuration()
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM outreach_deliveries WHERE draft_id=?", (did,)
        ).fetchone()
        if existing and existing["status"] in {"sending", "unknown", "sent"}:
            return dict(existing), False
        draft = require_approved(db, did, version)
        if db.execute("SELECT 1 FROM messages WHERE draft_id=?", (did,)).fetchone():
            raise DeliveryError(
                "Für diesen Entwurf ist bereits ein Versand protokolliert."
            )
        message = render_message(db, draft, cfg)
        raw = message.as_bytes()
        db.execute(
            """INSERT INTO outreach_deliveries
            (draft_id,draft_version,user_id,status,message_id,mime,recipient,sender,created_at,updated_at)
            VALUES (?,?,?,'sending',?,?,?,?,?,?) ON CONFLICT(draft_id) DO UPDATE SET
            draft_version=excluded.draft_version,user_id=excluded.user_id,status='sending',
            message_id=excluded.message_id,mime=excluded.mime,recipient=excluded.recipient,
            sender=excluded.sender,updated_at=excluded.updated_at,accepted_at=NULL,
            attempts=outreach_deliveries.attempts+1,note='',archive_status='pending'""",
            (
                did,
                version,
                uid,
                message["Message-ID"],
                raw,
                draft["approved_recipient"],
                cfg["sender"],
                storage.now(),
                storage.now(),
            ),
        )
        row = dict(
            db.execute(
                "SELECT * FROM outreach_deliveries WHERE draft_id=?", (did,)
            ).fetchone()
        )
    return row, True


def submit(row):
    """A positive DATA response is acceptance; QUIT cannot undo it."""
    cfg = configuration()
    smtp, data_started = None, False
    try:
        if cfg["port"] == "465":
            smtp = smtplib.SMTP_SSL(
                cfg["host"], 465, timeout=20, context=ssl.create_default_context()
            )
        elif cfg["port"] == "587":
            smtp = smtplib.SMTP(cfg["host"], 587, timeout=20)
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
        else:
            raise DeliveryError("Ungültige SMTP-Portkonfiguration.")
        smtp.ehlo()
        smtp.login(cfg["user"], cfg["password"])
        with storage.database() as db:
            require_approved(db, row["draft_id"], row["draft_version"])
        code, _ = smtp.mail(row["sender"])
        if code != 250:
            return (
                "failed",
                "Der Mailserver hat den Absender abgelehnt. Es wurde nichts versendet.",
            )
        code, _ = smtp.rcpt(row["recipient"])
        if code not in {250, 251}:
            return (
                "failed",
                "Der Mailserver hat den Empfänger abgelehnt. Es wurde nichts versendet.",
            )
        with storage.database() as db:
            require_approved(db, row["draft_id"], row["draft_version"])
        data_started = True
        code, _ = smtp.data(row["mime"])
        if code == 250:
            return (
                "sent",
                "Vom Mailserver zum Versand angenommen. Die Zustellung beim Empfänger ist damit noch nicht bestätigt.",
            )
        return (
            "failed",
            "Der Mailserver hat die Nachricht abgelehnt. Es wurde nichts versendet.",
        )
    except smtplib.SMTPResponseException:
        return (
            "failed",
            "Der Mailserver hat die Anfrage abgelehnt. Zugang oder Nachricht prüfen.",
        )
    except DeliveryError:
        return (
            "failed",
            "Die Freigabe ist nicht mehr gültig. Es wurde nichts versendet.",
        )
    except Exception:
        if data_started:
            return (
                "unknown",
                "Verbindung nach Beginn der Übertragung abgebrochen. Versandstatus unklar. Nicht erneut senden, bevor der Versand geprüft wurde.",
            )
        return (
            "failed",
            "Die Verbindung zum Postfach ist fehlgeschlagen. Es wurde nichts versendet.",
        )
    finally:
        if smtp:
            try:
                smtp.close()
            except Exception:
                pass


def finish(db, row, *, accepted_at=None):
    """Atomic acceptance record, independent of Sent-folder copying."""
    stamp = accepted_at or storage.now()
    message = BytesParser(policy=policy.default).parsebytes(row["mime"])
    draft = db.execute("SELECT * FROM drafts WHERE id=?", (row["draft_id"],)).fetchone()
    db.execute(
        "UPDATE outreach_deliveries SET status='sent',accepted_at=?,updated_at=?,note=? WHERE draft_id=?",
        (
            stamp,
            storage.now(),
            "Vom Mailserver zum Versand angenommen.",
            row["draft_id"],
        ),
    )
    db.execute(
        """INSERT OR IGNORE INTO messages
        (contact_id,draft_id,direction,message_id,in_reply_to,subject,body,occurred_at,source,sender_address,peer_addresses,references_json)
        VALUES (?,?,'outbound',?,?,?,?,?,'smtp',?,?,?)""",
        (
            draft["contact_id"],
            row["draft_id"],
            row["message_id"],
            str(message.get("In-Reply-To", "")),
            str(message["Subject"]),
            message.get_body(preferencelist=("plain",)).get_content().rstrip("\r\n"),
            stamp,
            row["sender"],
            json.dumps([row["recipient"]]),
            json.dumps(str(message.get("References", "")).split()),
        ),
    )
    db.execute(
        "UPDATE drafts SET status='sent',version=version+1,updated_at=? WHERE id=? AND status!='sent'",
        (stamp, row["draft_id"]),
    )
    db.execute(
        "UPDATE contacts SET status='contacted',updated_at=? WHERE id=?",
        (stamp, draft["contact_id"]),
    )


def archive(row):
    """No SMTP retry when copying to Sent fails. Never change import scope."""
    status = "failed"
    try:
        with imaplib.IMAP4_SSL(
            os.getenv("OUTREACH_IMAP_HOST", "imap.mailbox.org"), timeout=20
        ) as client:
            client.login(
                os.environ["OUTREACH_IMAP_USER"], os.environ["OUTREACH_IMAP_PASSWORD"]
            )
            folder = os.getenv("OUTREACH_SENT_FOLDER", "Sent")
            # Check before APPEND to avoid duplicates if the provider already saved it.
            result, _ = client.select(folder, readonly=True)
            if result != "OK":
                raise ValueError("Sent folder unavailable")
            result, data = client.uid(
                "search", None, "HEADER", "Message-ID", '"' + row["message_id"] + '"'
            )
            if result != "OK":
                raise ValueError("Search failed")
            if not data or not data[0]:
                result, _ = client.append(
                    folder,
                    "\\Seen",
                    imaplib.Time2Internaldate(time.time()),
                    row["mime"],
                )
                if result != "OK":
                    raise ValueError("Archive failed")
            status = "done"
    except Exception:
        pass  # Provider errors can contain credentials or addresses.
    with storage.database() as db:
        db.execute(
            "UPDATE outreach_deliveries SET archive_status=? WHERE draft_id=? AND status='sent'",
            (status, row["draft_id"]),
        )
    return status


def _send(did, version, uid):
    row, claimed = claim(did, version, uid)
    if not claimed:
        return row["status"]
    status, note = submit(row)
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        if status == "sent":
            finish(db, row)
        else:
            db.execute(
                "UPDATE outreach_deliveries SET status=?,note=?,updated_at=? WHERE draft_id=?",
                (status, note, storage.now(), did),
            )
    if status == "sent":
        archive(row)
    return status


def recover_stalled(db):
    # An interrupted process can never safely re-send a claimed message.
    db.execute(
        "UPDATE outreach_deliveries SET status='unknown',note='Der Versandlauf wurde unterbrochen. Versandstatus vor einem erneuten Versuch prüfen.',updated_at=? WHERE status='sending' AND julianday(updated_at)<julianday('now','-5 minutes')",
        (storage.now(),),
    )


@contextmanager
def delivery_lock(did):
    path = storage.DB_PATH.parent / f"delivery-{int(did)}.lock"
    with path.open("w") as lock:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeliveryError(
                "Der Versand wird gerade verarbeitet. Bitte den Status neu laden."
            ) from None
        yield


def send(did, version, uid):
    with delivery_lock(did):
        return _send(did, version, uid)


def resolve(did, uid, decision, note, occurred):
    with delivery_lock(did), storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        recover_stalled(db)
        row = db.execute(
            "SELECT * FROM outreach_deliveries WHERE draft_id=? AND status='unknown'",
            (did,),
        ).fetchone()
        if not row or not note.strip() or decision not in {"sent", "not_sent"}:
            raise DeliveryError(
                "Unklarer Versand und dokumentierte Prüfung erforderlich."
            )
        if decision == "sent":
            if not occurred:
                raise DeliveryError("Das tatsächliche Versanddatum fehlt.")
            finish(db, row, accepted_at=occurred)
            db.execute(
                "UPDATE outreach_deliveries SET note='Versand nach Prüfung manuell bestätigt.',archive_status='manual' WHERE draft_id=?",
                (did,),
            )
            db.execute(
                "UPDATE messages SET source='smtp-confirmed' WHERE draft_id=?", (did,)
            )
        else:
            db.execute(
                "UPDATE outreach_deliveries SET status='failed',note='Nach Prüfung als nicht versendet bestätigt. Vor einem neuen Versuch erneut freigeben.',updated_at=? WHERE draft_id=?",
                (storage.now(), did),
            )
            db.execute(
                "UPDATE drafts SET status='draft',version=version+1,review_at=NULL,approved_recipient='' WHERE id=?",
                (did,),
            )
        db.execute(
            "INSERT INTO reviews(draft_id,user_id,action,note,created_at) VALUES (?,?,?,?,?)",
            (did, uid, "delivery_" + decision, note, storage.now()),
        )
