from __future__ import annotations

import html
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


LABELS = {
    "en": {
        "tagline": "A collective social media exit",
        "greeting": "Hi",
        "signoff": "Log out visibly,",
        "receiving": "You are receiving this because you requested the logout guide.",
        "unsubscribe": "Unsubscribe",
        "open_generator": "Open the post generator",
        "open_in_generator": "Open in generator",
        "post_option": "Post option",
        "post_options": "Three posts you can use today",
        "square_svg": "Square SVG",
        "vertical_svg": "Vertical SVG",
        "reflections": "Three things to reflect on",
        "feedback_title": "Tell us what happened",
        "feedback": "If you want, reply to this email and tell us what happened.",
    },
    "de": {
        "tagline": "Ein gemeinsamer Social-Media-Ausstieg",
        "greeting": "Hallo",
        "signoff": "Log dich sichtbar aus,",
        "receiving": "Du erhältst diese E-Mail, weil du den Logout-Guide angefordert hast.",
        "unsubscribe": "Abmelden",
        "open_generator": "Post-Generator öffnen",
        "open_in_generator": "Im Generator öffnen",
        "post_option": "Post-Option",
        "post_options": "Drei Posts, die du heute verwenden kannst",
        "square_svg": "Quadratisches SVG",
        "vertical_svg": "Vertikales SVG",
        "reflections": "Drei Fragen zum Nachdenken",
        "feedback_title": "Erzähl uns, was passiert ist",
        "feedback": "Wenn du möchtest, antworte auf diese E-Mail und erzähl uns, was passiert ist.",
    },
}


def build_postmark_payload(
    *,
    email: dict[str, Any],
    recipient: str,
    first_name: str,
    unsubscribe_token: str,
    from_name: str,
    from_email: str,
    reply_to: str,
    site_url: str,
    api_base_url: str,
    message_stream: str,
) -> dict[str, Any]:
    return {
        "From": f"{from_name} <{from_email}>",
        "To": recipient,
        "ReplyTo": reply_to,
        "Subject": email["subject"],
        "HtmlBody": render_html(
            email, first_name, unsubscribe_token, site_url, api_base_url
        ),
        "TextBody": render_text(
            email, first_name, unsubscribe_token, site_url, api_base_url
        ),
        "MessageStream": message_stream,
        "TrackOpens": False,
        "TrackLinks": "None",
    }


def send_postmark_message(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not token:
        raise RuntimeError("POSTMARK_SERVER_TOKEN is not configured")
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
        details = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Postmark returned HTTP {error.code}: {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError("Postmark could not be reached") from error


def render_html(
    email: dict[str, Any],
    first_name: str,
    token: str,
    site_url: str,
    api_base_url: str,
) -> str:
    language = normalize_language(email.get("language"))
    labels = LABELS[language]
    localized_site = f"{site_url}/de/" if language == "de" else f"{site_url}/"
    greeting = f"{labels['greeting']} {html.escape(first_name)}," if first_name else f"{labels['greeting']},"
    paragraphs = "\n".join(
        f"<p>{html.escape(str(paragraph))}</p>" for paragraph in email["body"]
    )
    posts = render_posts(email.get("posts", []), language, localized_site, api_base_url)
    reflections = render_reflections(email.get("reflectionPrompts", []), language)
    feedback = ""
    if email.get("feedbackInvite"):
        feedback = (
            '<div style="margin-top:22px;border:1px solid rgba(182,255,59,.32);'
            'border-radius:16px;background:rgba(182,255,59,.07);padding:18px;">'
            f'<h2 style="font-size:20px;margin:0 0 10px;">{labels["feedback_title"]}</h2>'
            f'<p style="margin:0;color:#a4aaa1;">{labels["feedback"]}</p></div>'
        )
    generator = ""
    if email.get("posts"):
        generator = (
            '<p style="margin:28px 0 0;"><a href="'
            f'{localized_site}#generator" style="display:inline-block;background:#B6FF3B;'
            'color:#070807;text-decoration:none;font-weight:bold;border-radius:999px;'
            f'padding:13px 18px;">{labels["open_generator"]}</a></p>'
        )
    unsubscribe_url = f"{api_base_url}/unsubscribe?token={urllib.parse.quote(token)}"
    return f"""<!doctype html>
<html lang="{language}"><body style="margin:0;background:#070807;color:#f4f4ef;font-family:Arial,sans-serif;line-height:1.58;">
<div style="max-width:680px;margin:0 auto;padding:30px 20px 42px;"><div style="border:1px solid rgba(244,244,239,.12);border-radius:22px;background:#0f110f;overflow:hidden;">
<div style="padding:22px 24px;border-bottom:1px solid rgba(244,244,239,.12);"><strong style="font-size:18px;">The Great Logout</strong><div style="color:#a4aaa1;font-size:13px;margin-top:5px;">{labels['tagline']}</div></div>
<div style="padding:28px 24px 8px;"><h1 style="font-size:34px;line-height:1.05;margin:0 0 22px;">{html.escape(str(email['title']))}</h1><p>{greeting}</p>{paragraphs}{posts}{reflections}{feedback}{generator}<p style="margin-top:30px;">{labels['signoff']}<br><strong>The Great Logout</strong></p></div>
<div style="padding:18px 24px 24px;border-top:1px solid rgba(244,244,239,.12);color:#a4aaa1;font-size:13px;"><p>{labels['receiving']}</p><p><a href="{localized_site}" style="color:#B6FF3B;">thegreatlogout.org</a> | <a href="{unsubscribe_url}" style="color:#a4aaa1;">{labels['unsubscribe']}</a></p></div>
</div></div></body></html>"""


def render_posts(
    posts: list[str], language: str, localized_site: str, api_base_url: str
) -> str:
    if not posts:
        return ""
    labels = LABELS[language]
    cards: list[str] = []
    for index, post in enumerate(posts, start=1):
        encoded = urllib.parse.quote(post)
        generator = f"{localized_site}?post={encoded}#generator"
        square = f"{api_base_url}/post.svg?text={encoded}&lang={language}"
        vertical = f"{square}&format=vertical"
        cards.append(
            '<div style="border:1px solid rgba(244,244,239,.14);border-radius:16px;'
            'background:#121512;padding:16px;margin:12px 0;">'
            f'<div style="color:#B6FF3B;font-size:12px;margin-bottom:10px;">{labels["post_option"]} {index}</div>'
            f'<div style="white-space:pre-line;font-size:20px;font-weight:bold;">{html.escape(post)}</div>'
            f'<div style="margin-top:14px;"><a href="{generator}" style="color:#B6FF3B;">{labels["open_in_generator"]}</a> | '
            f'<a href="{square}" style="color:#B6FF3B;">{labels["square_svg"]}</a> | '
            f'<a href="{vertical}" style="color:#B6FF3B;">{labels["vertical_svg"]}</a></div></div>'
        )
    return f'<div style="margin-top:30px;"><h2>{labels["post_options"]}</h2>{"".join(cards)}</div>'


def render_reflections(prompts: list[str], language: str) -> str:
    if not prompts:
        return ""
    items = "".join(f"<li>{html.escape(prompt)}</li>" for prompt in prompts)
    return f'<div style="margin-top:30px;"><h2>{LABELS[language]["reflections"]}</h2><ul>{items}</ul></div>'


def render_text(
    email: dict[str, Any],
    first_name: str,
    token: str,
    site_url: str,
    api_base_url: str,
) -> str:
    language = normalize_language(email.get("language"))
    labels = LABELS[language]
    localized_site = f"{site_url}/de/" if language == "de" else f"{site_url}/"
    greeting = f"{labels['greeting']} {first_name}," if first_name else f"{labels['greeting']},"
    lines = ["The Great Logout", "", str(email["title"]), "", greeting, "", *email["body"], ""]
    for index, post in enumerate(email.get("posts", []), start=1):
        encoded = urllib.parse.quote(post)
        lines.extend(
            [
                f"{labels['post_option']} {index}:",
                post,
                f"{labels['open_in_generator']}: {localized_site}?post={encoded}#generator",
                f"{labels['square_svg']}: {api_base_url}/post.svg?text={encoded}&lang={language}",
                f"{labels['vertical_svg']}: {api_base_url}/post.svg?text={encoded}&lang={language}&format=vertical",
                "",
            ]
        )
    if email.get("reflectionPrompts"):
        lines.extend([labels["reflections"], *email["reflectionPrompts"], ""])
    if email.get("feedbackInvite"):
        lines.extend([labels["feedback"], ""])
    lines.extend(
        [
            labels["signoff"],
            "The Great Logout",
            "",
            localized_site,
            "",
            labels["receiving"],
            f"{labels['unsubscribe']}: {api_base_url}/unsubscribe?token={urllib.parse.quote(token)}",
        ]
    )
    return "\n".join(lines)


def normalize_language(value: Any) -> str:
    return "de" if str(value or "en").lower().startswith("de") else "en"
