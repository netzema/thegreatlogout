from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from server.admin_db import ROOT, database, now

router = APIRouter()
ORIGINS = {"https://thegreatlogout.org", "https://www.thegreatlogout.org"}
KEY_PATH = ROOT / "data" / "analytics.key"


class AnalyticsEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    visitor_id: UUID
    session_id: UUID
    event_type: Literal[
        "page_view",
        "link_click",
        "engagement",
        "form_submit_success",
        "guide_signup_success",
        "post_download",
    ]
    path: str = Field(min_length=1, max_length=512)
    referrer_host: str | None = Field(default=None, max_length=255)
    source: Literal["direct", "internal", "organic", "referral", "campaign"] = "direct"
    campaign: str | None = Field(default=None, max_length=100)
    campaign_source: str | None = Field(default=None, max_length=100)
    campaign_medium: str | None = Field(default=None, max_length=100)
    campaign_content: str | None = Field(default=None, max_length=100)
    campaign_term: str | None = Field(default=None, max_length=100)
    device_type: Literal["desktop", "tablet", "mobile"]
    target: str | None = Field(default=None, max_length=512)
    value: int | None = Field(default=None, ge=1, le=3600)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or "?" in value
            or "#" in value
            or "@" in unquote(value)
            or has_control_chars(value)
        ):
            raise ValueError("Invalid analytics path")
        return value

    @field_validator("referrer_host")
    @classmethod
    def validate_referrer_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9.-]{1,255}", cleaned):
            raise ValueError("Invalid referrer host")
        return cleaned

    @field_validator(
        "campaign",
        "campaign_source",
        "campaign_medium",
        "campaign_content",
        "campaign_term",
        "target",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or has_control_chars(cleaned):
            return None
        if "?" in cleaned or "@" in unquote(cleaned) or "mailto:" in cleaned.lower():
            raise ValueError("Analytics text may not include a query string")
        return cleaned

    @model_validator(mode="after")
    def validate_event_details(self) -> AnalyticsEventPayload:
        if self.event_type == "engagement" and self.value is None:
            raise ValueError("Engagement events require a value")
        if self.event_type != "engagement" and self.value is not None:
            raise ValueError("Only engagement events may include a value")
        if self.event_type in {"link_click", "post_download"} and not self.target:
            raise ValueError("This event type requires a target")
        if self.event_type in {"page_view", "engagement"} and self.target is not None:
            raise ValueError("This event type may not include a target")
        return self


def has_control_chars(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def identifier(value):
    # A campaign-owned key, not an imported NDS application/session secret.
    key = KEY_PATH.read_bytes()
    return hmac.new(key, str(value).encode(), hashlib.sha256).hexdigest()


@router.post("/api/analytics/events", status_code=202)
def collect(request: Request, payload: AnalyticsEventPayload):
    origin = request.headers.get("origin", "").rstrip("/")
    if (
        origin not in ORIGINS
        or request.cookies.get("tgl_analytics_consent") != "granted"
    ):
        raise HTTPException(403, "Consent and campaign origin required")
    fields = payload.model_dump(exclude={"visitor_id", "session_id"})
    fields["event_id"] = str(fields["event_id"])
    fields.update(
        occurred_at=now(),
        site=urlsplit(origin).hostname,
        visitor_key=identifier(payload.visitor_id),
        session_key=identifier(payload.session_id),
    )
    with database() as db:
        db.execute(
            "INSERT OR IGNORE INTO analytics_events ("
            + ",".join(fields)
            + ") VALUES ("
            + ",".join("?" for _ in fields)
            + ")",
            list(fields.values()),
        )
    return {"ok": True}


def prune():
    cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    with database() as db:
        db.execute("DELETE FROM analytics_events WHERE occurred_at < ?", (cutoff,))
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))


def report(days=30):
    days = days if days in (7, 30, 90) else 30
    zone = ZoneInfo("Europe/Vienna")
    today = datetime.now(zone).date()
    first = today - timedelta(days=days - 1)
    cutoff = (
        datetime.combine(first, datetime.min.time(), tzinfo=zone)
        .astimezone(UTC)
        .isoformat()
    )
    with database() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM analytics_events WHERE occurred_at >= ? ORDER BY occurred_at",
                (cutoff,),
            )
        ]
    views = [r for r in rows if r["event_type"] == "page_view"]
    sessions = {r["session_key"] for r in views}
    seconds = sum(r["value"] or 0 for r in rows if r["event_type"] == "engagement")
    counts = Counter(r["event_type"] for r in rows)
    daily = Counter(
        datetime.fromisoformat(r["occurred_at"])
        .replace(tzinfo=UTC)
        .astimezone(zone)
        .date()
        .isoformat()
        for r in views
    )
    trend = [(first + timedelta(days=i)).isoformat() for i in range(days)]
    first_views = {}
    for row in views:
        first_views.setdefault(row["session_key"], row)
    return {
        "days": days,
        "views": len(views),
        "visits": len(sessions),
        "visitors": len({r["visitor_key"] for r in views}),
        "seconds": round(seconds / len(sessions)) if sessions else 0,
        "signups": counts["guide_signup_success"],
        "downloads": counts["post_download"],
        "clicks": counts["link_click"],
        "pages": Counter(r["path"] for r in views).most_common(15),
        "sources": Counter(
            r["campaign_source"] or r["referrer_host"] or r["source"]
            for r in first_views.values()
        ).most_common(15),
        "devices": Counter(
            r["device_type"] for r in first_views.values()
        ).most_common(),
        "campaigns": Counter(
            (
                r["campaign"] or "–",
                r["campaign_source"] or "–",
                r["campaign_medium"] or "–",
                r["campaign_content"] or "–",
            )
            for r in first_views.values()
            if r["campaign"]
        ).most_common(15),
        "targets": Counter(
            r["target"] for r in rows if r["event_type"] == "link_click"
        ).most_common(15),
        "trend": [(d, daily[d]) for d in trend],
        "max_views": max(daily.values(), default=1),
    }
