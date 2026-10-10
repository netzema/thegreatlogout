"""Read-only, domain-filtered IMAP import. Never sends mail or marks mail read."""

from __future__ import annotations

import fcntl
import hashlib
import imaplib
import json
import os
import re
from datetime import UTC
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from server.admin_db import ROOT, database, ensure_schema, message_fingerprint, now
from server.mail_analysis import refresh_analysis
from server.contact_history import inherit_addresses

HEADER_FIELDS = "FROM TO CC BCC DELIVERED-TO ENVELOPE-TO X-ORIGINAL-TO MESSAGE-ID IN-REPLY-TO REFERENCES SUBJECT DATE"
MAX_BYTES = 2_000_000


def addresses(message, fields):
    return {
        address.lower()
        for _, address in getaddresses(
            [str(value) for key in fields for value in message.get_all(key, [])]
        )
        if "@" in address
    }


def permitted(message, sent=False, domains=None):
    domains = domains or {"thegreatlogout.org"}
    fields = (
        ["From"]
        if sent
        else ["To", "Cc", "Delivered-To", "Envelope-To", "X-Original-To"]
    )
    return any(
        address.rsplit("@", 1)[-1] in domains for address in addresses(message, fields)
    )


def literal(data):
    return next(
        (
            part[1]
            for part in data
            if isinstance(part, tuple) and isinstance(part[1], bytes)
        ),
        b"",
    )


class PlainHTML(HTMLParser):
    """Convert an HTML-only message locally without executing or loading anything."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.skip += 1
        elif tag in {"br", "p", "div", "li", "tr"} and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.skip:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def matched_contact(db, refs, peers):
    known = set()
    for ref in refs[-30:]:
        known.update(
            r[0]
            for r in db.execute(
                "SELECT contact_id FROM messages WHERE message_id=? AND contact_id IS NOT NULL",
                (ref,),
            )
        )
    if known:
        return next(iter(known)) if len(known) == 1 else None
    for address in peers:
        known.update(
            r[0]
            for r in db.execute(
                "SELECT id FROM contacts WHERE lower(email)=? UNION SELECT contact_id FROM contact_addresses WHERE address=?",
                (address, address),
            )
        )
    if not known:
        for address in peers:
            known.update(
                r[0]
                for r in db.execute(
                    "SELECT contact_id FROM organization_domains WHERE domain=?",
                    (address.rsplit("@", 1)[-1],),
                )
            )
    return next(iter(known)) if len(known) == 1 else None


def import_message(raw, sent=False, *, history_address=None):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    # A deliberately invoked history import may use a confirmed former address,
    # but only with an explicit campaign subject. The regular worker never sets it.
    if history_address is not None:
        historical = history_address.lower() in addresses(
            message, ["From"] if sent else ["To", "Cc"]
        ) and bool(
            re.search(
                r"\bgreat[\s-]*logout\b", str(message.get("Subject", "")), re.IGNORECASE
            )
        )
        if not historical:
            return 0
    elif not permitted(message, sent):
        return 0
    refs = re.findall(
        r"<[^<>\s]+>",
        str(message.get("References", "")) + " " + str(message.get("In-Reply-To", "")),
    )
    message_id = (
        str(message.get("Message-ID", "")).strip()[:500]
        or "sha256:" + hashlib.sha256(raw).hexdigest()
    )
    content = message.get_body(preferencelist=("plain", "html"))
    try:
        body = (
            str(content.get_content()) if content else "[Kein lesbarer Text vorhanden.]"
        )
        if content and content.get_content_type() == "text/html":
            parser = PlainHTML()
            parser.feed(body)
            body = "".join(parser.parts).strip()
        body = body[:20000]
    except (LookupError, UnicodeError):
        body = "[Text konnte nicht dekodiert werden; Original im Postfach öffnen.]"
    try:
        stamp = parsedate_to_datetime(str(message.get("Date", "")))
        occurred = (
            (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC))
            .astimezone(UTC)
            .isoformat()
        )
    except (ValueError, TypeError, OverflowError):
        occurred = now()
    automated = (
        str(message.get("Auto-Submitted", "no")).lower() != "no"
        or str(message.get("X-Spam-Flag", "")).lower() == "yes"
        or str(message.get("Precedence", "")).lower() in {"bulk", "list", "junk"}
        or bool(message.get("List-Id"))
        or message.get_content_type() == "multipart/report"
    )
    peers = sorted(addresses(message, ["To", "Cc", "Bcc"] if sent else ["From"]))
    peers = [
        p
        for p in peers
        if p.rsplit("@", 1)[-1] != "thegreatlogout.org"
        and p != (history_address or "").lower()
    ]
    senders = sorted(addresses(message, ["From"]))
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM excluded_messages WHERE fingerprint=?",
            (message_fingerprint(message_id),),
        ).fetchone():
            return 0
        cid = matched_contact(db, refs, peers)
        cursor = db.execute(
            """INSERT OR IGNORE INTO messages
            (contact_id,direction,message_id,in_reply_to,subject,body,occurred_at,matched,source,automated,
             sender_address,peer_addresses,references_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid,
                "outbound" if sent else "inbound",
                message_id,
                str(message.get("In-Reply-To", ""))[:500],
                str(message.get("Subject", ""))[:200],
                body,
                occurred,
                int(cid is not None),
                "imap-history" if history_address else "imap",
                int(automated),
                senders[0] if len(senders) == 1 else "",
                json.dumps(peers),
                json.dumps(refs[-30:]),
            ),
        )
        inserted = cursor.rowcount
        # Backfill metadata only; preserve human-reviewed text and assignments.
        if not inserted:
            db.execute(
                "UPDATE messages SET sender_address=?,peer_addresses=?,references_json=? WHERE message_id=? AND peer_addresses='[]'",
                (
                    senders[0] if len(senders) == 1 else "",
                    json.dumps(peers),
                    json.dumps(refs[-30:]),
                    message_id,
                ),
            )
        if inserted and sent and cid:
            match = re.fullmatch(
                r"<tgl-draft-(\d+)-v(\d+)@thegreatlogout\.org>", message_id
            )
            if match:
                draft = db.execute(
                    "SELECT * FROM drafts WHERE id=? AND version=? AND contact_id=? AND status='approved'",
                    (int(match[1]), int(match[2]), cid),
                ).fetchone()
                if draft and draft["approved_recipient"] in peers:
                    db.execute(
                        "UPDATE drafts SET status='sent',updated_at=? WHERE id=?",
                        (now(), draft["id"]),
                    )
                    db.execute(
                        "UPDATE messages SET draft_id=? WHERE message_id=?",
                        (draft["id"], message_id),
                    )
        inherit_addresses(db)
    return inserted


def reconcile_messages():
    changed = 0
    with database() as db:
        # Inbox may precede Sent in an initial import. Revisit after both folders.
        while True:
            progress = 0
            for row in db.execute("SELECT * FROM messages WHERE matched=0").fetchall():
                cid = matched_contact(
                    db,
                    json.loads(row["references_json"]),
                    json.loads(row["peer_addresses"]),
                )
                if cid:
                    db.execute(
                        "UPDATE messages SET contact_id=?,matched=1 WHERE id=?",
                        (cid, row["id"]),
                    )
                    progress += 1
            changed += progress
            if not progress:
                break
        # An already answered historical reply must not look like a new task.
        for row in db.execute(
            "SELECT * FROM messages WHERE direction='outbound'"
        ).fetchall():
            refs = set(json.loads(row["references_json"]))
            refs.update(re.findall(r"<[^<>\s]+>", row["in_reply_to"]))
            for ref in refs:
                db.execute(
                    """UPDATE messages SET reviewed_at=? WHERE message_id=? AND direction='inbound'
                    AND contact_id=? AND reviewed_at IS NULL AND occurred_at<=?""",
                    (now(), ref, row["contact_id"], row["occurred_at"]),
                )
        db.execute(
            """UPDATE contacts SET status='dialogue',updated_at=? WHERE status NOT IN ('closed','paused')
            AND EXISTS (SELECT 1 FROM messages WHERE contact_id=contacts.id AND direction='inbound' AND automated=0)""",
            (now(),),
        )
    return changed


def sync_folder(client, folder, sent=False, domains=None):
    typ, _ = client.select(folder, readonly=True)
    if typ != "OK":
        raise RuntimeError("Mailbox folder unavailable")
    response = client.response("UIDVALIDITY")[1]
    validity = response[0].decode() if response and response[0] else ""
    if not validity.isdigit():
        raise RuntimeError("Mailbox UIDVALIDITY unavailable")
    with database() as db:
        cursor = db.execute(
            "SELECT * FROM mail_cursors WHERE folder=?", (folder,)
        ).fetchone()
    last = cursor["last_uid"] if cursor and cursor["uidvalidity"] == validity else 0
    typ, items = client.uid("search", None, f"UID {last + 1}:*")
    if typ != "OK":
        raise RuntimeError("Mailbox search failed")
    pending = sorted(
        int(item) for item in (items[0] or b"").split() if int(item) > last
    )
    processed, checked, accepted = 0, 0, 0
    for uid in pending[:200]:
        if uid <= last:
            continue
        typ, data = client.uid(
            "fetch",
            str(uid),
            f"(RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])",
        )
        if typ != "OK" or not literal(data):
            raise RuntimeError("Mailbox header fetch failed")
        header = BytesParser(policy=policy.default).parsebytes(literal(data))
        sizes = [
            int(size)
            for part in data
            if isinstance(part, tuple)
            for size in re.findall(rb"RFC822.SIZE (\d+)", part[0])
        ]
        checked += 1
        if permitted(header, sent, domains) and sizes and max(sizes) <= MAX_BYTES:
            accepted += 1
            typ, full = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not literal(full):
                raise RuntimeError("Mailbox body fetch failed")
            processed += import_message(literal(full), sent)
        # Rejected/private messages retain no headers, subjects, or bodies.
        with database() as db:
            db.execute(
                "INSERT OR IGNORE INTO mail_seen VALUES (?,?,?)",
                (folder, validity, uid),
            )
            db.execute(
                "INSERT OR REPLACE INTO mail_cursors VALUES (?,?,?)",
                (folder, validity, uid),
            )
    with database() as db:
        db.execute(
            "INSERT OR REPLACE INTO mail_sync_stats VALUES (?,?,?,?,?,?)",
            (
                folder,
                checked,
                accepted,
                processed,
                max(0, len(pending) - checked),
                now(),
            ),
        )
    return processed


def run_sync():
    ensure_schema()
    user, password = (
        os.getenv("OUTREACH_IMAP_USER"),
        os.getenv("OUTREACH_IMAP_PASSWORD"),
    )
    count, status = 0, "not_configured"
    if user and password:
        domains = {
            x.strip().lower()
            for x in os.getenv("OUTREACH_ALLOWED_DOMAINS", "thegreatlogout.org").split(
                ","
            )
            if x.strip()
        }
        if not domains or domains != {"thegreatlogout.org"}:
            raise RuntimeError("Only the campaign domain is allowed in this deployment")
        try:
            with imaplib.IMAP4_SSL(
                os.getenv("OUTREACH_IMAP_HOST", "imap.mailbox.org"), timeout=30
            ) as client:
                client.login(user, password)
                count += sync_folder(client, "INBOX", domains=domains)
                count += sync_folder(
                    client,
                    os.getenv("OUTREACH_SENT_FOLDER", "Sent"),
                    sent=True,
                    domains=domains,
                )
            reconcile_messages()
            refresh_analysis()
            status = "ok"
        except Exception:  # noqa: BLE001 — Do not log provider errors, headers, addresses, or secrets.
            status = "error"
    with database() as db:
        db.execute(
            "INSERT OR REPLACE INTO job_runs VALUES (?,?,?,?)",
            ("mail_sync", now(), status, count),
        )
    if status in {"error", "not_configured"}:
        raise SystemExit("Mailbox sync failed; check server configuration.")


def main():
    # One lock across user/system timers and manual runs, including backfill.
    lock_path = ROOT / "data" / "mail-sync.lock"
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        run_sync()


if __name__ == "__main__":
    main()
