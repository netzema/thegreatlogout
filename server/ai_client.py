"""Bounded Responses API access. No prompts, addresses, secrets or responses in logs."""

import json
import os
import urllib.error
import urllib.request

from server import admin_db as storage


class AIError(Exception):
    pass


def model():
    return os.getenv("OUTREACH_AI_MODEL", "gpt-6-astra")


def configured():
    return bool(os.getenv("OPENAI_API_KEY"))


def request(purpose, instructions, data, schema=None, search=False):
    if not configured():
        raise AIError("KI-Zugang fehlt")
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute(
            "SELECT count(*) FROM automation_calls WHERE created_at>=?",
            (storage.now()[:10],),
        ).fetchone()[0]
        if count >= min(50, max(1, int(os.getenv("OUTREACH_AI_DAILY_CALLS", "12")))):
            raise AIError("Tageslimit erreicht")
        call_id = db.execute(
            "INSERT INTO automation_calls(purpose,created_at) VALUES (?,?)",
            (purpose, storage.now()),
        ).lastrowid
    payload = {
        "model": model(),
        "store": False,
        "max_output_tokens": 5000,
        "instructions": instructions,
        "input": json.dumps(data, ensure_ascii=False),
    }
    if schema:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": purpose,
                "strict": True,
                "schema": schema,
            }
        }
    if search:
        payload.update(
            tools=[{"type": "web_search", "search_context_size": "low"}],
            tool_choice="required",
            max_tool_calls=2,
            include=["web_search_call.action.sources"],
        )
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    status, usage = "failed", {}
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise AIError("KI-Antwort zu groß")
        result = json.loads(raw)
        if result.get("status") != "completed":
            raise AIError("KI-Antwort unvollständig")
        usage = result.get("usage", {})
        texts, sources = [], set()
        for item in result.get("output", []):
            if item.get("type") == "web_search_call":
                sources.update(
                    s["url"]
                    for s in item.get("action", {}).get("sources", [])
                    if "url" in s
                )
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content["text"])
                    sources.update(
                        a["url"]
                        for a in content.get("annotations", [])
                        if a.get("type") == "url_citation"
                    )
        if not texts:
            raise AIError("KI lieferte keinen Entwurf")
        output = "\n".join(texts)
        parsed = json.loads(output) if schema else output
        status = "ok"
        return parsed, sources
    except urllib.error.HTTPError as exc:
        raise AIError(f"KI-Anfrage fehlgeschlagen (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        raise AIError("KI-Anfrage fehlgeschlagen oder Antwort ungültig") from None
    finally:
        with storage.database() as db:
            db.execute(
                "UPDATE automation_calls SET status=?,input_tokens=?,output_tokens=? WHERE id=?",
                (
                    status,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    call_id,
                ),
            )
