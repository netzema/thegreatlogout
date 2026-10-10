"""Owner-editable writing guidance and mechanical punctuation rules for AI drafts."""

import re

from server import admin_db as storage

DEFAULT_NOTE = """Schreibe menschlich, direkt und persönlich, ohne Werbesprache oder künstliche Begeisterung.
Verwende einen normalen Bindestrich (-), keine langen Gedankenstriche.
Verwende ausschließlich gerade Apostrophe (') und gerade doppelte Anführungszeichen (").
Nach einer Anrede mit Komma beginnt der folgende Absatz mit einem kleingeschriebenen Wort, auch auf Englisch. Beispiel: "Dear Alex,\n\nyou mentioned ..." und "Hallo Alex,\n\ndanke für ...". Beginne dort nicht mit "You", "Thank" oder "Danke". Wähle bei Bedarf einen anderen Satzanfang, damit Eigennamen, das englische "I" und die höfliche Anrede "Sie" nicht fälschlich kleingeschrieben werden. Diese Regel gilt nur unmittelbar nach der Anrede, nicht für spätere Satzanfänge.
Verwende keine Semikolons. Aufzählungen sind erlaubt, wenn sie wirklich helfen.
Erkenne die tatsächlich angeschriebene Person aus dem bisherigen Dialog: besonders aus unseren Anreden und den Signaturen eingehender Nachrichten. Berücksichtige die gespeicherte Ansprechperson. Übernimm die bisherige Anrede und das Du oder Sie. Bei widersprüchlichen oder fehlenden Belegen bleibe neutral und erfinde keinen Namen.
Knüpfe konkret an den bisherigen Austausch an und vermeide einen erneuten allgemeinen Erstpitch."""


def read(db):
    row = db.execute(
        "SELECT note,version FROM writing_preferences WHERE id=1"
    ).fetchone()
    return (row["note"], row["version"]) if row else (DEFAULT_NOTE, 0)


def save(db, note, version):
    db.execute("BEGIN IMMEDIATE")
    if read(db)[1] != version:
        raise ValueError("Die Schreibnotiz wurde inzwischen geändert. Bitte neu laden.")
    db.execute(
        "INSERT INTO writing_preferences(id,note,version,updated_at) VALUES (1,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET note=excluded.note,version=excluded.version,updated_at=excluded.updated_at",
        (note, version + 1, storage.now()),
    )


def normalize(text, *, greeting=False):
    text = text.translate(
        str.maketrans(
            {
                "—": "-",
                "–": "-",
                "‘": "'",
                "’": "'",
                "‚": "'",
                "‛": "'",
                "“": '"',
                "”": '"',
                "„": '"',
                "‟": '"',
                "«": '"',
                "»": '"',
                "‹": "'",
                "›": "'",
                ";": ",",
            }
        )
    )
    if greeting:
        text = re.sub(
            r"\A(\s*(?:Hallo|Hi|Hello|Hey|Dear|Liebe\w*|Guten\w*|Sehr geehrte\w*)[^\n]{0,100},\s+)([a-zäöü])",
            lambda match: match[1] + match[2].lower(),
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    return text
