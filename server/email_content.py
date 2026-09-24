from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EMAILS_JS = ROOT / "worker" / "src" / "emails.js"


@lru_cache(maxsize=1)
def load_email_sequences() -> dict[str, list[dict[str, Any]]]:
    source = EMAILS_JS.read_text(encoding="utf-8")
    return {
        "en": build_sequence(
            parse_js_value(source, "BASE_EMAIL_SEQUENCE"),
            parse_js_value(source, "POST_OPTIONS_BY_KEY"),
            parse_js_value(source, "REFLECTION_PROMPTS_BY_KEY"),
            "en",
        ),
        "de": build_sequence(
            parse_js_value(source, "BASE_EMAIL_SEQUENCE_DE"),
            parse_js_value(source, "POST_OPTIONS_BY_KEY_DE"),
            parse_js_value(source, "REFLECTION_PROMPTS_BY_KEY_DE"),
            "de",
        ),
    }


def build_sequence(
    base: list[dict[str, Any]],
    posts: dict[str, list[str]],
    prompts: dict[str, list[str]],
    language: str,
) -> list[dict[str, Any]]:
    feedback_keys = {"day-7", "day-14", "day-30", "month-6", "year-1"}
    sequence: list[dict[str, Any]] = []
    for source_email in base:
        email = dict(source_email)
        key = str(email["key"])
        email["language"] = language
        email["posts"] = posts.get(key, [])
        email["reflectionPrompts"] = prompts.get(key, [])
        email["feedbackInvite"] = key in feedback_keys
        sequence.append(email)
    return sequence


def parse_js_value(source: str, const_name: str) -> Any:
    marker = f"const {const_name} = "
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"Could not find {const_name} in {EMAILS_JS}")
    value_start = start + len(marker)
    opening = source[value_start]
    closing = "]" if opening == "[" else "}"
    value_end = find_matching(source, value_start, opening, closing)
    return json.loads(quote_object_keys(source[value_start : value_end + 1]))


def find_matching(source: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("Unclosed JS value")


def quote_object_keys(js_value: str) -> str:
    result: list[str] = []
    index = 0
    in_string = False
    escape = False
    while index < len(js_value):
        char = js_value[index]
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char.isalpha() or char == "_":
            previous = next((item for item in reversed(result) if not item.isspace()), "")
            if previous in {"{", ","}:
                end = index + 1
                while end < len(js_value) and (
                    js_value[end].isalnum() or js_value[end] == "_"
                ):
                    end += 1
                probe = end
                while probe < len(js_value) and js_value[probe].isspace():
                    probe += 1
                if probe < len(js_value) and js_value[probe] == ":":
                    result.append(f'"{js_value[index:end]}"')
                    index = end
                    continue
        result.append(char)
        index += 1
    return "".join(result)
