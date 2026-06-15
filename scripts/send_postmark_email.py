#!/usr/bin/env python3
"""
Send one selected Great Logout guide email directly through Postmark.

Examples:
  python scripts/send_postmark_email.py --list
  python scripts/send_postmark_email.py --key day-1
  python scripts/send_postmark_email.py --key day-7 --to you@example.com --first-name Daniel

The script reads POSTMARK_SERVER_TOKEN from the environment or from a local .env file.
If --to is omitted, it reads TEST_RECIPIENT from the root .env file.
It does not need Cloudflare.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EMAILS_JS = ROOT / "worker" / "src" / "emails.js"
ENV_FILE = ROOT / ".env"

DEFAULT_FROM_EMAIL = "hello@thegreatlogout.org"
DEFAULT_FROM_NAME = "The Great Logout"
DEFAULT_PUBLIC_SITE_URL = "https://www.thegreatlogout.org"
DEFAULT_API_BASE_URL = "https://api.thegreatlogout.org"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a selected Great Logout email through Postmark.")
    parser.add_argument("--list", action="store_true", help="List available email keys and exit.")
    parser.add_argument("--key", help="Email key to send, for example day-0, day-1, day-14, month-6.")
    parser.add_argument("--to", default=get_config("TEST_RECIPIENT", ""), help="Recipient email address. Defaults to TEST_RECIPIENT from .env.")
    parser.add_argument("--first-name", default="", help="Optional first name for the greeting.")
    parser.add_argument("--from-email", default=get_config("FROM_EMAIL", DEFAULT_FROM_EMAIL))
    parser.add_argument("--from-name", default=get_config("FROM_NAME", DEFAULT_FROM_NAME))
    parser.add_argument("--site-url", default=get_config("PUBLIC_SITE_URL", DEFAULT_PUBLIC_SITE_URL))
    parser.add_argument("--api-base-url", default=get_config("API_BASE_URL", DEFAULT_API_BASE_URL))
    parser.add_argument("--message-stream", default=get_config("POSTMARK_MESSAGE_STREAM", "outbound"))
    parser.add_argument("--dry-run", action="store_true", help="Render and print the payload without sending.")
    args = parser.parse_args()

    sequence = load_email_sequence()

    if args.list:
      for email in sequence:
          print(f"{email['key']:8}  {email['subject']}")
      return 0

    if not args.key:
        parser.error("--key is required unless --list is used")

    if not args.to:
        parser.error("--to is required unless TEST_RECIPIENT is set in .env")

    selected = next((email for email in sequence if email["key"] == args.key), None)
    if not selected:
        keys = ", ".join(email["key"] for email in sequence)
        raise SystemExit(f"Unknown key '{args.key}'. Available keys: {keys}")

    token = get_config("POSTMARK_SERVER_TOKEN", "")
    if not token:
        raise SystemExit("Missing POSTMARK_SERVER_TOKEN. Put it in .env or set it as an environment variable.")

    payload = build_postmark_payload(
        email=selected,
        recipient=args.to,
        first_name=args.first_name,
        from_name=args.from_name,
        from_email=args.from_email,
        site_url=args.site_url.rstrip("/"),
        api_base_url=args.api_base_url.rstrip("/"),
        message_stream=args.message_stream,
    )

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    result = send_postmark(token, payload)
    print(f"Sent '{selected['key']}' to {args.to}")
    if result.get("MessageID"):
        print(f"Postmark MessageID: {result['MessageID']}")
    return 0


def get_config(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]

    if not ENV_FILE.exists():
        return default

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")

    return default


def load_email_sequence() -> list[dict[str, Any]]:
    source = EMAILS_JS.read_text(encoding="utf-8")
    base = parse_js_value(source, "BASE_EMAIL_SEQUENCE")
    posts = parse_js_value(source, "POST_OPTIONS_BY_KEY")
    prompts = parse_js_value(source, "REFLECTION_PROMPTS_BY_KEY")

    feedback_keys = {"day-7", "day-14", "day-30", "month-6", "year-1"}
    for email in base:
        key = email["key"]
        email["posts"] = posts.get(key, [])
        email["reflectionPrompts"] = prompts.get(key, [])
        email["feedbackInvite"] = key in feedback_keys

    return base


def parse_js_value(source: str, const_name: str) -> Any:
    marker = f"const {const_name} = "
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"Could not find {const_name} in {EMAILS_JS}")

    value_start = start + len(marker)
    opening = source[value_start]
    closing = "]" if opening == "[" else "}"
    value_end = find_matching(source, value_start, opening, closing)
    js_value = source[value_start:value_end + 1]
    json_text = quote_object_keys(js_value)
    return json.loads(json_text)


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

    raise ValueError(f"Could not parse value starting at {start}")


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
            prev = previous_nonspace(result)
            if prev in {"{", ","}:
                end = index + 1
                while end < len(js_value) and (js_value[end].isalnum() or js_value[end] == "_"):
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


def previous_nonspace(chars: list[str]) -> str:
    for char in reversed(chars):
        if not char.isspace():
            return char
    return ""


def build_postmark_payload(
    *,
    email: dict[str, Any],
    recipient: str,
    first_name: str,
    from_name: str,
    from_email: str,
    site_url: str,
    api_base_url: str,
    message_stream: str,
) -> dict[str, Any]:
    return {
        "From": f"{from_name} <{from_email}>",
        "To": recipient,
        "Subject": email["subject"],
        "HtmlBody": render_html(email, first_name, site_url, api_base_url),
        "TextBody": render_text(email, first_name, site_url, api_base_url),
        "MessageStream": message_stream,
    }


def render_html(email: dict[str, Any], first_name: str, site_url: str, api_base_url: str) -> str:
    site_url = normalize_url(site_url)
    api_base_url = normalize_url(api_base_url)
    greeting = f"Hi {html.escape(first_name)}," if first_name else "Hi,"
    paragraphs = "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in email["body"])
    post_options = render_post_options_html(email.get("posts", []), site_url, api_base_url)
    reflection_prompts = render_reflection_prompts_html(email.get("reflectionPrompts", []))
    feedback_invite = render_feedback_invite_html(bool(email.get("feedbackInvite")))
    logo_url = f"{site_url}/assets/the-great-logout-mark.svg"
    generator_button = ""
    if email.get("posts"):
        generator_button = f"""
          <p style="margin:28px 0 0;">
            <a href="{site_url}/#generator" style="display:inline-block;background:#B6FF3B;color:#070807;text-decoration:none;font-weight:bold;border-radius:999px;padding:13px 18px;">Open the post generator</a>
          </p>
        """

    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#070807;color:#f4f4ef;font-family:Arial,sans-serif;line-height:1.58;">
    <div style="max-width:680px;margin:0 auto;padding:30px 20px 42px;">
      <div style="border:1px solid rgba(244,244,239,.12);border-radius:22px;background:#0f110f;overflow:hidden;">
        <div style="padding:22px 24px;border-bottom:1px solid rgba(244,244,239,.12);">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
            <tr>
              <td width="54" style="vertical-align:middle;width:54px;">
                <img src="{logo_url}" width="42" height="42" alt="" style="display:block;width:42px;height:42px;">
              </td>
              <td style="vertical-align:middle;">
                <div style="color:#f4f4ef;font-size:18px;line-height:1.1;font-weight:bold;">The Great Logout</div>
                <div style="color:#a4aaa1;font-size:13px;margin-top:5px;">A collective social media exit</div>
              </td>
            </tr>
          </table>
        </div>
        <div style="padding:28px 24px 8px;">
          <h1 style="font-size:34px;line-height:1.05;margin:0 0 22px;color:#f4f4ef;">{html.escape(email["title"])}</h1>
          <p>{greeting}</p>
          {paragraphs}
          {post_options}
          {reflection_prompts}
          {feedback_invite}
          {generator_button}
          <p style="margin-top:30px;">Log out visibly,<br><strong>The Great Logout</strong></p>
        </div>
        <div style="padding:18px 24px 24px;border-top:1px solid rgba(244,244,239,.12);color:#a4aaa1;font-size:13px;">
          <p style="margin:0 0 8px;">This is a manual test send.</p>
          <p style="margin:0;"><a href="{site_url}" style="color:#B6FF3B;">thegreatlogout.org</a></p>
        </div>
      </div>
    </div>
  </body>
</html>"""


def render_post_options_html(posts: list[str], site_url: str, api_base_url: str) -> str:
    site_url = normalize_url(site_url)
    api_base_url = normalize_url(api_base_url)
    if not posts:
        return ""

    cards = []
    for index, post in enumerate(posts, start=1):
        generator_link = f"{site_url}/?post={urllib.parse.quote(post)}#generator"
        svg_link = f"{api_base_url}/post.svg?text={urllib.parse.quote(post)}"
        cards.append(f"""
          <div style="border:1px solid rgba(244,244,239,.14);border-radius:16px;background:#121512;padding:16px;margin:12px 0;">
            <div style="color:#B6FF3B;font-family:Consolas,monospace;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;">Post option {index}</div>
            <div style="white-space:pre-line;font-size:20px;line-height:1.18;color:#f4f4ef;font-weight:bold;">{html.escape(post)}</div>
            <div style="margin-top:14px;">
              <a href="{generator_link}" style="color:#B6FF3B;text-decoration:none;font-weight:bold;">Open in generator</a>
              <span style="color:#6f766d;"> &nbsp;|&nbsp; </span>
              <a href="{svg_link}" style="color:#B6FF3B;text-decoration:none;font-weight:bold;">Download SVG</a>
            </div>
          </div>
        """)

    return f"""
      <div style="margin-top:30px;">
        <h2 style="font-size:20px;line-height:1.2;margin:0 0 12px;color:#f4f4ef;">Three posts you can use today</h2>
        {"".join(cards)}
      </div>
    """


def render_reflection_prompts_html(prompts: list[str]) -> str:
    if not prompts:
        return ""
    items = "".join(f'<li style="margin:10px 0;color:#f4f4ef;">{html.escape(prompt)}</li>' for prompt in prompts)
    return f"""
      <div style="margin-top:30px;border:1px solid rgba(244,244,239,.14);border-radius:16px;background:#121512;padding:18px;">
        <h2 style="font-size:20px;line-height:1.2;margin:0 0 12px;color:#f4f4ef;">Three things to reflect on</h2>
        <ul style="margin:0;padding-left:20px;">{items}</ul>
      </div>
    """


def render_feedback_invite_html(enabled: bool) -> str:
    if not enabled:
        return ""
    return """
      <div style="margin-top:22px;border:1px solid rgba(182,255,59,.32);border-radius:16px;background:rgba(182,255,59,.07);padding:18px;">
        <h2 style="font-size:20px;line-height:1.2;margin:0 0 10px;color:#f4f4ef;">Tell us what happened</h2>
        <p style="margin:0;color:#a4aaa1;">You can reply to this email with a comment, a note, or a short experience.</p>
      </div>
    """


def render_text(email: dict[str, Any], first_name: str, site_url: str, api_base_url: str) -> str:
    site_url = normalize_url(site_url)
    api_base_url = normalize_url(api_base_url)
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    lines = ["The Great Logout", "", email["title"], "", greeting, "", *email["body"], ""]

    if email.get("posts"):
        lines.extend(["Post options", ""])
        for index, post in enumerate(email["posts"], start=1):
            lines.extend([
                f"Post option {index}:",
                post,
                f"Open in generator: {site_url}/?post={urllib.parse.quote(post)}#generator",
                f"Download SVG: {api_base_url}/post.svg?text={urllib.parse.quote(post)}",
                "",
            ])

    if email.get("reflectionPrompts"):
        lines.extend(["Reflection prompts", ""])
        lines.extend(f"Reflection prompt {index}: {prompt}" for index, prompt in enumerate(email["reflectionPrompts"], start=1))
        lines.append("")

    if email.get("feedbackInvite"):
        lines.extend(["If you want, reply to this email and tell us what happened.", ""])

    lines.extend(["Log out visibly,", "The Great Logout", "", site_url])
    return "\n".join(lines)


def normalize_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return "https://www.thegreatlogout.org"
    if value.lower().startswith("https://"):
        return value
    return "https://" + value.removeprefix("http://")


def send_postmark(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.postmarkapp.com/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Postmark returned HTTP {error.code}: {details}") from error


if __name__ == "__main__":
    raise SystemExit(main())
