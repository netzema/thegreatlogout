"""Broad public research with source-backed, review-only contact discovery."""

import re
import unicodedata
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from server import admin_db as storage
from server import ai_client, writing_style, opportunity_quality as quality

LANES = (
    (
        "events",
        "Events, Konferenzen, neue Kampagnen, Initiativen und aktuelle Geschehnisse",
    ),
    (
        "publications",
        "Neue Studien, Publikationen, journalistische Beiträge, Podcasts und Kulturbeiträge",
    ),
    (
        "debates",
        "Öffentliche Aussagen, Personen des öffentlichen Lebens, Creator, Organisationen und virale Themen",
    ),
)


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DiscoveredContact(EvidenceModel):
    organization: str = Field(min_length=1, max_length=200)
    person: str = Field(max_length=200)
    category: Literal["media", "ngo", "science", "sport", "creator", "other"]
    source_url: str = Field(max_length=1000)
    website: str = Field(max_length=1000)
    contact_url: str = Field(max_length=1000)
    relationship: str = Field(min_length=1, max_length=500)


class DiscoveredOpportunity(EvidenceModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal[
        "event", "news", "publication", "post", "viral", "campaign", "statement"
    ]
    source_url: str = Field(max_length=1000)
    published_at: str = Field(max_length=10)
    event_at: str = Field(max_length=10)
    contact: DiscoveredContact
    reason: str = Field(min_length=1, max_length=1500)
    cta: str = Field(min_length=1, max_length=500)
    framing: str = Field(min_length=1, max_length=100)
    fit: int = Field(ge=0, le=3)
    contact_fit: int = Field(ge=0, le=3)
    opening_fit: int = Field(ge=0, le=3)
    startpoint: str = Field(max_length=700)
    source_quote: str = Field(max_length=400)


class DiscoveryResult(EvidenceModel):
    opportunities: list[DiscoveredOpportunity] = Field(max_length=8)


def name_key(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def site_host(value):
    host = (urlsplit(value).hostname or "").removeprefix("www.")
    # Shared hosting is not evidence that two people/organizations are identical.
    shared = {
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "youtu.be",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "bsky.app",
        "substack.com",
        "medium.com",
        "linktr.ee",
    }
    return (
        ""
        if any(host == domain or host.endswith("." + domain) for domain in shared)
        else host
    )


def timely(item, current_date):
    try:
        age = (current_date - date.fromisoformat(item.published_at)).days
        if item.kind == "event":
            ahead = (date.fromisoformat(item.event_at) - current_date).days
            return 0 <= age <= 180 and 0 <= ahead <= 90
        return not item.event_at and 0 <= age <= 14
    except ValueError:
        return False


def resolve_contact(db, candidate, item, allowed):
    from server.outreach import digest, eligible, public_url

    identity = name_key(candidate.organization)
    if not identity or "@" in candidate.organization or "@" in candidate.person:
        return None, False
    evidence = public_url(candidate.source_url)
    if evidence not in allowed:
        return None, False
    website = public_url(candidate.website) if candidate.website else ""
    # Keep only observed pages, not model-guessed homepages or contact paths.
    website = website if website in allowed else ""
    contact_url = public_url(candidate.contact_url) if candidate.contact_url else ""
    contact_url = contact_url if contact_url in allowed else ""
    host = site_host(website or contact_url)
    identity_key = digest(["discovery", identity])
    known = db.execute("SELECT * FROM contacts").fetchall()
    matches = {
        c["id"]: c
        for c in known
        if name_key(c["organization"]) == identity
        or c["discovery_key"] == identity_key
        or (host and site_host(c["website"]) == host)
    }
    if host:
        # Read established domain identities, never expand mailbox import scope.
        for c in db.execute(
            "SELECT contacts.* FROM contacts JOIN organization_domains ON contacts.id=contact_id "
            "WHERE lower(domain) IN (?,?)",
            (host, "www." + host),
        ):
            matches[c["id"]] = c
    if matches:
        if len(matches) != 1 or not eligible(db, next(iter(matches))):
            return None, False
        return next(iter(matches)), False
    cid = db.execute(
        "INSERT INTO contacts(organization,person,category,status,permission,notes,next_step,"
        "discovery_key,discovery_source,website,contact_url,created_at,updated_at) "
        "VALUES (?,?,?,'researched','unknown',?,?,?,?,?,?,?,?)",
        (
            candidate.organization.strip(),
            candidate.person.strip(),
            candidate.category,
            "Aus öffentlicher Recherche entdeckt. " + candidate.relationship,
            item.cta,
            identity_key,
            evidence,
            website,
            contact_url,
            storage.now(),
            storage.now(),
        ),
    ).lastrowid
    return cid, True


def run():
    from server.outreach import (
        BOUNDARY,
        CAMPAIGN,
        digest,
        public_url,
        today,
    )

    research, sources = [], set()
    for lane, focus in LANES:
        text, cited = ai_client.request(
            "discovery_" + lane,
            BOUNDARY
            + CAMPAIGN
            + quality.RULES
            + " Recherchiere breit und unabhängig von einem bestehenden Kontaktbestand. "
            "Entdecke neue Akteure und konkrete Möglichkeiten, die Kampagne bekannt zu machen. "
            "Suche im deutschsprachigen Raum UND international auf Deutsch und Englisch. "
            "Themen: Plattformmacht, Aufmerksamkeit, algorithmische Feeds, digitale Selbstbestimmung, "
            "Jugend, Bildung, Kultur, Sport, Arbeit und gesellschaftliche Folgen sozialer Medien. "
            "Nutze mehrere Themen und voneinander unabhängige Quellen. Keine Beschränkung auf große Medien. "
            "Fokus dieses Suchlaufs: " + focus + ". "
            "Aktuelle Veröffentlichungen der letzten 14 Tage oder anstehende Events in den nächsten "
            "90 Tagen mit belegtem Termin und einer Ankündigung der letzten 180 Tage. "
            "Notiere Publikationsdatum, ggf. Eventdatum, Originalquelle, handelnde Person/Organisation, "
            "deren belegte Rolle und warum gerade sie ansprechbar wäre. Suche auch die offizielle Website "
            "oder öffentliche Kontaktseite und nenne deren Quelllink. Keine E-Mail-Adressen erraten. "
            "Private Personen und sensible persönliche Lebensumstände sind keine Akquiseziele. "
            "Virale Reichweite nur nennen, wenn sie belegt ist. Keine Gerüchte als Fakten verwenden. "
            "Höchstens vier konkrete Funde je Suchlauf, keine Fülltreffer. Kurz und quellenbezogen berichten.",
            {"today": str(today()), "focus": focus},
            search=True,
        )
        research.append({"focus": focus, "findings": text[:11000]})
        sources.update(cited)
    allowed = {public_url(s) for s in sources} - {""}
    if not allowed:
        return 0
    raw, _ = ai_client.request(
        "discovery_extract",
        BOUNDARY
        + CAMPAIGN
        + quality.RULES
        + " Extrahiere maximal acht unterschiedliche, relevante Anlässe aus den Recherchebelegen. "
        "Priorisiere Vielfalt bei Themen, Quellmedien und Akteuren. Höchstens zwei Funde pro Organisation. "
        "Leite für jeden Anlass einen konkreten öffentlichen Kontakt ab: Veranstalter, Initiative, "
        "Organisation, Autor oder öffentliche Person. Die Beziehung zum Anlass muss belegt sein. "
        "organization ist der stabile Organisationsname, bei unabhängigen öffentlichen Personen deren Name. "
        "person nur bei belegter Ansprechperson, sonst leer. contact.source_url belegt Identität und Rolle. "
        "website und contact_url nur als bereits recherchierte, belegte offizielle Seiten, sonst leer. "
        "Keine erfundenen Adressen oder Kontakt-IDs. Es ist richtig, keine Funde vorzuschlagen. "
        "Nur Quelllinks aus sources. Datum im Format YYYY-MM-DD, kein geschätztes Datum. "
        "event_at nur für anstehende Events, sonst leer. fit bewertet die konkrete Kampagnenpassung von 0 bis 3. "
        "reason und cta kurz, konkret und auf Deutsch. Ein Artikel ist noch keine virale Debatte.",
        {"today": str(today()), "research": research, "sources": sorted(allowed)},
        schema=DiscoveryResult.model_json_schema(),
    )
    result = DiscoveryResult.model_validate(raw)
    created, per_contact = 0, {}
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        for item in result.opportunities:
            source = public_url(item.source_url)
            if source not in allowed or item.fit < 3 or not timely(item, today()):
                continue
            assessment = quality.Assessment.model_validate(
                {k: getattr(item, k) for k in quality.Assessment.model_fields}
            )
            evidence = "\n".join(r["findings"] for r in research)
            tier, score, explanation = quality.grade(assessment, evidence)
            if tier != "good":
                continue
            for field in ("title", "reason", "cta", "framing"):
                setattr(item, field, writing_style.normalize(getattr(item, field)))
            item.contact.relationship = writing_style.normalize(
                item.contact.relationship
            )
            cid, is_new = resolve_contact(db, item.contact, item, allowed)
            if cid is None or per_contact.get(cid, 0) >= 2:
                continue
            key = digest([source, cid])
            if db.execute(
                "SELECT 1 FROM opportunities WHERE source_key=?", (key,)
            ).fetchone():
                continue
            inserted = db.execute(
                "INSERT INTO opportunities(contact_id,title,source_url,reason,cta,created_at,source_key,"
                "published_at,score,score_reason,framing,kind,event_at,discovered_new) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    item.title,
                    source,
                    item.reason,
                    item.cta,
                    storage.now(),
                    key,
                    item.published_at,
                    score,
                    explanation,
                    item.framing,
                    item.kind,
                    item.event_at,
                    int(is_new),
                ),
            )
            from server.preparation import enqueue

            quality.save(db, inserted.lastrowid, assessment, evidence)
            enqueue(db, cid, inserted.lastrowid)
            per_contact[cid] = per_contact.get(cid, 0) + 1
            created += 1
    return created
