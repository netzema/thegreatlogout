(() => {
  "use strict";

  const CONSENT_COOKIE = "tgl_analytics_consent";
  const VISITOR_COOKIE = "tgl_analytics_visitor";
  const SESSION_KEY = "tgl_analytics_session";
  const ENDPOINT = "/api/analytics/events";
  const CONSENT_MAX_AGE = 180 * 24 * 60 * 60;
  const SESSION_TIMEOUT_MS = 30 * 60 * 1000;
  const ENGAGEMENT_FLUSH_MS = 30 * 1000;
  const validId = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

  let trackingEnabled = false;
  let listenersAttached = false;
  let engagementTimer = null;
  let activeSince = null;
  let pendingActiveMs = 0;

  const cookieDomain = location.hostname.endsWith("thegreatlogout.org")
    ? "; Domain=.thegreatlogout.org"
    : "";
  const secureCookie = location.protocol === "https:" ? "; Secure" : "";

  const readCookie = (name) => {
    const prefix = `${encodeURIComponent(name)}=`;
    const entry = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(prefix));
    return entry ? decodeURIComponent(entry.slice(prefix.length)) : "";
  };

  const writeCookie = (name, value, maxAge) => {
    document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secureCookie}${cookieDomain}`;
  };

  const deleteCookie = (name) => writeCookie(name, "", 0);

  const createId = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const value = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
  };

  const sanitizeText = (value, maxLength = 100) =>
    String(value || "")
      .replace(/[\u0000-\u001f\u007f]/g, "")
      .replace(/\?/g, "")
      .trim()
      .slice(0, maxLength);

  const referrerHost = () => {
    if (!document.referrer) return "";
    try {
      return sanitizeText(new URL(document.referrer).hostname.toLowerCase(), 255);
    } catch {
      return "";
    }
  };

  const sourceFromReferrer = (host) => {
    if (!host) return "direct";
    if (host === location.hostname.toLowerCase() || host.endsWith("thegreatlogout.org")) {
      return "internal";
    }
    if (/(^|\.)(google|bing|duckduckgo|ecosia|yahoo)\./i.test(host)) return "organic";
    return "referral";
  };

  const currentAcquisition = () => {
    const parameters = new URLSearchParams(location.search);
    const campaignSource = sanitizeText(parameters.get("utm_source"));
    const host = referrerHost();
    return {
      referrer_host: host,
      source: campaignSource ? "campaign" : sourceFromReferrer(host),
      campaign: sanitizeText(parameters.get("utm_campaign")),
      campaign_source: campaignSource,
      campaign_medium: sanitizeText(parameters.get("utm_medium")),
      campaign_content: sanitizeText(parameters.get("utm_content")),
      campaign_term: sanitizeText(parameters.get("utm_term")),
    };
  };

  const getSession = () => {
    const now = Date.now();
    let stored = null;
    try {
      stored = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
    } catch {
      stored = null;
    }
    if (
      !stored ||
      !validId.test(stored.id || "") ||
      !Number.isFinite(stored.lastActive) ||
      now - stored.lastActive > SESSION_TIMEOUT_MS
    ) {
      stored = { id: createId(), lastActive: now, acquisition: currentAcquisition() };
    } else {
      stored.lastActive = now;
    }
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(stored));
    return stored;
  };

  const getVisitorId = () => {
    const existing = readCookie(VISITOR_COOKIE);
    if (validId.test(existing)) return existing;
    const visitorId = createId();
    writeCookie(VISITOR_COOKIE, visitorId, CONSENT_MAX_AGE);
    return visitorId;
  };

  const deviceType = () => {
    if (matchMedia("(max-width: 767px)").matches) return "mobile";
    if (matchMedia("(max-width: 1100px)").matches) return "tablet";
    return "desktop";
  };

  const sendEvent = (eventType, details = {}, preferBeacon = false) => {
    if (!trackingEnabled || readCookie(CONSENT_COOKIE) !== "granted") return;
    const session = getSession();
    const acquisition = session.acquisition || currentAcquisition();
    const payload = {
      event_id: createId(),
      visitor_id: getVisitorId(),
      session_id: session.id,
      event_type: eventType,
      path: location.pathname || "/",
      referrer_host: acquisition.referrer_host || null,
      source: acquisition.source || "direct",
      campaign: acquisition.campaign || null,
      campaign_source: acquisition.campaign_source || null,
      campaign_medium: acquisition.campaign_medium || null,
      campaign_content: acquisition.campaign_content || null,
      campaign_term: acquisition.campaign_term || null,
      device_type: deviceType(),
      target: details.target || null,
      value: Number.isFinite(details.value) ? details.value : null,
    };
    const body = JSON.stringify(payload);
    if (preferBeacon && navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
      return;
    }
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
  };

  const clickTarget = (link) => {
    const href = link.getAttribute("href") || "";
    if (!href || href.startsWith("javascript:")) return "";
    if (href.startsWith("mailto:")) return "Email";
    try {
      const url = new URL(href, location.href);
      if (url.origin === location.origin) return `${url.pathname}${url.hash}`.slice(0, 512);
      return `${url.hostname}${url.pathname === "/" ? "" : url.pathname}`.slice(0, 512);
    } catch {
      return sanitizeText(href.split("?")[0], 512);
    }
  };

  const flushEngagement = (preferBeacon = false) => {
    if (!trackingEnabled) return;
    if (activeSince !== null) {
      pendingActiveMs += performance.now() - activeSince;
      activeSince = performance.now();
    }
    const activeSeconds = Math.floor(pendingActiveMs / 1000);
    if (activeSeconds < 1) return;
    pendingActiveMs -= activeSeconds * 1000;
    sendEvent("engagement", { value: Math.min(activeSeconds, 3600) }, preferBeacon);
  };

  const startTracking = () => {
    if (trackingEnabled || readCookie(CONSENT_COOKIE) !== "granted") return;
    trackingEnabled = true;
    getVisitorId();
    getSession();
    sendEvent("page_view");
    if (document.visibilityState === "visible") activeSince = performance.now();
    engagementTimer = window.setInterval(() => flushEngagement(), ENGAGEMENT_FLUSH_MS);
    if (listenersAttached) return;
    listenersAttached = true;
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        flushEngagement(true);
        activeSince = null;
      } else if (trackingEnabled) {
        activeSince = performance.now();
      }
    });
    window.addEventListener("pagehide", () => flushEngagement(true));
    document.addEventListener("click", (event) => {
      const link = event.target.closest?.("a[href]");
      if (!link || link.closest("[data-no-analytics]")) return;
      const target = clickTarget(link);
      if (target) sendEvent("link_click", { target }, true);
    });
  };

  const stopTracking = () => {
    trackingEnabled = false;
    activeSince = null;
    pendingActiveMs = 0;
    if (engagementTimer !== null) window.clearInterval(engagementTimer);
    engagementTimer = null;
    sessionStorage.removeItem(SESSION_KEY);
    deleteCookie(VISITOR_COOKIE);
  };

  const isGerman = document.documentElement.lang.toLowerCase().startsWith("de");
  const copy = isGerman
    ? {
        kicker: "Optionale Website-Statistik",
        title: "Hilf mit, die Kampagne zu verbessern",
        body: "Mit deiner Zustimmung erfassen wir eine datensparsame Nutzungsstatistik auf unserem eigenen Server. So sehen wir, welche Outreach-Kampagnen funktionieren.",
        privacy: "Mehr zum Datenschutz",
        denied: "Ablehnen",
        granted: "Zustimmen",
        close: "Schließen",
        statusGranted: "Aktueller Status: Statistik ist erlaubt.",
        statusDenied: "Aktueller Status: Statistik ist abgelehnt.",
      }
    : {
        kicker: "Optional website statistics",
        title: "Help improve the campaign",
        body: "With your consent, we collect privacy-conscious usage statistics on our own server. This helps us understand which outreach campaigns work.",
        privacy: "Read the privacy policy",
        denied: "Decline",
        granted: "Allow",
        close: "Close",
        statusGranted: "Current status: statistics are allowed.",
        statusDenied: "Current status: statistics are declined.",
      };
  const privacyUrl = isGerman ? "/de/privacy.html#website-statistics" : "/privacy.html#website-statistics";

  const ensureConsentDialog = () => {
    let dialog = document.querySelector("#tgl-consent-dialog");
    if (dialog) return dialog;
    dialog = document.createElement("section");
    dialog.id = "tgl-consent-dialog";
    dialog.className = "tgl-consent-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-labelledby", "tgl-consent-title");
    dialog.setAttribute("aria-describedby", "tgl-consent-copy");
    dialog.setAttribute("data-no-analytics", "");
    dialog.hidden = true;
    dialog.innerHTML = `
      <div class="tgl-consent-inner">
        <div class="tgl-consent-copy">
          <p class="tgl-consent-kicker">${copy.kicker}</p>
          <h2 id="tgl-consent-title">${copy.title}</h2>
          <p id="tgl-consent-copy">${copy.body}</p>
          <p class="tgl-consent-status" aria-live="polite"></p>
          <a href="${privacyUrl}">${copy.privacy}</a>
        </div>
        <div class="tgl-consent-actions">
          <button type="button" data-consent="denied">${copy.denied}</button>
          <button type="button" data-consent="granted">${copy.granted}</button>
          <button class="tgl-consent-close" type="button" data-consent-close>${copy.close}</button>
        </div>
      </div>`;
    document.body.append(dialog);
    dialog.querySelectorAll("[data-consent]").forEach((button) => {
      button.addEventListener("click", () => {
        const choice = button.dataset.consent;
        writeCookie(CONSENT_COOKIE, choice, CONSENT_MAX_AGE);
        if (choice === "granted") startTracking();
        else stopTracking();
        dialog.hidden = true;
        dialog.classList.remove("is-required");
      });
    });
    dialog.querySelector("[data-consent-close]").addEventListener("click", () => {
      dialog.hidden = true;
    });
    return dialog;
  };

  const showPreferences = (required = false) => {
    const dialog = ensureConsentDialog();
    const consent = readCookie(CONSENT_COOKIE);
    const status = dialog.querySelector(".tgl-consent-status");
    status.textContent = consent === "granted"
      ? copy.statusGranted
      : consent === "denied"
        ? copy.statusDenied
        : "";
    dialog.classList.toggle("is-required", required);
    dialog.hidden = false;
    dialog.querySelector("[data-consent='denied']").focus({ preventScroll: true });
  };

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-analytics-settings]");
    if (!button) return;
    event.preventDefault();
    showPreferences(false);
  });

  window.tglAnalytics = {
    showPreferences,
    trackGuideSignup: () => sendEvent("guide_signup_success", { target: "Logout guide" }, true),
    trackPostDownload: (format) => sendEvent("post_download", { target: sanitizeText(format, 100) }, true),
  };

  if (readCookie(CONSENT_COOKIE) === "granted") startTracking();
  else if (!readCookie(CONSENT_COOKIE)) showPreferences(true);
})();
