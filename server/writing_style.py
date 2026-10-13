"""Owner-editable writing guidance and mechanical punctuation rules for AI drafts."""

import re

from server import admin_db as storage

DEFAULT_NOTE = """Schreibe menschlich, direkt und persönlich, ohne Werbesprache oder künstliche Begeisterung.
Für deutsche Mails: Daniel schreibt kurze, klare Sätze und kommt zügig zu seinem Anliegen. Er spricht in der Ich-Form und klingt freundlich, ohne seine Gedanken aufzublähen. Ein passender Dank oder gelegentliches Ausrufezeichen kann natürlich sein, ist aber kein Pflichtbaustein. Erkläre bei einem Erstkontakt ausreichend, halte keinen Vortrag. Stelle eine konkrete Frage in normalen Worten. Erfinde weder Begeisterung noch Betroffenheit, etwa mit Einstiegen wie "lässt mich nicht los". Daniels Hoffnung für The Great Logout: Menschen sollen merken, dass sie diesen Plattformen gemeinsam etwas entgegensetzen können. Drücke das schlicht aus, wenn es zum Anlass passt. Der Bezug zur Person muss belegt sein. Sage offen, weshalb du schreibst. Keine erfundenen Angebote und keine vorgeschobene Bitte um Rat, wenn du eigentlich auf einen Hinweis zur Kampagne hoffst. Erwähne Zweisprachigkeit, Werkzeuge und Ankündigungsdetails nur, wenn sie für genau dieses Gespräch gebraucht werden. Bisherige Kampagnenmails dienen als Gesprächsverlauf, nicht als Stilvorlage.
Verwende einen normalen Bindestrich (-), keine langen Gedankenstriche.
Verwende ausschließlich gerade Apostrophe (') und gerade doppelte Anführungszeichen (").
Nach einer Anrede mit Komma wird das erste Wort kleingeschrieben, auch auf Englisch, sofern es nicht unabhängig von seiner Position großgeschrieben werden muss. Namen, Eigennamen, deutsche Nomen und Substantivierungen, Abkürzungen, das englische "I" und die höfliche Anrede "Sie", "Ihr" und "Ihnen" behalten ihre erforderliche Großschreibung. Beispiel: "Dear Alex,\n\nyou mentioned ...", "Hallo Alex,\n\ndanke für ...", aber "Hallo Alex,\n\nDatenschutz ist ...", "Dear Alex,\n\nI remember ..." und "Hallo Alex,\n\nMaria hat ...". "You", "Thank" oder "Danke" werden nur als gewöhnlicher Satzanfang kleingeschrieben. Die Satzanfänge danach bleiben normal. Wähle einen natürlichen Einstieg, ohne Namen oder Nomen künstlich umzuschreiben.
Verwende keine Semikolons. Aufzählungen sind erlaubt, wenn sie wirklich helfen.
Erkenne die tatsächlich angeschriebene Person aus dem bisherigen Dialog: besonders aus unseren Anreden und den Signaturen eingehender Nachrichten. Berücksichtige die gespeicherte Ansprechperson. Übernimm die bisherige Anrede und das Du oder Sie. Bei widersprüchlichen oder fehlenden Belegen bleibe neutral und erfinde keinen Namen.
Knüpfe konkret an den bisherigen Austausch an und vermeide einen erneuten allgemeinen Erstpitch."""

OWNER_EDIT_LESSONS = """Aus Daniels tatsächlich überarbeiteten und versendeten Mails:
Bei einer Bitte um öffentliche Unterstützung darf Daniel persönlich sagen, dass er sich über eine konkrete Erwähnung oder Weitergabe freuen würde, wenn die Person die Idee unterstützt. Eine solche freundliche Bedingung gehört zu Daniels Stimme. Mache daraus weder einen Prüfauftrag noch eine Reihe von Einschränkungen. Wähle eine Bitte, die zur Rolle und zum tatsächlichen Anliegen passt; erzwinge keine einheitliche Schlussformel.
Seine eigene Verantwortung für die Kampagne und sein Wunsch, Plattformen entschlossen zu verlassen und Kontakte unabhängig von ihnen zu erhalten, dürfen klar erkennbar sein. Den Kampagnenlink als weiterführende Information natürlich einbetten: auf Deutsch https://thegreatlogout.org/de/, auf Englisch https://thegreatlogout.org/. Einen im Gespräch bereits vorhandenen Link nicht mechanisch wiederholen.
Deutsche Grußformeln erhalten nach Daniels persönlicher Vorliebe ein abschließendes Komma. Übernimm keine Tipp- oder Grammatikfehler aus bisherigen Mails.
Die tatsächlich bearbeitete englische Mail behielt ihre Stimme und konkrete Frage; ergänzt wurde nur ein Informationssatz mit Kampagnenlink. Schreibe auch künftig idiomatisches Englisch, persönlich und knapp. Sachlich passende fachliche Fragen dürfen bleiben. Übertrage die persönliche Bitte um Unterstützung sinngemäß, wenn sie zum Zweck der Nachricht passt; keine wörtliche Übersetzung deutscher Wendungen, keine erfundene Nähe und keine ungefragten Arbeitsangebote."""

DEFAULT_NOTE += "\n\n" + OWNER_EDIT_LESSONS


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
        # Only known grammatical openings, never blindly lowercase a character.
        # Unknown words may be names, nouns or acronyms; leave them to the model.
        openings = {
            "danke",
            "vielen",
            "ich",
            "wir",
            "du",
            "ihr",
            "euer",
            "eure",
            "dein",
            "deine",
            "unser",
            "unsere",
            "mit",
            "nach",
            "beim",
            "zum",
            "zur",
            "auf",
            "in",
            "für",
            "über",
            "an",
            "aus",
            "wie",
            "weil",
            "wenn",
            "da",
            "das",
            "die",
            "der",
            "es",
            "dieser",
            "diese",
            "dieses",
            "you",
            "your",
            "thank",
            "thanks",
            "we",
            "our",
            "it",
            "this",
            "that",
            "the",
            "following",
            "after",
            "as",
            "with",
        }

        def opening(match):
            word = match[2]
            if word in {"Ihr", "Ihre", "Ihren", "Ihrem", "Ihrer", "Ihres"}:
                return match[0]
            return match[1] + (
                word.lower()
                if word.lower() in openings and not word.isupper()
                else word
            )

        text = re.sub(
            r"\A(\s*(?:Hallo|Hi|Hello|Hey|Dear|Liebe\w*|Guten\w*|Sehr geehrte\w*)[^\n]{0,100},\s+)([^\W\d_]+)",
            opening,
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    return text
