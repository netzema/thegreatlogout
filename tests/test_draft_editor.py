"""Synthetic editing tests, without HTTP clients, real contacts, or mail transport."""

import json

import pytest

from server import admin_db, ai_client, draft_editor


CONTEXT = {
    "person": "Alex Beispiel",
    "writing_note": "Direkt, freundlich, ohne künstliche Begeisterung.",
    "history": [{"direction": "inbound", "text": "Bitte bleiben wir beim Du."}],
    "opportunity": {
        "source_quote": "Ein sichtbarer Ausstieg kann anderen Mut machen.",
        "conversation_start": "Wie sprechen wir offen über unseren Ausstieg?",
    },
}
INSTRUCTIONS = "Daniel lädt zu einem sichtbaren Ausstieg aus sozialen Plattformen ein."
ENGLISH_CONTEXT = {
    "person": "Alex Example",
    "writing_note": "Eine warme Bitte um eine passende Erwähnung ist willkommen.",
    "owner_feedback": [{"action": "edited", "note": "Kampagnenlink beibehalten."}],
    "history": [{"direction": "inbound", "text": "Please call me Alex."}],
    "opportunity": {
        "source_quote": "People fear losing touch when they leave a platform.",
        "conversation_start": "Making a public departure easier for others.",
    },
}


@pytest.fixture
def editor_db(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_db, "DB_PATH", tmp_path / "editor.db")


def candidate(body=None, **changes):
    return {
        "should_draft": True,
        "subject": "Über den eigenen Ausstieg sprechen",
        "body": body or "Hallo Alex,\n\nich finde Deinen Gedanken zum sichtbaren Ausstieg interessant. Wie sprichst Du mit anderen darüber?\nDaniel",
        "rationale": "Der belegte Gedanke zum sichtbaren Ausstieg ist ein konkreter Bezug.",
        "framing": "dialogue",
        **changes,
    }


def critique(verdict="ready", **changes):
    return {
        "verdict": verdict,
        "summary": "Die Nachricht knüpft konkret an den belegten Gedanken an.",
        "natural_german": True,
        "personal_voice": True,
        "grounded_connection": True,
        "credible_ask": True,
        "factually_supported": True,
        "issues": [] if verdict == "ready" else [{
            "category": "personal_voice",
            "passage": "interessant",
            "instruction": "Erkläre konkret, was Dich an dem Gedanken interessiert.",
        }],
        **changes,
    }


def scripted(monkeypatch, responses):
    remaining = iter(responses)
    calls = []

    def request(purpose, instructions, data, **kwargs):
        calls.append((purpose, instructions, data, kwargs))
        value = next(remaining)
        if isinstance(value, BaseException):
            raise value
        return value, set()

    monkeypatch.setattr(ai_client, "request", request)
    return calls


def english_candidate(body=None):
    return candidate(
        body or "Dear Alex,\n\nI hope that public departures can encourage others. If the idea speaks to you, I would appreciate a mention in your newsletter: https://thegreatlogout.org/\nDaniel",
        subject="Helping people leave platforms",
    )


def english_critique(verdict="ready", **changes):
    report = critique(verdict, **changes)
    report.pop("natural_german")
    report.setdefault("natural_english", True)
    return report


def test_two_revisions_are_bounded_and_every_step_is_preserved(editor_db, monkeypatch):
    first = candidate()
    second = candidate("Hallo Alex,\n\nich möchte Deinen Gedanken aufgreifen. Wie sprichst Du über den Ausstieg?\nDaniel")
    third = candidate("Hallo Alex,\n\nich möchte, dass mehr Menschen ihren Ausstieg öffentlich erklären. Was hält sie bisher davon ab?\nDaniel")
    calls = scripted(monkeypatch, [first, critique("revise"), second, critique("revise"), third, critique("revise")])
    result = draft_editor.run("bounded", CONTEXT, INSTRUCTIONS, language="de")
    assert result.status == "needs_review"
    assert result.rounds == 2
    assert result.candidate == third
    assert len(calls) == 6
    with admin_db.database() as db:
        steps = db.execute("SELECT kind,content_json FROM draft_editor_steps ORDER BY sequence").fetchall()
        assert [s[0] for s in steps] == ["draft", "review", "revision", "review", "revision", "review"]
        assert json.loads(steps[0][1]) == first
        assert json.loads(steps[2][1]) == second
        assert json.loads(steps[4][1]) == third
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('drafts','messages','outreach_deliveries')").fetchall()
    assert draft_editor.run("bounded", CONTEXT, INSTRUCTIONS, language="de") == result
    assert len(calls) == 6


def test_budget_resume_reuses_candidate_and_critique(editor_db, monkeypatch):
    first, revised = candidate(), candidate("Hallo Alex,\n\nich möchte, dass ein öffentlicher Ausstieg anderen Mut macht. Wie würdest Du damit beginnen?\nDaniel")
    calls = scripted(monkeypatch, [first, critique("revise"), ai_client.AIBudgetExceeded("limit"), revised, critique()])
    with pytest.raises(ai_client.AIBudgetExceeded):
        draft_editor.run("budget", CONTEXT, INSTRUCTIONS, language="de")
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM draft_editor_runs").fetchone()
        assert row["stage"] == "revise"
        assert json.loads(row["candidate_json"]) == first
        assert row["lease_token"] == ""
    result = draft_editor.run("budget", CONTEXT, INSTRUCTIONS, language="de")
    assert result.status == "ready" and result.rounds == 1
    assert result.candidate == revised
    assert [call[0] for call in calls] == [
        "outreach_draft", "outreach_text_review", "outreach_revision",
        "outreach_revision", "outreach_text_review",
    ]


def test_budget_after_initial_draft_does_not_regenerate(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(), ai_client.AIBudgetExceeded("limit"), critique()])
    with pytest.raises(ai_client.AIBudgetExceeded):
        draft_editor.run("initial-budget", CONTEXT, INSTRUCTIONS)
    result = draft_editor.run("initial-budget", CONTEXT, INSTRUCTIONS)
    assert result.status == "ready"
    assert [c[0] for c in calls].count("outreach_draft") == 1


@pytest.mark.parametrize("language", [None, "en"])
def test_english_seed_is_unchanged_without_model_calls(editor_db, monkeypatch, language):
    original = candidate("Dear Alex,\n\nThank you for your work; I’d like to ask about the project.\nDaniel")
    calls = scripted(monkeypatch, [])
    result = draft_editor.run("english-seed", CONTEXT, INSTRUCTIONS, seed=original, language=language)
    assert result.status == "english"
    assert result.candidate == original
    assert result.rounds == 0 and calls == []


def test_new_english_output_gets_no_german_review(editor_db, monkeypatch):
    original = candidate("Dear Alex,\n\nThank you for your work; I’d like to ask about the project.\nDaniel")
    calls = scripted(monkeypatch, [original])
    result = draft_editor.run("english-new", CONTEXT, INSTRUCTIONS)
    assert result.status == "english" and result.candidate == original
    assert len(calls) == 1


@pytest.mark.parametrize("language", [None, "en"])
def test_opted_in_english_is_normalized_before_native_critique(editor_db, monkeypatch, language):
    original = english_candidate("Dear Alex,\n\nThank you for your work; I’d like to ask about the project.\nDaniel")
    calls = scripted(monkeypatch, [english_critique()])
    result = draft_editor.run(
        "english-opt-in", ENGLISH_CONTEXT, INSTRUCTIONS,
        seed=original, language=language, review_english=True,
    )
    assert result.status == "ready" and result.rounds == 0
    assert result.candidate["body"] == "Dear Alex,\n\nthank you for your work, I'd like to ask about the project.\nDaniel"
    purpose, instructions, data, options = calls[0]
    assert purpose == "outreach_text_review"
    assert instructions == draft_editor.ENGLISH_REVIEW_PROMPT
    assert data["candidate"] == result.candidate
    assert data["context"] == ENGLISH_CONTEXT
    assert draft_editor.ENGLISH_PROMPT in data["writing_instructions"]
    assert draft_editor.GERMAN_PROMPT not in data["writing_instructions"]
    assert "natural_english" in options["schema"]["required"]
    assert "natural_german" not in options["schema"]["properties"]


def test_opted_in_english_generation_uses_full_context_and_native_revision(editor_db, monkeypatch):
    first = english_candidate()
    revised = english_candidate("Dear Alex,\n\nI would like people to see that leaving these platforms is possible. Does this fit the discussion in your newsletter? https://thegreatlogout.org/\nDaniel")
    calls = scripted(monkeypatch, [first, english_critique("revise"), revised, english_critique()])
    result = draft_editor.run(
        "english-generation", ENGLISH_CONTEXT, INSTRUCTIONS,
        language="en", review_english=True,
    )
    assert result.status == "ready" and result.rounds == 1
    assert result.candidate == revised
    assert [c[0] for c in calls] == [
        "outreach_draft", "outreach_text_review", "outreach_revision", "outreach_text_review"
    ]
    assert calls[0][2] == ENGLISH_CONTEXT
    for purpose, instructions, data, options in calls:
        assert options.get("search", False) is False
        if purpose == "outreach_draft":
            assert draft_editor.ENGLISH_PROMPT in instructions
        else:
            assert data["context"] == ENGLISH_CONTEXT
        if purpose == "outreach_revision":
            assert draft_editor.ENGLISH_REVISION_PROMPT in instructions
            assert draft_editor.REVISION_PROMPT not in instructions
            assert data["review"]["verdict"] == "revise"
        if purpose == "outreach_text_review":
            assert instructions == draft_editor.ENGLISH_REVIEW_PROMPT
            assert INSTRUCTIONS in data["writing_instructions"]
            assert draft_editor.ENGLISH_PROMPT in data["writing_instructions"]


def test_opted_in_detected_english_receives_english_review(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [english_candidate(), english_critique()])
    result = draft_editor.run(
        "english-detected", ENGLISH_CONTEXT, INSTRUCTIONS, review_english=True
    )
    assert result.status == "ready"
    assert calls[1][1] == draft_editor.ENGLISH_REVIEW_PROMPT
    assert draft_editor.ENGLISH_PROMPT in calls[0][1]


def test_english_revision_limit_and_budget_resume_preserve_completed_work(editor_db, monkeypatch):
    first = english_candidate()
    second = english_candidate("Dear Alex,\n\nI hope people can leave these platforms without losing touch. Could this be useful for your newsletter? https://thegreatlogout.org/\nDaniel")
    third = english_candidate("Dear Alex,\n\nI hope people can find the confidence to leave together. Would the idea fit your newsletter? https://thegreatlogout.org/\nDaniel")
    # Contradictory ready verdicts may not bypass the bounded revision loop.
    failed = english_critique(natural_english=False)
    calls = scripted(monkeypatch, [
        first, failed, ai_client.AIBudgetExceeded("limit"), second,
        failed, third, failed,
    ])
    with pytest.raises(ai_client.AIBudgetExceeded):
        draft_editor.run(
            "english-resume", ENGLISH_CONTEXT, INSTRUCTIONS,
            language="en", review_english=True,
        )
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM draft_editor_runs").fetchone()
        assert row["stage"] == "revise" and row["lease_token"] == ""
        assert json.loads(row["candidate_json"]) == first
    result = draft_editor.run(
        "english-resume", ENGLISH_CONTEXT, INSTRUCTIONS,
        language="en", review_english=True,
    )
    assert result.status == "needs_review" and result.rounds == 2
    assert result.candidate == third
    assert result.review["reported_verdict"] == "ready"
    assert [c[0] for c in calls].count("outreach_draft") == 1
    assert [c[0] for c in calls].count("outreach_text_review") == 3
    with admin_db.database() as db:
        steps = db.execute("SELECT kind FROM draft_editor_steps ORDER BY sequence").fetchall()
        assert [row[0] for row in steps] == ["draft", "review", "revision", "review", "revision", "review"]
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('drafts','messages','outreach_deliveries')").fetchall()
    assert draft_editor.run(
        "english-resume", ENGLISH_CONTEXT, INSTRUCTIONS,
        language="en", review_english=True,
    ) == result
    assert len(calls) == 7


def test_english_opt_in_cannot_reuse_unreviewed_checkpoint(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [])
    original = english_candidate()
    result = draft_editor.run(
        "english-policy", ENGLISH_CONTEXT, INSTRUCTIONS, seed=original, language="en"
    )
    assert result.status == "english"
    with pytest.raises(draft_editor.EditorError, match="Arbeitsgrundlage"):
        draft_editor.run(
            "english-policy", ENGLISH_CONTEXT, INSTRUCTIONS,
            seed=original, language="en", review_english=True,
        )
    assert calls == []


def test_full_factual_context_reaches_every_critic_and_revision(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(), critique("revise"), candidate(), critique()])
    result = draft_editor.run("evidence", CONTEXT, INSTRUCTIONS, language="de")
    assert result.status == "ready"
    for purpose, _, data, kwargs in calls[1:]:
        assert data["context"] == CONTEXT
        assert data["context"]["opportunity"]["source_quote"]
        assert data["context"]["opportunity"]["conversation_start"]
        assert data["context"]["writing_note"]
        assert kwargs.get("search", False) is False
        if purpose == "outreach_text_review":
            assert INSTRUCTIONS in data["writing_instructions"]
            assert draft_editor.GERMAN_PROMPT in data["writing_instructions"]


@pytest.mark.parametrize("contradiction", [
    {"issues": [{"category": "facts", "passage": "erfunden", "instruction": "Entferne die unbelegte Behauptung."}]},
    {"factually_supported": False},
])
def test_ready_with_issues_or_failed_criterion_cannot_pass(editor_db, monkeypatch, contradiction):
    bad = critique(**contradiction)
    calls = scripted(monkeypatch, [bad, candidate(), bad, candidate(), bad])
    result = draft_editor.run("contradictory", CONTEXT, INSTRUCTIONS, seed=candidate(), language="de")
    assert result.status == "needs_review"
    assert result.review["verdict"] == "revise"
    assert result.review["reported_verdict"] == "ready"
    assert len(calls) == 5


def test_no_fit_stops_without_rewriting(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [critique("no_fit", grounded_connection=False)])
    result = draft_editor.run("no-fit", CONTEXT, INSTRUCTIONS, seed=candidate(), language="de")
    assert result.status == "no_fit" and result.rounds == 0
    assert len(calls) == 1


def test_writer_decline_stops_without_critic(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(should_draft=False, body="", subject="")])
    result = draft_editor.run("decline", CONTEXT, INSTRUCTIONS, language="de")
    assert result.status == "no_fit"
    assert result.review["summary"] == result.candidate["rationale"]
    assert result.review["verdict"] == "no_fit"
    assert len(calls) == 1


def test_cross_day_budget_resume_keeps_candidate_and_uses_current_date(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(), ai_client.AIBudgetExceeded("limit"), critique()])
    with pytest.raises(ai_client.AIBudgetExceeded):
        draft_editor.run("next-day", {**CONTEXT, "today": "2026-10-13"}, INSTRUCTIONS)
    result = draft_editor.run("next-day", {**CONTEXT, "today": "2026-10-14"}, INSTRUCTIONS)
    assert result.status == "ready"
    assert [c[0] for c in calls].count("outreach_draft") == 1
    assert calls[-1][2]["context"]["today"] == "2026-10-14"


def test_initial_german_prompt_is_not_duplicated(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(), critique()])
    draft_editor.run("prompt", CONTEXT, INSTRUCTIONS + draft_editor.GERMAN_PROMPT)
    assert calls[0][1].count(draft_editor.GERMAN_PROMPT) == 1


def test_changed_evidence_cannot_resume_old_run(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [candidate(), ai_client.AIBudgetExceeded("limit")])
    with pytest.raises(ai_client.AIBudgetExceeded):
        draft_editor.run("changed", CONTEXT, INSTRUCTIONS)
    with pytest.raises(draft_editor.EditorError, match="Arbeitsgrundlage"):
        draft_editor.run("changed", {**CONTEXT, "person": "Andere Person"}, INSTRUCTIONS)
    assert len(calls) == 2


def test_network_error_preserves_checkpoint_and_does_not_expose_payload(editor_db, monkeypatch):
    calls = scripted(monkeypatch, [ai_client.AIError("PRIVATE MODEL RESPONSE"), critique()])
    with pytest.raises(ai_client.AIError) as failure:
        draft_editor.run("network", CONTEXT, INSTRUCTIONS, seed=candidate(), language="de")
    assert "PRIVATE" not in str(failure.value)
    result = draft_editor.run("network", CONTEXT, INSTRUCTIONS, seed=candidate(), language="de")
    assert result.status == "ready" and len(calls) == 2


def test_invalid_review_is_not_accepted_or_exposed(editor_db, monkeypatch):
    scripted(monkeypatch, [{"verdict": "ready", "private": "PRIVATE RESPONSE"}])
    with pytest.raises(draft_editor.EditorError) as failure:
        draft_editor.run("invalid", CONTEXT, INSTRUCTIONS, seed=candidate())
    assert "PRIVATE" not in str(failure.value)
    with admin_db.database() as db:
        row = db.execute("SELECT * FROM draft_editor_runs").fetchone()
        assert row["stage"] == "review" and row["status"] == ""
        assert row["lease_token"] == ""
