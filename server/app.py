from __future__ import annotations

import html
import os
import re
import secrets
import sqlite3
import textwrap
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.email_content import load_email_sequences
from server.mailer import build_postmark_payload, send_postmark_message

ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT / "data" / "thegreatlogout.db"))
ALLOWED_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.getenv(
        "ALLOWED_ORIGINS", "https://thegreatlogout.org,https://www.thegreatlogout.org"
    ).split(",")
    if item.strip()
}
POSTMARK_SERVER_TOKEN = os.getenv("POSTMARK_SERVER_TOKEN", "")
POSTMARK_MESSAGE_STREAM = os.getenv("POSTMARK_MESSAGE_STREAM", "outbound")
FROM_EMAIL = os.getenv("FROM_EMAIL", "hello@thegreatlogout.org")
FROM_NAME = os.getenv("FROM_NAME", "The Great Logout")
REPLY_TO = os.getenv("REPLY_TO", "support@thegreatlogout.org")
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://thegreatlogout.org").rstrip("/")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.thegreatlogout.org").rstrip("/")
MIN_FILL_SECONDS = max(float(os.getenv("MIN_FILL_SECONDS", "2")), 0.0)
MAX_SEND_ATTEMPTS = max(int(os.getenv("MAX_SEND_ATTEMPTS", "8")), 1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    yield


app = FastAPI(
    title="The Great Logout API", docs_url=None, redoc_url=None, lifespan=lifespan
)


class SignupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    firstName: str = Field(default="", max_length=80)
    logoutDate: str = Field(default="", max_length=10)
    guideLength: int = Field(default=7)
    language: str = Field(default="en", max_length=8)
    consent: bool
    website: str = Field(default="", max_length=200)
    startedAt: int | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", cleaned):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("firstName")
    @classmethod
    def clean_first_name(cls, value: str) -> str:
        return clean_text(value, 80)

    @field_validator("logoutDate")
    @classmethod
    def validate_logout_date(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            raise ValueError("Invalid logout date")
        return cleaned

    @field_validator("guideLength")
    @classmethod
    def validate_guide_length(cls, value: int) -> int:
        return value if value in {1, 3, 7} else 7

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return "de" if value.lower().startswith("de") else "en"


def database(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def ensure_schema(path: Path | None = None) -> None:
    with database(path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS subscribers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL,
              first_name TEXT,
              guide_length INTEGER NOT NULL DEFAULT 7,
              planned_logout_date TEXT,
              language TEXT NOT NULL DEFAULT 'en',
              unsubscribe_token TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'active',
              consented_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              unsubscribed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ix_subscribers_active_email
              ON subscribers(email) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS email_sends (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              subscriber_id INTEGER NOT NULL,
              sequence_key TEXT NOT NULL,
              send_after TEXT NOT NULL,
              sent_at TEXT,
              postmark_message_id TEXT,
              error TEXT,
              attempts INTEGER NOT NULL DEFAULT 0,
              last_attempt_at TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(subscriber_id, sequence_key),
              FOREIGN KEY (subscriber_id) REFERENCES subscribers(id)
            );
            CREATE INDEX IF NOT EXISTS ix_email_sends_due
              ON email_sends(send_after, sent_at);
            """
        )


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    with database() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.post("/api/guide/subscribe", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
@app.post("/subscribe", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
def subscribe(request: Request, payload: SignupPayload) -> dict[str, bool]:
    require_allowed_origin(request)
    if payload.website:
        return {"ok": True}
    if payload.startedAt is None or time.time() - payload.startedAt / 1000 < MIN_FILL_SECONDS:
        raise HTTPException(status_code=400, detail="Please take a moment before submitting.")
    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consent is required.")

    now = utc_now()
    with database() as connection:
        existing = connection.execute(
            "SELECT id FROM subscribers WHERE email = ? AND status = 'active' LIMIT 1",
            (payload.email,),
        ).fetchone()
        if existing:
            return {"ok": True}
        token = secrets.token_urlsafe(32)
        cursor = connection.execute(
            """
            INSERT INTO subscribers (
              email, first_name, guide_length, planned_logout_date, language,
              unsubscribe_token, status, consented_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                payload.email,
                payload.firstName or None,
                payload.guideLength,
                payload.logoutDate or None,
                payload.language,
                token,
                now,
                now,
            ),
        )
        subscriber_id = int(cursor.lastrowid)
        schedule_emails(connection, subscriber_id, payload.guideLength, payload.language)
        connection.commit()
    send_due_emails(limit=1, subscriber_id=subscriber_id)
    return {"ok": True}


@app.get("/api/guide/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
@app.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: Annotated[str, Query(min_length=20, max_length=200)]) -> HTMLResponse:
    with database() as connection:
        subscriber = connection.execute(
            "SELECT language FROM subscribers WHERE unsubscribe_token = ? LIMIT 1", (token,)
        ).fetchone()
        if subscriber:
            connection.execute(
                "UPDATE subscribers SET status = 'unsubscribed', unsubscribed_at = ? "
                "WHERE unsubscribe_token = ?",
                (utc_now(), token),
            )
            connection.commit()
    language = subscriber["language"] if subscriber else "en"
    if language == "de":
        title = "Du bist abgemeldet."
        copy = "Du erhältst keine weiteren E-Mails aus dem Logout-Guide."
        back = "Zur Website"
    else:
        title = "You are unsubscribed."
        copy = "You will not receive more logout guide emails at this address."
        back = "Return to the website"
    return HTMLResponse(
        f"""<!doctype html><html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | The Great Logout</title></head><body style="margin:0;background:#070807;color:#f4f4ef;font-family:Arial,sans-serif;line-height:1.5;"><main style="max-width:620px;margin:0 auto;padding:56px 20px;"><p style="color:#B6FF3B;font-family:monospace;text-transform:uppercase;">The Great Logout</p><h1>{title}</h1><p>{copy}</p><p><a href="{PUBLIC_SITE_URL}" style="color:#B6FF3B;">{back}</a></p></main></body></html>"""
    )


@app.get("/api/guide/post.svg", include_in_schema=False)
@app.get("/post.svg", include_in_schema=False)
def post_svg(
    text: Annotated[str, Query(max_length=280)] = "The exit is the message.",
    format: Annotated[str, Query(max_length=16)] = "square",
    color: Annotated[str, Query(max_length=16)] = "white",
    lang: Annotated[str, Query(max_length=8)] = "en",
) -> Response:
    vertical = format == "vertical"
    height = 1920 if vertical else 1080
    fill = "#B6FF3B" if color == "green" else "#f4f4ef"
    lines = wrap_svg_text(clean_text(text, 280), 18)
    font_size = max(54, min(108, int(1080 / max(9, max(map(len, lines), default=9) * 0.58))))
    line_height = round(font_size * 1.14)
    start_y = round((height - 200 - len(lines) * line_height) / 2 + font_size)
    tspans = "".join(
        f'<tspan x="50%" y="{start_y + index * line_height}">{html.escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    tagline = "Ein gemeinsamer Social-Media-Ausstieg" if lang.startswith("de") else "A collective social media exit"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="{height}" viewBox="0 0 1080 {height}"><rect width="100%" height="100%" fill="#070807"/><defs><pattern id="grid" width="120" height="120" patternUnits="userSpaceOnUse"><path d="M 120 0 L 0 0 0 120" fill="none" stroke="#202320" stroke-width="2"/></pattern></defs><rect width="100%" height="100%" fill="url(#grid)"/><text text-anchor="middle" font-family="Arial, sans-serif" font-size="{font_size}" font-weight="800" fill="{fill}">{tspans}</text><text x="108" y="{height - 156}" font-family="Arial, sans-serif" font-size="28" font-weight="800" fill="#f4f4ef">The Great Logout</text><text x="108" y="{height - 124}" font-family="Arial, sans-serif" font-size="23" fill="#a4aaa1">{html.escape(tagline)}</text><text x="972" y="{height - 124}" text-anchor="end" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#B6FF3B">thegreatlogout.org</text></svg>"""
    filename = "great-logout-vertical.svg" if vertical else "great-logout-square.svg"
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def schedule_emails(
    connection: sqlite3.Connection, subscriber_id: int, guide_length: int, language: str
) -> None:
    start = datetime.now(UTC)
    for email in load_email_sequences()[language]:
        key = str(email["key"])
        if key.startswith("day-"):
            day = int(key.removeprefix("day-"))
            if day not in {0} and day <= 7 and day > guide_length:
                continue
        send_after = (start + timedelta(days=int(email["delayDays"]))).isoformat()
        connection.execute(
            "INSERT OR IGNORE INTO email_sends "
            "(subscriber_id, sequence_key, send_after, created_at) VALUES (?, ?, ?, ?)",
            (subscriber_id, key, send_after, utc_now()),
        )


def send_due_emails(limit: int = 50, subscriber_id: int | None = None) -> int:
    ensure_schema()
    retry_before = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    parameters: list[Any] = [utc_now(), MAX_SEND_ATTEMPTS, retry_before]
    subscriber_filter = ""
    if subscriber_id is not None:
        subscriber_filter = " AND subscribers.id = ?"
        parameters.append(subscriber_id)
    parameters.append(limit)
    with database() as connection:
        rows = connection.execute(
            f"""
            SELECT email_sends.id, email_sends.sequence_key, subscribers.email,
                   subscribers.first_name, subscribers.unsubscribe_token,
                   subscribers.language
            FROM email_sends
            JOIN subscribers ON subscribers.id = email_sends.subscriber_id
            WHERE email_sends.sent_at IS NULL
              AND email_sends.send_after <= ?
              AND email_sends.attempts < ?
              AND (email_sends.last_attempt_at IS NULL OR email_sends.last_attempt_at <= ?)
              AND subscribers.status = 'active'
              {subscriber_filter}
            ORDER BY email_sends.send_after, email_sends.id
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        sent = 0
        for row in rows:
            attempt_time = utc_now()
            claimed = connection.execute(
                "UPDATE email_sends SET attempts = attempts + 1, last_attempt_at = ? "
                "WHERE id = ? AND sent_at IS NULL "
                "AND (last_attempt_at IS NULL OR last_attempt_at <= ?)",
                (attempt_time, row["id"], retry_before),
            )
            connection.commit()
            if claimed.rowcount != 1:
                continue
            sequence = load_email_sequences()[row["language"]]
            email = next((item for item in sequence if item["key"] == row["sequence_key"]), None)
            if not email:
                record_send_error(connection, row["id"], "Unknown email sequence key")
                continue
            try:
                result = send_postmark_message(
                    POSTMARK_SERVER_TOKEN,
                    build_postmark_payload(
                        email=email,
                        recipient=row["email"],
                        first_name=row["first_name"] or "",
                        unsubscribe_token=row["unsubscribe_token"],
                        from_name=FROM_NAME,
                        from_email=FROM_EMAIL,
                        reply_to=REPLY_TO,
                        site_url=PUBLIC_SITE_URL,
                        api_base_url=API_BASE_URL,
                        message_stream=POSTMARK_MESSAGE_STREAM,
                    ),
                )
                connection.execute(
                    "UPDATE email_sends SET sent_at = ?, postmark_message_id = ?, "
                    "error = NULL WHERE id = ?",
                    (utc_now(), result.get("MessageID"), row["id"]),
                )
                sent += 1
            # Keep one failed delivery from stopping the rest of the due queue.
            except Exception as error:  # noqa: BLE001
                record_send_error(connection, row["id"], str(error))
            connection.commit()
        return sent


def record_send_error(connection: sqlite3.Connection, send_id: int, message: str) -> None:
    connection.execute(
        "UPDATE email_sends SET error = ? WHERE id = ?",
        (clean_text(message, 500), send_id),
    )


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def clean_text(value: Any, max_length: int) -> str:
    return "".join(character for character in str(value or "").strip() if ord(character) >= 32)[
        :max_length
    ]


def wrap_svg_text(value: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for raw_line in value.splitlines() or [value]:
        wrapped = textwrap.wrap(raw_line, width=max_chars, break_long_words=True) or [""]
        lines.extend(wrapped)
    return lines[:12]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
