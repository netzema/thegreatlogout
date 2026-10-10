"""Find professional addresses on public, evidenced pages; never infer addresses."""

import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import Field

from server import admin_db as storage
from server import ai_client
from server.outreach import BOUNDARY, StrictModel, eligible, public_url

EMAIL = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
CONTACT_LINK = re.compile(
    r"contact|kontakt|impress|about|team|people|staff|redaktion", re.I
)
GENERIC = {
    "info",
    "contact",
    "kontakt",
    "office",
    "hello",
    "presse",
    "press",
    "redaktion",
    "editor",
    "editorial",
    "think",
}
EXCLUDED = re.compile(
    r"privacy|datenschutz|abuse|noreply|no-reply|webmaster|jobs|career|bewerbung", re.I
)


class ContactSelection(StrictModel):
    index: int = Field(ge=-1, le=49)
    person: str = Field(max_length=200)
    evidence: str = Field(max_length=800)


class ContactPages(StrictModel):
    urls: list[str] = Field(max_length=6)


def host(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def same_site(a, b):
    x, y = host(a), host(b)
    return bool(x and y and (x == y or x.endswith("." + y) or y.endswith("." + x)))


def fetch(url):
    """Pin each connection to a checked public IP, including every redirect."""
    for _ in range(4):
        url = public_url(url)
        if not url:
            raise ValueError("Keine öffentliche Quelle")
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ValueError("Ungültiger Port")
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in addresses
        ):
            raise ValueError("Keine öffentliche Quelle")
        conn = http.client.HTTPConnection(parts.hostname, port, timeout=7)
        sock = socket.create_connection((addresses[0][4][0], port), timeout=7)
        try:
            if parts.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=parts.hostname
                )
            conn.sock = sock
            conn.request(
                "GET",
                parts.path + ("?" + parts.query if parts.query else ""),
                headers={
                    "User-Agent": "TheGreatLogout/1.0 (public contact research)",
                    "Accept": "text/html,text/plain",
                    "Accept-Encoding": "identity",
                },
            )
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200 or not any(
                t in response.getheader("Content-Type", "")
                for t in ("text/html", "text/plain")
            ):
                raise ValueError("Quelle nicht lesbar")
            raw = response.read(800_001)
            if len(raw) > 800_000:
                raise ValueError("Quelle zu groß")
            charset = re.search(
                r"charset=([\w-]+)", response.getheader("Content-Type", "")
            )
            return url, raw.decode(charset[1] if charset else "utf-8", errors="replace")
        finally:
            conn.close()
            sock.close()
    raise ValueError("Zu viele Weiterleitungen")


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.text, self.links, self.mailtos, self.hidden = [], [], [], 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href", "")
            if href.lower().startswith("mailto:"):
                self.mailtos.append(unquote(href[7:].split("?")[0]))
            else:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden:
            self.text.append(text)

    def addresses(self):
        text = html.unescape(" ".join(self.text + self.mailtos))
        text = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", text, flags=re.I)
        text = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", text, flags=re.I)
        return {m.group().lower().strip(".") for m in EMAIL.finditer(text)}


def choose(candidates, contact):
    """Prefer the named person, otherwise an official organization inbox."""
    ranked = {}
    names = [n.casefold() for n in re.findall(r"\w+", contact["person"]) if len(n) >= 4]
    for address, source in candidates:
        local, domain = address.split("@")
        if EXCLUDED.search(local):
            continue
        official = same_site("https://" + domain, source)
        personal = bool(names and any(n in local for n in names))
        generic = local in GENERIC or local.split(".")[0] in GENERIC
        if personal or (official and generic):
            ranked[address] = (3 if personal else 2, source)
    if not ranked:
        return None
    best = max(score for score, _ in ranked.values())
    matches = [(a, source) for a, (score, source) in ranked.items() if score == best]
    # Different generic inboxes are interchangeable only by explicit priority.
    if len(matches) > 1 and best == 2:
        for prefix in (
            "contact",
            "kontakt",
            "info",
            "office",
            "redaktion",
            "press",
            "presse",
            "hello",
        ):
            subset = [(a, s) for a, s in matches if a.split("@")[0] == prefix]
            if len(subset) == 1:
                return subset[0]
    return matches[0] if len(matches) == 1 else None


def enrich(cid):
    with storage.database() as db:
        contact = dict(
            db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        )
        if contact["email"] or not eligible(db, cid):
            return bool(contact["email"])
    seeds = [u for u in (contact["contact_url"], contact["website"]) if public_url(u)]
    candidates, visited, pages = set(), set(), {}
    selected_person = ""
    deadline = time.monotonic() + 90

    def crawl(urls, limit=12):
        queue = list(urls)
        while queue and len(visited) < limit and time.monotonic() < deadline:
            url = public_url(queue.pop(0))
            if not url or url in visited:
                continue
            visited.add(url)
            try:
                final, text = fetch(url)
                # A redirect to another organization is not contact evidence.
                if not same_site(final, url):
                    continue
                page = Page(text)
                pages[final] = " ".join(" ".join(page.text).split())
                candidates.update((a, final) for a in page.addresses())
                found = choose(candidates, contact)
                if found:
                    return found
                queue.extend(
                    urljoin(final, link)
                    for link in page.links
                    if CONTACT_LINK.search(link)
                    and (
                        same_site(urljoin(final, link), final)
                        or re.search(
                            r"kontakt|contact|impress",
                            urlsplit(urljoin(final, link)).path,
                            re.I,
                        )
                    )
                )
            except (OSError, ValueError, http.client.HTTPException, LookupError):
                continue
        return None

    def select_evidenced_person():
        nonlocal selected_person
        choices = [
            (a, u)
            for a, u in sorted(candidates)
            if not EXCLUDED.search(a.split("@")[0])
        ][:50]
        if not choices:
            return None
        result, _ = ai_client.request(
            "contact_selection",
            BOUNDARY
            + " Wähle ausschließlich eine auf diesen offiziellen Quellen belegte berufliche "
            "Kontaktadresse für die genannte Organisation und den konkreten Ansprechpartner. "
            "Bevorzuge redaktionelle bzw. thematisch zuständige Kontakte oder den allgemeinen Kontakt. "
            "Keine privaten Kontakte, Datenschutzbeauftragten, Webagenturen oder fremden Organisationen. "
            "Bei einer personenbezogenen Adresse muss der Text die berufliche Rolle oder die Angabe als "
            "offizieller Kontakt belegen. Gib den Index aus der Liste zurück, bei Unklarheit -1. "
            "evidence muss ein wörtlicher zusammenhängender Textauszug der zugehörigen Seite sein, "
            "der die Rolle bzw. Zuständigkeit belegt. person nur bei im Text wörtlich belegtem Namen, sonst leer.",
            {
                "organization": contact["organization"],
                "person": contact["person"],
                "candidates": [
                    {"index": i, "address": a, "source": u}
                    for i, (a, u) in enumerate(choices)
                ],
                "pages": {u: pages[u][:16000] for _, u in choices},
            },
            schema=ContactSelection.model_json_schema(),
        )
        decision = ContactSelection.model_validate(result)
        if not 0 <= decision.index < len(choices):
            return None
        selected = choices[decision.index]
        page_text = pages[selected[1]]
        evidence = " ".join(decision.evidence.split())
        if len(evidence) < 12 or evidence not in page_text:
            return None
        if decision.person and decision.person in page_text:
            selected_person = decision.person
        return selected

    selected = crawl(seeds, limit=6)
    if not selected:
        selected = select_evidenced_person()
    if not selected:
        result, sources = ai_client.request(
            "contact_research",
            BOUNDARY
            + " Finde offizielle öffentlich zugängliche Kontakt-, Impressums- oder Teamseiten "
            "dieser Organisation bzw. der genannten beruflichen Ansprechperson. Nutze Websuche. "
            "Berücksichtige auch Autorenprofile und offizielle Programmseiten von Medienpartnern, "
            "wenn dort ausdrücklich der Kontakt der gesuchten Sendung oder Person angegeben ist. "
            "Gib nur tatsächlich belegte offizielle URLs zurück, keine Adressverzeichnisse, "
            "sozialen Netzwerke oder privaten Kontaktdaten. Keine E-Mail-Adressen raten. "
            "Wenn ein offizieller Webauftritt mitgeliefert wird, bleibe auf dessen Domain/Subdomains.",
            {
                k: contact[k]
                for k in (
                    "organization",
                    "person",
                    "website",
                    "contact_url",
                    "discovery_source",
                )
            },
            schema=ContactPages.model_json_schema(),
            search=True,
        )
        urls = ContactPages.model_validate(result).urls
        cited = {public_url(u) for u in sources}
        # Search may discover the official site when no website was known.
        urls = [
            u
            for u in urls
            if public_url(u) in cited
            and public_url(u)
            and (not seeds or any(same_site(u, s) for s in seeds))
        ]
        deadline = time.monotonic() + 60
        selected = crawl(urls)
        if not selected:
            selected = select_evidenced_person()
    if not selected:
        return False
    address, source = selected
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT email,person,website,contact_url FROM contacts WHERE id=?", (cid,)
        ).fetchone()
        if current["email"]:
            return True
        if not eligible(db, cid) or any(
            current[k] != contact[k] for k in ("person", "website", "contact_url")
        ):
            return False
        if db.execute(
            "SELECT id FROM contacts WHERE lower(email)=? AND id!=? UNION SELECT contact_id FROM contact_addresses WHERE address=? AND contact_id!=?",
            (address, cid, address, cid),
        ).fetchone():
            return False
        db.execute(
            "UPDATE contacts SET email=?,email_source=?,updated_at=?,person=CASE WHEN person='' THEN ? ELSE person END WHERE id=?",
            (
                address,
                "Öffentliche berufliche Kontaktseite: " + source,
                storage.now(),
                selected_person,
                cid,
            ),
        )
        # Public research must never expand mailbox-import permissions or consent.
    return True
