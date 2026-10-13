"""Conservative, explainable qualification. A score never authorizes contact."""

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from server import admin_db as storage
from server import ai_client, writing_style

RULES = """Bewerte streng, ob eine persönliche Anfrage zu The Great Logout für diesen Kontakt sinnvoll ist.
Wir haben Zeit. Kein Mengenziel, keine Fülltreffer und kein künstlicher Zeitdruck.
fit (0-3): 3 = direkter Bezug zu süchtig machenden Social-Media-Plattformen, Plattformmacht,
bewusstem öffentlichem Ausstieg oder einer konkreten relevanten Initiative. 2 = angrenzend,
1 = nur allgemeine Digitalisierung, KI, Gesundheit, Kultur oder gesellschaftliche Kritik, 0 = kein Bezug.
contact_fit (0-3): 3 = belegter verantwortlicher Akteur/Autor und klarer Empfängerbezug,
2 = belegte passende Zuständigkeit, 1 = nur ein allgemeines Organisationspostfach ohne klare Zuständigkeit,
0 = kein belastbarer Empfängerbezug. Bekanntheit und Reichweite geben keine Zusatzpunkte.
opening_fit (0-3): 3 = konkreter belegter Anknüpfungspunkt mit plausibler Frage/Beitrag und Nutzen für
beide Seiten, 2 = natürlicher, spezifischer Gesprächseinstieg, 1 = nur Themenähnlichkeit oder allgemeine
Bitte um Feedback, 0 = konstruierter Vorwand. Eine Veranstaltung oder Publikation allein genügt nicht.
Eine Einladung zu einem bereits abgeschlossenen Call, ein ungefragter Werbepitch, Instrumentalisierung
persönlicher Belastungen oder künstlich konstruierte Zusammenarbeit sind kein tragfähiger Einstieg.
reason nennt den stärksten Bezug UND die wichtigste Einschränkung kurz auf Deutsch.
startpoint ist eine konkrete natürliche Einstiegsfrage oder ein Beitrag auf Deutsch, sonst leer.
source_quote ist ein kurzer wörtlicher Beleg aus dem bereitgestellten Quellentext, sonst leer.
Keine Fakten aus früheren KI-Begründungen als bewiesen übernehmen. Fehlende Belege senken die Bewertung.
"""


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fit: int = Field(ge=0, le=3)
    contact_fit: int = Field(ge=0, le=3)
    opening_fit: int = Field(ge=0, le=3)
    reason: str = Field(min_length=1, max_length=1500)
    startpoint: str = Field(max_length=700)
    source_quote: str = Field(max_length=400)


def grade(assessment, evidence):
    a = assessment
    score = round((45 * a.fit + 35 * a.opening_fit + 20 * a.contact_fit) / 3)
    quoted = " ".join(a.source_quote.casefold().split())
    verified = len(quoted) >= 20 and quoted in " ".join(evidence.casefold().split())
    if (
        a.fit == 3
        and a.contact_fit >= 2
        and a.opening_fit >= 2
        and a.startpoint.strip()
        and verified
    ):
        tier = "good"
    elif a.fit >= 2 and a.contact_fit >= 1:
        tier = "watch"
    else:
        tier = "poor"
    if not verified:
        score = min(score, 59)
        tier = "watch" if tier == "good" else tier
    reason = writing_style.normalize(a.reason)
    if not verified:
        reason += " Der konkrete Quellenbeleg konnte nicht bestätigt werden."
    return tier, score, reason


def allowed(row):
    # An explicitly entered manual occasion is reviewable until assessed.
    return row["quality_tier"] == "good" or (
        row["quality_tier"] == "unassessed" and not row["source_key"]
    )


def require_draft(db, draft):
    from server.preparation import editorial_summary

    if editorial_summary(draft)["unresolved"]:
        raise ValueError(
            "Die Textprüfung hat offene Punkte. Bitte den Entwurf zuerst überarbeiten."
        )
    if draft["opportunity_id"]:
        row = db.execute(
            "SELECT * FROM opportunities WHERE id=?", (draft["opportunity_id"],)
        ).fetchone()
        if row and not allowed(row):
            raise ValueError(
                "Kein ausreichend belegter Gesprächseinstieg. Dieser Anlass bleibt zurückgestellt."
            )


def save(db, oid, assessment, evidence):
    from server.outreach_delivery import assert_editable

    for d in db.execute(
        "SELECT id FROM drafts WHERE opportunity_id=? AND status!='sent'", (oid,)
    ).fetchall():
        assert_editable(db, d["id"])
    tier, score, reason = grade(assessment, evidence)
    db.execute(
        "UPDATE opportunities SET quality_tier=?,quality_json=?,quality_checked_at=?,score=?,score_reason=? WHERE id=?",
        (tier, assessment.model_dump_json(), storage.now(), score, reason, oid),
    )
    if tier != "good":
        db.execute(
            "UPDATE drafts SET status='draft',approved_recipient='',review_at=NULL,version=version+1,updated_at=? WHERE opportunity_id=? AND status='approved'",
            (storage.now(), oid),
        )
        db.execute(
            "UPDATE automation_jobs SET status='done',result='Mangels Passung zurückgestellt',finished_at=? WHERE opportunity_id=? AND status IN ('queued','waiting_budget')",
            (storage.now(), oid),
        )
    return tier


def assess(oid):
    """Re-read a public source, without passing correspondence or addresses to AI."""
    from server.contact_research import fetch, Page
    from server.outreach import BOUNDARY, CAMPAIGN, digest, today

    with storage.database() as db:
        row = db.execute(
            "SELECT o.*,c.organization FROM opportunities o JOIN contacts c ON c.id=o.contact_id WHERE o.id=?",
            (oid,),
        ).fetchone()
        if not row:
            raise ValueError("Anlass fehlt")
        data = {
            key: row[key]
            for key in (
                "title",
                "source_url",
                "organization",
                "published_at",
                "event_at",
                "kind",
            )
        }
        key = digest(data)
    try:
        url, raw = fetch(row["source_url"])
        evidence = re.sub(
            r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}", "[Adresse]", " ".join(Page(raw).text)
        )[:18000]
    except (ValueError, OSError, LookupError):
        evidence = ""
    if evidence.strip():
        raw, _ = ai_client.request(
            "opportunity_quality",
            BOUNDARY + CAMPAIGN + RULES,
            {"today": str(today()), "opportunity": data, "source_text": evidence},
            schema=Assessment.model_json_schema(),
        )
        result = Assessment.model_validate(raw)
    else:
        result = Assessment(
            fit=2,
            contact_fit=1,
            opening_fit=0,
            reason="Originalquelle aktuell nicht lesbar. Ohne bestätigten Startpunkt vorerst nicht anschreiben.",
            startpoint="",
            source_quote="",
        )
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT o.*,c.organization FROM opportunities o JOIN contacts c ON c.id=o.contact_id WHERE o.id=?",
            (oid,),
        ).fetchone()
        if not current or digest({k: current[k] for k in data}) != key:
            raise ValueError("Anlass wurde während der Bewertung geändert")
        return save(db, oid, result, evidence)


def summary(row):
    try:
        detail = json.loads(row["quality_json"])
    except (TypeError, ValueError):
        detail = {}
    return {
        "tier": row["quality_tier"],
        "score": row["score"],
        "reason": row["score_reason"],
        "startpoint": detail.get("startpoint", "") if isinstance(detail, dict) else "",
        "allowed": allowed(row),
    }


def main():
    storage.ensure_schema()
    with storage.database() as db:
        ids = [
            r[0]
            for r in db.execute(
                "SELECT id FROM opportunities WHERE status='open' AND quality_checked_at='' ORDER BY id"
            )
        ]
    counts = {}
    for oid in ids:
        try:
            tier = assess(oid)
        except ai_client.AIBudgetExceeded:
            print("Bewertung pausiert: Tagesbudget erreicht.")
            break
        counts[tier] = counts.get(tier, 0) + 1
        print(
            json.dumps({"evaluated": sum(counts.values()), "tiers": counts}), flush=True
        )


if __name__ == "__main__":
    main()
