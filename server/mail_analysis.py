"""Local, extractive review hints. No model calls, guessed facts or automatic replies."""

from __future__ import annotations

import json
import re

from server.admin_db import database

ANALYSIS_VERSION = 1


def fresh_text(body):
    lines = []
    for line in body.splitlines():
        if line.lstrip().startswith(">") or re.match(
            r"^\s*(On .+wrote:|Am .+schrieb.+:|From:|Von:|_{5,}|-{5,}Original)",
            line,
            re.IGNORECASE,
        ):
            break
        if line.strip() == "--":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def analyse(body, automated=False):
    text = fresh_text(body)
    normalized = " ".join(text.split())
    # Classification is deliberately a hint for a human, not a status decision.
    questions = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", text)
        if s.strip().endswith("?")
    ][:5]
    kind = "automated" if automated else "question" if questions else "review"
    if not automated and re.search(
        r"\b(unsubscribe|do not contact|stop emailing|nicht mehr kontaktieren|keine weiteren e-mails)\b",
        normalized,
        re.IGNORECASE,
    ):
        kind = "contact_objection"
    summary = normalized[:450] + ("…" if len(normalized) > 450 else "")
    return kind, summary, questions


def refresh_analysis():
    changed = 0
    with database() as db:
        rows = db.execute(
            "SELECT * FROM messages WHERE analysis_version<?", (ANALYSIS_VERSION,)
        ).fetchall()
        for row in rows:
            kind, summary, questions = analyse(row["body"], bool(row["automated"]))
            db.execute(
                "UPDATE messages SET analysis_kind=?,analysis_summary=?,analysis_questions=?,analysis_version=? WHERE id=?",
                (
                    kind,
                    summary,
                    json.dumps(questions, ensure_ascii=False),
                    ANALYSIS_VERSION,
                    row["id"],
                ),
            )
            # Hints never change permission or send/approve a draft.
            changed += 1
    return changed
