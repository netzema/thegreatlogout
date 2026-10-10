from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pwdlib import PasswordHash

from server import admin_db as storage
from server import analytics, outreach
from server.contact_history import inherit_addresses, valid_address

ADMIN_ORIGIN = os.getenv("ADMIN_ORIGIN", "https://admin.thegreatlogout.org").rstrip("/")
COOKIE = "__Host-tgl_admin"
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash(secrets.token_urlsafe(24))
BASE = Path(__file__).resolve().parent
STATUS = {"researched", "contacted", "no_response", "dialogue", "paused", "closed"}
PERMISSIONS = {"unknown", "existing", "allowed", "blocked"}
CATEGORIES = {"media", "ngo", "science", "sport", "creator", "other"}


@asynccontextmanager
async def lifespan(app):
    storage.ensure_schema()
    with storage.database() as db:
        inherit_addresses(db)
    yield


app = FastAPI(
    title="The Great Logout Admin",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.include_router(analytics.router)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def message_key(row):
    # Bind forms to the displayed record even when SQLite later reuses an ID.
    return storage.message_fingerprint(
        json.dumps(
            [
                row[k]
                for k in (
                    "id",
                    "message_id",
                    "occurred_at",
                    "direction",
                    "subject",
                    "body",
                )
            ]
        )
    )


templates.env.globals["message_key"] = message_key
templates.env.globals["assisted_workflow"] = True


def checked_message(db, message_id, data):
    row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not row or not hmac.compare_digest(
        field(data, "message_key", 64), message_key(row)
    ):
        raise HTTPException(
            409, "Nachricht wurde geändert oder entfernt. Bitte neu laden."
        )
    return row


def redirect(path):
    return RedirectResponse(path, status_code=303)


def render(request, name, **context):
    return templates.TemplateResponse(
        request,
        name,
        {
            "user": getattr(request.state, "user", None),
            "csrf": getattr(request.state, "csrf", ""),
            **context,
        },
    )


@app.middleware("http")
async def security(request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in {
        urlsplit(ADMIN_ORIGIN).hostname,
        "127.0.0.1",
        "localhost",
        "testserver",
    }:
        return Response(status_code=400)
    path = request.url.path
    request.state.user = None
    request.state.csrf = ""
    public = path in {"/login", "/health", "/api/analytics/events"} or path.startswith(
        "/static/"
    )
    token = request.cookies.get(COOKIE, "")
    if token and path != "/api/analytics/events":
        with storage.database() as db:
            row = db.execute(
                """SELECT users.id, users.email, sessions.csrf FROM sessions
                JOIN users ON users.id=sessions.user_id
                WHERE token_hash=? AND expires_at>? AND users.active=1""",
                (hashlib.sha256(token.encode()).hexdigest(), storage.now()),
            ).fetchone()
        if row:
            request.state.user = dict(row)
            request.state.csrf = row["csrf"]
    if not public and not request.state.user:
        return redirect("/login")
    if (
        request.method == "POST"
        and path != "/api/analytics/events"
        and request.headers.get("origin", "").rstrip("/") != ADMIN_ORIGIN
    ):
        return Response(
            "Ungültiger Ursprung.", status_code=403, media_type="text/plain"
        )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'none'; style-src 'self'; "
        "img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return response


async def form(request):
    data = await request.form(max_fields=30, max_files=0)
    if not hmac.compare_digest(str(data.get("csrf", "")), request.state.csrf):
        raise HTTPException(403, "Ungültige Formularfreigabe. Bitte neu laden.")
    return data


def field(data, key, limit=500, required=False):
    value = str(data.get(key, "")).strip()
    if len(value) > limit or "\x00" in value or (required and not value):
        raise HTTPException(400, "Bitte Eingaben und Feldlängen prüfen.")
    return value


def choice(data, key, options):
    value = field(data, key)
    if value not in options:
        raise HTTPException(400, "Ungültige Auswahl.")
    return value


def integer(data, key):
    try:
        return int(data.get(key, 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Ungültige Auswahl.") from None


def date_field(data, key):
    value = field(data, key, 10)
    if value:
        try:
            datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            raise HTTPException(400, "Ungültiges Datum.") from None
    return value


def contact(db, contact_id):
    row = db.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Kontakt nicht gefunden.")
    return row


@app.get("/health")
def health():
    with storage.database() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", error=None)


@app.post("/login")
async def login(request: Request):
    data = await request.form(max_fields=3, max_files=0)
    email = field(data, "email", 254).lower()
    password = field(data, "password", 1024)
    with storage.database() as db:
        user = db.execute(
            "SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)
        ).fetchone()
        try:
            valid = password_hash.verify(
                password, user["password_hash"] if user else DUMMY_HASH
            )
        except (ValueError, TypeError):
            valid = False
        if not user or not valid:
            return render(request, "login.html", error="Anmeldung fehlgeschlagen.")
        token = secrets.token_urlsafe(32)
        old = request.cookies.get(COOKIE, "")
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (hashlib.sha256(old.encode()).hexdigest(),),
        )
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                secrets.token_urlsafe(32),
                (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
            ),
        )
    response = redirect("/")
    response.set_cookie(
        COOKIE, token, secure=True, httponly=True, samesite="strict", max_age=43200
    )
    return response


@app.post("/logout")
async def logout(request: Request):
    await form(request)
    with storage.database() as db:
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),),
        )
    response = redirect("/login")
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with storage.database() as db:
        counts = {
            key: db.execute(query).fetchone()[0]
            for key, query in {
                "contacts": "SELECT count(*) FROM contacts",
                "reviews": "SELECT count(*) FROM drafts WHERE status IN ('draft','approved')",
                "answers": "SELECT count(*) FROM messages WHERE direction='inbound'",
                "unmatched": "SELECT count(*) FROM messages WHERE matched=0",
            }.items()
        }
        due = db.execute(
            "SELECT * FROM contacts WHERE next_date!='' AND next_date<=? "
            "AND status NOT IN ('closed','paused') ORDER BY next_date",
            (storage.now()[:10],),
        ).fetchall()
        jobs = db.execute("SELECT * FROM job_runs ORDER BY name").fetchall()
    return render(request, "dashboard.html", counts=counts, due=due, jobs=jobs)


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, days: int = 30):
    return render(request, "analytics.html", report=analytics.report(days))


@app.get("/contacts", response_class=HTMLResponse)
def contacts(request: Request, q: str = ""):
    with storage.database() as db:
        rows = db.execute(
            "SELECT * FROM contacts WHERE organization LIKE ? OR person LIKE ? "
            "ORDER BY priority, organization LIMIT 500",
            ("%" + q[:100] + "%",) * 2,
        ).fetchall()
    return render(request, "contacts.html", contacts=rows, q=q[:100])


@app.get("/contacts/{contact_id}", response_class=HTMLResponse)
def contact_page(request: Request, contact_id: int):
    with storage.database() as db:
        row = contact(db, contact_id)
        history = db.execute(
            "SELECT * FROM messages WHERE contact_id=? ORDER BY occurred_at DESC",
            (contact_id,),
        ).fetchall()
        drafts = db.execute(
            "SELECT * FROM drafts WHERE contact_id=? ORDER BY id DESC", (contact_id,)
        ).fetchall()
    return render(request, "contact.html", contact=row, history=history, drafts=drafts)


@app.post("/contacts")
async def save_contact(request: Request):
    data = await form(request)
    contact_id = integer(data, "id")
    message_id = integer(data, "message_id")
    email = field(data, "email", 254).lower()
    if email and (
        email.count("@") != 1
        or any(c.isspace() for c in email)
        or "\r" in email
        or "\n" in email
    ):
        raise HTTPException(400, "Ungültige E-Mail-Adresse.")
    priority = integer(data, "priority")
    if priority not in {1, 2, 3}:
        raise HTTPException(400, "Ungültige Priorität.")
    values = (
        field(data, "organization", 200, True),
        field(data, "person", 150),
        email,
        choice(data, "category", CATEGORIES),
        choice(data, "status", STATUS),
        choice(data, "permission", PERMISSIONS),
        priority,
        field(data, "notes", 12000),
        field(data, "next_step", 1000),
        date_field(data, "next_date"),
        storage.now(),
    )
    try:
        with storage.database() as db:
            db.execute("BEGIN IMMEDIATE")
            if message_id:
                message = checked_message(db, message_id, data)
                if contact_id or message["matched"]:
                    raise HTTPException(
                        409, "Nachricht ist bereits zugeordnet. Bitte neu laden."
                    )
            if contact_id:
                previous = contact(db, contact_id)
                if previous["email"] != email or previous["permission"] != values[5]:
                    db.execute(
                        "UPDATE drafts SET status='draft',version=version+1,review_at=NULL "
                        "WHERE contact_id=? AND status='approved'",
                        (contact_id,),
                    )
                db.execute(
                    """UPDATE contacts SET organization=?,person=?,email=?,category=?,status=?,
                    permission=?,priority=?,notes=?,next_step=?,next_date=?,updated_at=? WHERE id=?""",
                    (*values, contact_id),
                )
            else:
                contact_id = db.execute(
                    """INSERT INTO contacts
                    (organization,person,email,category,status,permission,priority,notes,next_step,next_date,
                    updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*values, storage.now()),
                ).lastrowid
            if message_id:
                db.execute(
                    "UPDATE messages SET contact_id=?,matched=1 WHERE id=?",
                    (contact_id, message_id),
                )
    except sqlite3.IntegrityError:
        raise HTTPException(
            409, "Diese Adresse ist bereits einem Kontakt zugeordnet."
        ) from None
    with storage.database() as db:
        inherit_addresses(db)
    return redirect("/review" if message_id else f"/contacts/{contact_id}")


@app.post("/drafts")
async def save_draft(request: Request):
    data = await form(request)
    cid, did = integer(data, "contact_id"), integer(data, "id")
    subject = field(data, "subject", 200, True)
    if "\r" in subject or "\n" in subject:
        raise HTTPException(400, "Betreff muss einzeilig sein.")
    values = (
        subject,
        field(data, "body", 20000, True),
        field(data, "framing", 100),
        field(data, "campaign", 100),
        integer(data, "reply_message_id") or None,
        storage.now(),
    )
    with storage.database() as db:
        contact(db, cid)
        if (
            values[-2]
            and not db.execute(
                "SELECT id FROM messages WHERE id=? AND contact_id=?",
                (values[-2], cid),
            ).fetchone()
        ):
            raise HTTPException(400, "Antwortbezug passt nicht zum Kontakt.")
        if did:
            changed = db.execute(
                """UPDATE drafts SET subject=?,body=?,framing=?,campaign=?,reply_message_id=?,updated_at=?,
                status='draft',version=version+1,review_at=NULL WHERE id=? AND contact_id=?
                AND version=? AND status!='sent' """,
                (*values, did, cid, integer(data, "version")),
            )
            if changed.rowcount != 1:
                raise HTTPException(
                    409,
                    "Entwurf wurde bereits geändert oder versendet. Bitte neu laden.",
                )
        else:
            db.execute(
                """INSERT INTO drafts (subject,body,framing,campaign,reply_message_id,updated_at,contact_id,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (*values, cid, storage.now()),
            )
    return redirect("/review")


@app.get("/review", response_class=HTMLResponse)
def review(request: Request):
    with storage.database() as db:
        drafts = db.execute("""SELECT drafts.*,contacts.organization,contacts.permission,contacts.notes,
            contacts.next_step,contacts.email,contacts.email_source FROM drafts JOIN contacts ON contacts.id=drafts.contact_id
            WHERE drafts.status!='sent' ORDER BY CASE drafts.status WHEN 'draft' THEN 0
            WHEN 'approved' THEN 1 ELSE 2 END, drafts.updated_at DESC""").fetchall()
        unmatched = db.execute(
            "SELECT * FROM messages WHERE matched=0 ORDER BY occurred_at DESC"
        ).fetchall()
        unmatched = [dict(row) for row in unmatched]
        for row in unmatched:
            peers = json.loads(row["peer_addresses"])
            row["suggested_email"] = peers[0] if len(peers) == 1 else ""
        issues = db.execute(
            "SELECT contact_address_issues.*,contacts.organization FROM contact_address_issues JOIN contacts ON contacts.id=contact_id"
        ).fetchall()
        contacts_list = db.execute(
            "SELECT id,organization FROM contacts ORDER BY organization"
        ).fetchall()
        replies = db.execute("""SELECT messages.*,contacts.organization FROM messages
            JOIN contacts ON contacts.id=messages.contact_id WHERE direction='inbound'
            AND matched=1 AND automated=0 AND reviewed_at IS NULL ORDER BY occurred_at DESC""").fetchall()
    return render(
        request,
        "review.html",
        drafts=drafts,
        unmatched=unmatched,
        contacts=contacts_list,
        replies=replies,
        address_issues=issues,
    )


@app.post("/drafts/{draft_id}/review")
async def decide(request: Request, draft_id: int):
    data = await form(request)
    action = choice(data, "action", {"approved", "deferred", "rejected"})
    note = field(data, "note", 1000)
    defer_until = date_field(data, "deferred_until")
    if action == "deferred" and not defer_until:
        defer_until = (datetime.now(UTC) + timedelta(days=7)).date().isoformat()
    if action == "deferred" and defer_until <= storage.now()[:10]:
        raise HTTPException(400, "Bitte ein zukünftiges Wiedervorlagedatum wählen.")
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if (
            not row
            or row["version"] != integer(data, "version")
            or row["status"] == "sent"
        ):
            raise HTTPException(409, "Entwurf wurde geändert. Bitte neu laden.")
        recipient = contact(db, row["contact_id"])
        approved_email = ""
        if action == "approved":
            approved_email = field(data, "recipient", 254).lower() or recipient["email"]
            if (
                not valid_address(approved_email)
                or recipient["permission"] == "blocked"
            ):
                raise HTTPException(400, "Empfänger fehlt oder Kontakt ist gesperrt.")
            if (
                recipient["permission"] not in {"allowed", "existing"}
                and field(data, "contact_review") != "confirmed"
            ):
                raise HTTPException(
                    400, "Kontakt bitte direkt in diesem Review prüfen."
                )
            if not outreach.eligible(db, recipient["id"]):
                raise HTTPException(
                    400, "Kontakt pausiert oder Kontaktwiderspruch noch ungeprüft."
                )
            conflict = db.execute(
                "SELECT id FROM contacts WHERE lower(email)=? AND id!=? UNION SELECT contact_id FROM contact_addresses WHERE address=? AND contact_id!=?",
                (approved_email, recipient["id"], approved_email, recipient["id"]),
            ).fetchone()
            if conflict:
                raise HTTPException(409, "Adresse gehört zu einem anderen Kontakt.")
            if approved_email != recipient["email"]:
                db.execute(
                    "UPDATE drafts SET status='draft',version=version+1,review_at=NULL WHERE contact_id=? AND status='approved' AND id!=?",
                    (recipient["id"], draft_id),
                )
            db.execute(
                "UPDATE contacts SET email=?,permission=CASE WHEN permission='unknown' THEN 'allowed' ELSE permission END,updated_at=? WHERE id=?",
                (approved_email, storage.now(), recipient["id"]),
            )
        db.execute(
            "UPDATE drafts SET approved_recipient=?,deferred_until=? WHERE id=?",
            (approved_email, defer_until if action == "deferred" else "", draft_id),
        )
        db.execute(
            "UPDATE drafts SET status=?,review_note=?,review_at=?,updated_at=?,version=version+1 WHERE id=?",
            (action, note, storage.now(), storage.now(), draft_id),
        )
        db.execute(
            "INSERT INTO reviews (draft_id,user_id,action,note,created_at) VALUES (?,?,?,?,?)",
            (draft_id, request.state.user["id"], action, note, storage.now()),
        )
    return redirect("/review")


@app.post("/drafts/{draft_id}/export")
async def export_draft(request: Request, draft_id: int):
    data = await form(request)
    with storage.database() as db:
        row = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if (
            not row
            or row["status"] != "approved"
            or row["version"] != integer(data, "version")
        ):
            raise HTTPException(409, "Aktuelle Freigabe erforderlich.")
        recipient = contact(db, row["contact_id"])
        if (
            recipient["permission"] not in {"allowed", "existing"}
            or not recipient["email"]
            or (
                row["approved_recipient"]
                and row["approved_recipient"] != recipient["email"]
            )
            or not outreach.eligible(db, recipient["id"])
        ):
            raise HTTPException(400, "Versandberechtigung fehlt.")
    message = EmailMessage()
    message["To"] = recipient["email"]
    message["Subject"] = row["subject"]
    message["X-Unsent"] = "1"
    message["Message-ID"] = (
        f"<tgl-draft-{draft_id}-v{row['version']}@thegreatlogout.org>"
    )
    sender, reply_to = (
        os.getenv("OUTREACH_FROM", ""),
        os.getenv("OUTREACH_REPLY_TO", ""),
    )
    if valid_address(sender):
        message["From"] = sender
    if valid_address(reply_to):
        message["Reply-To"] = reply_to
    with storage.database() as db:
        previous = db.execute(
            "SELECT message_id FROM messages WHERE id=? AND contact_id=? AND message_id LIKE '<%>'",
            (row["reply_message_id"], row["contact_id"]),
        ).fetchone()
    if (
        previous
        and "\r" not in previous["message_id"]
        and "\n" not in previous["message_id"]
    ):
        message["In-Reply-To"] = previous["message_id"]
        message["References"] = previous["message_id"]
    message.set_content(row["body"])
    return Response(
        message.as_bytes(),
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="draft-{draft_id}.eml"'},
    )


@app.post("/messages")
async def log_message(request: Request):
    data = await form(request)
    cid = integer(data, "contact_id")
    direction = choice(data, "direction", {"inbound", "outbound"})
    did = integer(data, "draft_id") or None
    logged_mid = None
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        contact(db, cid)
        if did:
            row = db.execute(
                "SELECT * FROM drafts WHERE id=? AND contact_id=?", (did, cid)
            ).fetchone()
            if (
                not row
                or row["status"] != "approved"
                or row["version"] != integer(data, "version")
            ):
                raise HTTPException(
                    409,
                    "Aktuelle Freigabe erforderlich; bereits protokollierte Sendungen werden nicht wiederholt.",
                )
            subject, body = row["subject"], row["body"]
            logged_mid = f"<tgl-draft-{did}-v{row['version']}@thegreatlogout.org>"
            direction = "outbound"
            db.execute(
                "UPDATE drafts SET status='sent',version=version+1,updated_at=? WHERE id=?",
                (storage.now(), did),
            )
        else:
            subject, body = (
                field(data, "subject", 200, True),
                field(data, "body", 20000, True),
            )
        occurred = date_field(data, "occurred_at")
        if not occurred:
            raise HTTPException(400, "Datum erforderlich.")
        db.execute(
            """INSERT INTO messages (contact_id,draft_id,direction,subject,body,occurred_at,message_id)
            VALUES (?,?,?,?,?,?,?)""",
            (cid, did, direction, subject, body, occurred, logged_mid),
        )
        db.execute(
            "UPDATE contacts SET status=?,updated_at=? WHERE id=?",
            ("dialogue" if direction == "inbound" else "contacted", storage.now(), cid),
        )
    return redirect(f"/contacts/{cid}")


@app.post("/messages/{message_id}/match")
async def match_message(request: Request, message_id: int):
    data = await form(request)
    cid = integer(data, "contact_id")
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = checked_message(db, message_id, data)
        if row["matched"]:
            raise HTTPException(
                409, "Nachricht ist bereits zugeordnet. Bitte neu laden."
            )
        contact(db, cid)
        db.execute(
            "UPDATE messages SET contact_id=?,matched=1 WHERE id=? AND matched=0",
            (cid, message_id),
        )
        inherit_addresses(db)
    return redirect("/review")


@app.post("/messages/{message_id}/remove")
async def remove_message(request: Request, message_id: int):
    data = await form(request)
    if field(data, "confirm") != "remove":
        raise HTTPException(400, "Bitte das Entfernen bestätigen.")
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = checked_message(db, message_id, data)
        if row["message_id"]:
            db.execute(
                "INSERT OR IGNORE INTO excluded_messages VALUES (?,?)",
                (storage.message_fingerprint(row["message_id"]), storage.now()),
            )
        # A removed reply reference must never retain a send approval.
        db.execute(
            """UPDATE drafts SET reply_message_id=NULL, version=version+1,
            status=CASE WHEN status='sent' THEN status ELSE 'draft' END,
            review_at=NULL,updated_at=? WHERE reply_message_id=?""",
            (storage.now(), message_id),
        )
        db.execute("DELETE FROM messages WHERE id=?", (message_id,))
    return redirect("/review")


@app.post("/messages/{message_id}/reviewed")
async def reviewed_message(request: Request, message_id: int):
    data = await form(request)
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        checked_message(db, message_id, data)
        db.execute(
            "UPDATE messages SET reviewed_at=? WHERE id=? AND direction='inbound'",
            (storage.now(), message_id),
        )
    return redirect("/review")


@app.get("/opportunities", response_class=HTMLResponse)
def opportunities(request: Request):
    with storage.database() as db:
        rows = db.execute(
            "SELECT opportunities.*, contacts.organization FROM opportunities LEFT JOIN contacts "
            "ON contacts.id=opportunities.contact_id ORDER BY opportunities.id DESC"
        ).fetchall()
        recipients = db.execute(
            "SELECT id,organization FROM contacts ORDER BY organization"
        ).fetchall()
    return render(
        request, "opportunities.html", opportunities=rows, contacts=recipients
    )


@app.post("/opportunities")
async def new_opportunity(request: Request):
    data = await form(request)
    url = field(data, "source_url", 1000)
    if url and urlsplit(url).scheme not in {"https", "http"}:
        raise HTTPException(400, "Bitte eine HTTP(S)-Quelle angeben.")
    cid = integer(data, "contact_id") or None
    with storage.database() as db:
        if cid:
            contact(db, cid)
        db.execute(
            "INSERT INTO opportunities (contact_id,title,source_url,reason,cta,created_at) VALUES (?,?,?,?,?,?)",
            (
                cid,
                field(data, "title", 200, True),
                url,
                field(data, "reason", 3000),
                field(data, "cta", 1000),
                storage.now(),
            ),
        )
    return redirect("/opportunities")


@app.get("/guide", response_class=HTMLResponse)
def guide(request: Request):
    # Read the campaign's own guide database; no NDS process or settings import.
    path = Path(os.getenv("DATABASE_PATH", storage.ROOT / "data" / "thegreatlogout.db"))
    counts = {}
    if path.exists():
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            counts = dict(
                db.execute("SELECT status,count(*) FROM subscribers GROUP BY status")
            )
            counts["sent"] = db.execute(
                "SELECT count(*) FROM email_sends WHERE sent_at IS NOT NULL"
            ).fetchone()[0]
            counts["pending"] = (
                db.execute("""SELECT count(*) FROM email_sends JOIN subscribers ON subscribers.id=subscriber_id
                WHERE sent_at IS NULL AND subscribers.status='active' """).fetchone()[0]
            )
            counts["errors"] = db.execute(
                "SELECT count(*) FROM email_sends WHERE sent_at IS NULL AND error IS NOT NULL"
            ).fetchone()[0]
        finally:
            db.close()
    return render(request, "guide.html", counts=counts)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    return render(
        request,
        "settings.html",
        imap=bool(
            os.getenv("OUTREACH_IMAP_USER") and os.getenv("OUTREACH_IMAP_PASSWORD")
        ),
    )


@app.post("/settings/password")
async def change_password(request: Request):
    data = await form(request)
    new = field(data, "new_password", 1024, True)
    if len(new) < 14:
        raise HTTPException(400, "Bitte mindestens 14 Zeichen verwenden.")
    with storage.database() as db:
        user = db.execute(
            "SELECT * FROM users WHERE id=?", (request.state.user["id"],)
        ).fetchone()
        if not password_hash.verify(
            field(data, "old_password", 1024), user["password_hash"]
        ):
            raise HTTPException(400, "Aktuelles Passwort stimmt nicht.")
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash.hash(new), user["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    return redirect("/login")


@app.get("/outreach", response_class=HTMLResponse)
def outreach_page(request: Request):
    with storage.database() as db:
        result = outreach.report(db)
    return render(
        request,
        "outreach.html",
        report=result,
        ai_ready=outreach.ai_client.configured(),
        automation_active=os.getenv("OUTREACH_AUTOMATION_ENABLED") == "1",
    )


@app.post("/outreach/jobs")
async def queue_outreach(request: Request):
    data = await form(request)
    kind = choice(data, "kind", {"radar", "draft"})
    with storage.database() as db:
        try:
            outreach.enqueue(
                db,
                kind,
                integer(data, "contact_id") or None,
                integer(data, "opportunity_id") or None,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return redirect("/outreach")


@app.post("/outreach/jobs/{job_id}/retry")
async def retry_outreach(request: Request, job_id: int):
    await form(request)
    with storage.database() as db:
        db.execute(
            "UPDATE automation_jobs SET status='queued',result='' WHERE id=? AND status='failed' AND attempts<3",
            (job_id,),
        )
    return redirect("/outreach")


@app.post("/opportunities/{opportunity_id}/dismiss")
async def dismiss_opportunity(request: Request, opportunity_id: int):
    await form(request)
    with storage.database() as db:
        db.execute(
            "UPDATE opportunities SET status='dismissed' WHERE id=?", (opportunity_id,)
        )
    return redirect("/opportunities")


@app.post("/settings/backup-key")
async def download_backup_key(request: Request):
    await form(request)
    from server.offsite_backup import key_path

    path = key_path()
    if not path.is_file():
        raise HTTPException(404, "Wiederherstellungsschlüssel noch nicht erstellt.")
    return Response(
        path.read_bytes(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="thegreatlogout-recovery.key"'
        },
    )
