"""Independent storage for the campaign admin; never imports the NDS backend."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("ADMIN_DATABASE_PATH", ROOT / "data" / "admin.db"))


def now():
    return datetime.now(UTC).isoformat()


def message_fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def database(path=None):
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(target, timeout=20)
    target.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def ensure_schema(path=None):
    with database(path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS writing_preferences (
            id INTEGER PRIMARY KEY CHECK(id=1), note TEXT NOT NULL,
            version INTEGER NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY, seed_key TEXT UNIQUE,
            organization TEXT NOT NULL, person TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'ngo',
            status TEXT NOT NULL DEFAULT 'researched', permission TEXT NOT NULL DEFAULT 'unknown',
            priority INTEGER NOT NULL DEFAULT 2, notes TEXT NOT NULL DEFAULT '',
            next_step TEXT NOT NULL DEFAULT '', next_date TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS contact_email ON contacts(lower(email)) WHERE email != '';
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id),
            title TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '', cta TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id),
            opportunity_id INTEGER REFERENCES opportunities(id), subject TEXT NOT NULL,
            body TEXT NOT NULL, framing TEXT NOT NULL DEFAULT '', campaign TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
            review_note TEXT NOT NULL DEFAULT '', review_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id),
            draft_id INTEGER UNIQUE REFERENCES drafts(id), direction TEXT NOT NULL,
            message_id TEXT UNIQUE, in_reply_to TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL, body TEXT NOT NULL, occurred_at TEXT NOT NULL,
            matched INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL DEFAULT 'manual');
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, draft_id INTEGER REFERENCES drafts(id),
            user_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_cursors (
            folder TEXT PRIMARY KEY, uidvalidity TEXT NOT NULL, last_uid INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_seen (
            folder TEXT NOT NULL, uidvalidity TEXT NOT NULL, uid INTEGER NOT NULL,
            PRIMARY KEY(folder,uidvalidity,uid));
        CREATE TABLE IF NOT EXISTS job_runs (
            name TEXT PRIMARY KEY, finished_at TEXT NOT NULL,
            status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, occurred_at TEXT NOT NULL,
            site TEXT NOT NULL, event_type TEXT NOT NULL, visitor_key TEXT NOT NULL,
            session_key TEXT NOT NULL, path TEXT NOT NULL, referrer_host TEXT,
            source TEXT NOT NULL, campaign TEXT, campaign_source TEXT,
            campaign_medium TEXT, campaign_content TEXT, campaign_term TEXT,
            device_type TEXT NOT NULL, target TEXT, value INTEGER);
        CREATE INDEX IF NOT EXISTS event_time ON analytics_events(occurred_at);
        CREATE INDEX IF NOT EXISTS message_contact ON messages(contact_id,occurred_at);
        CREATE INDEX IF NOT EXISTS contact_followup ON contacts(next_date);
        """)

        # Additive migrations also support databases created by an earlier pilot.
        columns = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
        for name, definition in [
            ("reviewed_at", "TEXT"),
            ("automated", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if name not in columns:
                db.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")

        draft_columns = {r[1] for r in db.execute("PRAGMA table_info(drafts)")}
        if "reply_message_id" not in draft_columns:
            db.execute(
                "ALTER TABLE drafts ADD COLUMN reply_message_id INTEGER REFERENCES messages(id)"
            )

        for name, definition in [
            ("sender_address", "TEXT NOT NULL DEFAULT ''"),
            ("peer_addresses", "TEXT NOT NULL DEFAULT '[]'"),
            ("references_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("analysis_summary", "TEXT NOT NULL DEFAULT ''"),
            ("analysis_kind", "TEXT NOT NULL DEFAULT 'unclassified'"),
            ("analysis_questions", "TEXT NOT NULL DEFAULT '[]'"),
            ("analysis_version", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if name not in columns:
                db.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS contact_addresses (
            address TEXT PRIMARY KEY COLLATE NOCASE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            source TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS organization_domains (
            domain TEXT PRIMARY KEY COLLATE NOCASE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_sync_stats (
            folder TEXT PRIMARY KEY, checked INTEGER NOT NULL DEFAULT 0,
            permitted INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,
            remaining INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS excluded_messages (
            fingerprint TEXT PRIMARY KEY, created_at TEXT NOT NULL);
        """)

        for table, additions in {
            "contacts": [
                ("email_source", "TEXT NOT NULL DEFAULT ''"),
                ("discovery_key", "TEXT"),
                ("discovery_source", "TEXT NOT NULL DEFAULT ''"),
                ("website", "TEXT NOT NULL DEFAULT ''"),
                ("contact_url", "TEXT NOT NULL DEFAULT ''"),
            ],
            "drafts": [
                ("generation_key", "TEXT"),
                ("generation_model", "TEXT NOT NULL DEFAULT ''"),
                ("rationale", "TEXT NOT NULL DEFAULT ''"),
                ("deferred_until", "TEXT NOT NULL DEFAULT ''"),
                ("approved_recipient", "TEXT NOT NULL DEFAULT ''"),
                ("original_body", "TEXT NOT NULL DEFAULT ''"),
            ],
            "opportunities": [
                ("preparation_state", "TEXT NOT NULL DEFAULT ''"),
                ("preparation_note", "TEXT NOT NULL DEFAULT ''"),
                ("preparation_draft_id", "INTEGER"),
                ("source_key", "TEXT"),
                ("published_at", "TEXT NOT NULL DEFAULT ''"),
                ("score", "INTEGER NOT NULL DEFAULT 0"),
                ("score_reason", "TEXT NOT NULL DEFAULT ''"),
                ("framing", "TEXT NOT NULL DEFAULT ''"),
                ("kind", "TEXT NOT NULL DEFAULT ''"),
                ("event_at", "TEXT NOT NULL DEFAULT ''"),
                ("discovered_new", "INTEGER NOT NULL DEFAULT 0"),
            ],
        }.items():
            existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for column, definition in additions:
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        db.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS draft_generation ON drafts(generation_key);
        CREATE UNIQUE INDEX IF NOT EXISTS opportunity_source ON opportunities(source_key);
        CREATE UNIQUE INDEX IF NOT EXISTS contact_discovery ON contacts(discovery_key);
        CREATE TABLE IF NOT EXISTS automation_jobs (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL, contact_id INTEGER REFERENCES contacts(id),
            opportunity_id INTEGER REFERENCES opportunities(id), dedup_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL, finished_at TEXT,
            result TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS automation_calls (
            id INTEGER PRIMARY KEY, purpose TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'started', input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS contact_address_issues (
            contact_id INTEGER PRIMARY KEY REFERENCES contacts(id), reason TEXT NOT NULL);
        """)
