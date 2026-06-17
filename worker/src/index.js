import { EMAIL_SEQUENCE } from "./emails.js";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return corsResponse(null, env, 204, request);
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return corsResponse({ ok: true }, env, 200, request);
    }

    if (request.method === "GET" && url.pathname === "/post.svg") {
      return handlePostSvg(url);
    }

    if (request.method === "GET" && url.pathname === "/unsubscribe") {
      return handleUnsubscribe(url, env);
    }

    if (request.method === "POST" && url.pathname === "/subscribe") {
      return handleSubscribe(request, env);
    }

    return corsResponse({ error: "Not found." }, env, 404, request);
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(sendDueEmails(env));
  }
};

async function handleSubscribe(request, env) {
  const input = await request.json().catch(() => null);
  const email = normalizeEmail(input?.email);
  const firstName = cleanText(input?.firstName || "", 80);
  const guideLength = [1, 3, 7].includes(Number(input?.guideLength)) ? Number(input.guideLength) : 7;
  const plannedLogoutDate = cleanDate(input?.logoutDate);
  const consent = input?.consent === true;
  const unsubscribeToken = crypto.randomUUID();

  if (!email) {
    return corsResponse({ error: "Please enter a valid email address." }, env, 400, request);
  }

  if (!consent) {
    return corsResponse({ error: "Please confirm that you want to receive the guide." }, env, 400, request);
  }

  const now = new Date();
  await env.DB.prepare(`
    INSERT INTO subscribers (email, first_name, guide_length, planned_logout_date, unsubscribe_token, status)
    VALUES (?, ?, ?, ?, ?, 'active')
    ON CONFLICT(email) DO UPDATE SET
      first_name = excluded.first_name,
      guide_length = excluded.guide_length,
      planned_logout_date = excluded.planned_logout_date,
      unsubscribe_token = COALESCE(subscribers.unsubscribe_token, excluded.unsubscribe_token),
      status = 'active',
      unsubscribed_at = NULL
  `).bind(email, firstName || null, guideLength, plannedLogoutDate || null, unsubscribeToken).run();

  const subscriber = await env.DB.prepare("SELECT id FROM subscribers WHERE email = ?").bind(email).first();
  await scheduleEmails(env, subscriber.id, now, guideLength);
  await sendWelcomeEmail(env, subscriber.id, email, firstName);

  return corsResponse({ ok: true }, env, 200, request);
}

async function scheduleEmails(env, subscriberId, startDate, guideLength) {
  const sequence = EMAIL_SEQUENCE.filter(email => {
    if (!email.key.startsWith("day-")) return true;
    const day = Number(email.key.replace("day-", ""));
    return day === 0 || day <= guideLength || day > 7;
  });

  for (const email of sequence) {
    const sendAfter = new Date(startDate.getTime() + email.delayDays * 24 * 60 * 60 * 1000).toISOString();
    await env.DB.prepare(`
      INSERT OR IGNORE INTO email_sends (subscriber_id, sequence_key, send_after)
      VALUES (?, ?, ?)
    `).bind(subscriberId, email.key, sendAfter).run();
  }
}

async function sendDueEmails(env) {
  const due = await env.DB.prepare(`
    SELECT
      email_sends.id,
      email_sends.sequence_key,
      subscribers.email,
      subscribers.first_name,
      subscribers.unsubscribe_token
    FROM email_sends
    JOIN subscribers ON subscribers.id = email_sends.subscriber_id
    WHERE email_sends.sent_at IS NULL
      AND subscribers.status = 'active'
      AND email_sends.send_after <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ORDER BY email_sends.send_after ASC
    LIMIT 50
  `).all();

  for (const row of due.results || []) {
    const email = EMAIL_SEQUENCE.find(item => item.key === row.sequence_key);
    if (!email) continue;

    try {
      const result = await sendPostmarkEmail(env, row.email, row.first_name, row.unsubscribe_token, email);
      await env.DB.prepare(`
        UPDATE email_sends
        SET sent_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), postmark_message_id = ?, error = NULL
        WHERE id = ?
      `).bind(result.MessageID || null, row.id).run();
    } catch (error) {
      await env.DB.prepare("UPDATE email_sends SET error = ? WHERE id = ?")
        .bind(String(error.message || error).slice(0, 500), row.id)
        .run();
    }
  }
}

async function sendWelcomeEmail(env, subscriberId, emailAddress, firstName) {
  const row = await env.DB.prepare(`
    SELECT id
    FROM email_sends
    WHERE subscriber_id = ?
      AND sequence_key = 'day-0'
      AND sent_at IS NULL
    LIMIT 1
  `).bind(subscriberId).first();

  if (!row) return;

  const subscriber = await env.DB.prepare("SELECT unsubscribe_token FROM subscribers WHERE id = ?")
    .bind(subscriberId)
    .first();
  const email = EMAIL_SEQUENCE.find(item => item.key === "day-0");
  if (!email || !subscriber?.unsubscribe_token) return;

  try {
    const result = await sendPostmarkEmail(env, emailAddress, firstName, subscriber.unsubscribe_token, email);
    await env.DB.prepare(`
      UPDATE email_sends
      SET sent_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), postmark_message_id = ?, error = NULL
      WHERE id = ?
    `).bind(result.MessageID || null, row.id).run();
  } catch (error) {
    await env.DB.prepare("UPDATE email_sends SET error = ? WHERE id = ?")
      .bind(String(error.message || error).slice(0, 500), row.id)
      .run();
  }
}

async function sendPostmarkEmail(env, to, firstName, unsubscribeToken, email) {
  const response = await fetch("https://api.postmarkapp.com/email", {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-Postmark-Server-Token": env.POSTMARK_SERVER_TOKEN
    },
    body: JSON.stringify({
      From: `${env.FROM_NAME} <${env.FROM_EMAIL}>`,
      To: to,
      Subject: email.subject,
      HtmlBody: renderEmailHtml(env, firstName, unsubscribeToken, email),
      TextBody: renderEmailText(env, firstName, unsubscribeToken, email),
      MessageStream: "outbound"
    })
  });

  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.Message || "Postmark rejected the email.");
  }
  return result;
}

function renderEmailHtml(env, firstName, unsubscribeToken, email) {
  const greeting = firstName ? `Hi ${escapeHtml(firstName)},` : "Hi,";
  const paragraphs = email.body.map(paragraph => `<p>${escapeHtml(paragraph)}</p>`).join("\n");
  const siteUrl = normalizeUrl(env.PUBLIC_SITE_URL || "https://www.thegreatlogout.org");
  const generatorUrl = `${siteUrl}/#generator`;
  const postOptions = renderPostOptionsHtml(env, email.posts || []);
  const reflectionPrompts = renderReflectionPromptsHtml(email.reflectionPrompts || []);
  const feedbackInvite = renderFeedbackInviteHtml(email);
  const generatorButton = renderGeneratorButtonHtml(generatorUrl, email.posts || []);
  const unsubscribeUrl = buildUnsubscribeLink(env, unsubscribeToken);
  const logoUrl = `${siteUrl}/assets/the-great-logout-mark.svg`;

  return `<!doctype html>
<html>
  <body style="margin:0;background:#070807;color:#f4f4ef;font-family:Arial,sans-serif;line-height:1.58;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;">${escapeHtml(email.subject)} - The Great Logout</div>
    <div style="max-width:680px;margin:0 auto;padding:30px 20px 42px;">
      <div style="border:1px solid rgba(244,244,239,.12);border-radius:22px;background:#0f110f;overflow:hidden;">
        <div style="padding:22px 24px;border-bottom:1px solid rgba(244,244,239,.12);">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
            <tr>
              <td width="54" style="vertical-align:middle;width:54px;">
                <img src="${logoUrl}" width="42" height="42" alt="" style="display:block;width:42px;height:42px;">
              </td>
              <td style="vertical-align:middle;">
                <div style="color:#f4f4ef;font-size:18px;line-height:1.1;font-weight:bold;">The Great Logout</div>
                <div style="color:#a4aaa1;font-size:13px;margin-top:5px;">A collective social media exit</div>
              </td>
              <td align="right" style="vertical-align:middle;color:#B6FF3B;font-size:30px;font-weight:bold;">-&gt;</td>
            </tr>
          </table>
        </div>

        <div style="padding:28px 24px 8px;">
          <h1 style="font-size:34px;line-height:1.05;margin:0 0 22px;color:#f4f4ef;">${escapeHtml(email.title)}</h1>
          <p>${greeting}</p>
          ${paragraphs}

          ${postOptions}
          ${reflectionPrompts}
          ${feedbackInvite}

          ${generatorButton}

          <p style="margin-top:30px;">Log out visibly,<br><strong>The Great Logout</strong></p>
        </div>

        <div style="padding:18px 24px 24px;border-top:1px solid rgba(244,244,239,.12);color:#a4aaa1;font-size:13px;">
          <p style="margin:0 0 8px;">You are receiving this because you requested the logout guide.</p>
          <p style="margin:0;"><a href="${siteUrl}" style="color:#B6FF3B;">thegreatlogout.org</a> <span style="color:#6f766d;">|</span> <a href="${unsubscribeUrl}" style="color:#a4aaa1;">Unsubscribe</a></p>
        </div>
      </div>
    </div>
  </body>
</html>`;
}

function renderEmailText(env, firstName, unsubscribeToken, email) {
  const greeting = firstName ? `Hi ${firstName},` : "Hi,";
  const siteUrl = normalizeUrl(env.PUBLIC_SITE_URL || "https://www.thegreatlogout.org");
  const unsubscribeUrl = buildUnsubscribeLink(env, unsubscribeToken);
  const postLines = (email.posts || []).flatMap((post, index) => [
    `Post option ${index + 1}:`,
    post,
    `Open in generator: ${buildGeneratorLink(env, post)}`,
    `Download SVG: ${buildPostSvgLink(env, post)}`,
    ""
  ]);
  const reflectionLines = (email.reflectionPrompts || []).flatMap((prompt, index) => [
    `Reflection prompt ${index + 1}: ${prompt}`
  ]);

  return [
    "The Great Logout",
    "",
    email.title,
    "",
    greeting,
    "",
    ...email.body,
    "",
    ...(postLines.length ? ["Post options", "", ...postLines] : []),
    ...(reflectionLines.length ? ["Reflection prompts", "", ...reflectionLines, ""] : []),
    ...(email.feedbackInvite ? [
      "If you want, reply to this email and tell us what happened. We may later ask whether we can share a short anonymized version on the website.",
      ""
    ] : []),
    ...((email.posts || []).length ? ["Open the post generator:", `${siteUrl}/#generator`, ""] : []),
    "Log out visibly,",
    "The Great Logout",
    "",
    siteUrl,
    "",
    "You are receiving this because you requested the logout guide.",
    `Unsubscribe: ${unsubscribeUrl}`
  ].join("\n");
}

function renderGeneratorButtonHtml(generatorUrl, posts) {
  if (!posts.length) return "";

  return `
    <p style="margin:28px 0 0;">
      <a href="${generatorUrl}" style="display:inline-block;background:#B6FF3B;color:#070807;text-decoration:none;font-weight:bold;border-radius:999px;padding:13px 18px;">Open the post generator</a>
    </p>
  `;
}

function renderPostOptionsHtml(env, posts) {
  if (!posts.length) return "";

  const cards = posts.map((post, index) => `
    <div style="border:1px solid rgba(244,244,239,.14);border-radius:16px;background:#121512;padding:16px;margin:12px 0;">
      <div style="color:#B6FF3B;font-family:Consolas,monospace;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;">Post option ${index + 1}</div>
      <div style="white-space:pre-line;font-size:20px;line-height:1.18;color:#f4f4ef;font-weight:bold;">${escapeHtml(post)}</div>
      <div style="margin-top:14px;">
        <a href="${buildGeneratorLink(env, post)}" style="color:#B6FF3B;text-decoration:none;font-weight:bold;">Open in generator</a>
        <span style="color:#6f766d;"> &nbsp;|&nbsp; </span>
        <a href="${buildPostSvgLink(env, post)}" style="color:#B6FF3B;text-decoration:none;font-weight:bold;">Download SVG</a>
      </div>
    </div>
  `).join("");

  return `
    <div style="margin-top:30px;">
      <h2 style="font-size:20px;line-height:1.2;margin:0 0 12px;color:#f4f4ef;">Three posts you can use today</h2>
      ${cards}
    </div>
  `;
}

function renderReflectionPromptsHtml(prompts) {
  if (!prompts.length) return "";

  const items = prompts.map(prompt => `
    <li style="margin:10px 0;color:#f4f4ef;">${escapeHtml(prompt)}</li>
  `).join("");

  return `
    <div style="margin-top:30px;border:1px solid rgba(244,244,239,.14);border-radius:16px;background:#121512;padding:18px;">
      <h2 style="font-size:20px;line-height:1.2;margin:0 0 12px;color:#f4f4ef;">Three things to reflect on</h2>
      <ul style="margin:0;padding-left:20px;">${items}</ul>
    </div>
  `;
}

function renderFeedbackInviteHtml(email) {
  if (!email.feedbackInvite) return "";

  return `
    <div style="margin-top:22px;border:1px solid rgba(182,255,59,.32);border-radius:16px;background:rgba(182,255,59,.07);padding:18px;">
      <h2 style="font-size:20px;line-height:1.2;margin:0 0 10px;color:#f4f4ef;">Tell us what happened</h2>
      <p style="margin:0;color:#a4aaa1;">You can reply to this email with a comment, a note, or a short experience. We may later ask whether we can share an anonymized version on the website so others can see what leaving actually feels like.</p>
    </div>
  `;
}

function buildGeneratorLink(env, post) {
  const siteUrl = normalizeUrl(env.PUBLIC_SITE_URL || "https://www.thegreatlogout.org");
  return `${siteUrl}/?post=${encodeURIComponent(post)}#generator`;
}

function buildPostSvgLink(env, post) {
  const apiBaseUrl = normalizeUrl(env.API_BASE_URL || "https://api.thegreatlogout.org");
  return `${apiBaseUrl}/post.svg?text=${encodeURIComponent(post)}`;
}

function buildUnsubscribeLink(env, token) {
  const apiBaseUrl = normalizeUrl(env.API_BASE_URL || "https://api.thegreatlogout.org");
  return `${apiBaseUrl}/unsubscribe?token=${encodeURIComponent(token || "")}`;
}

function normalizeUrl(value) {
  const trimmed = String(value || "").trim().replace(/\/+$/, "");
  if (!trimmed) return "https://www.thegreatlogout.org";
  if (/^https:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed.replace(/^http:\/\//i, "")}`;
}

async function handleUnsubscribe(url, env) {
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return new Response("Missing unsubscribe token.", {
      status: 400,
      headers: { "Content-Type": "text/plain; charset=utf-8" }
    });
  }

  await env.DB.prepare(`
    UPDATE subscribers
    SET status = 'unsubscribed',
      unsubscribed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE unsubscribe_token = ?
  `).bind(token).run();

  return new Response(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Unsubscribed - The Great Logout</title>
  </head>
  <body style="margin:0;background:#070807;color:#f4f4ef;font-family:Arial,sans-serif;line-height:1.5;">
    <main style="max-width:620px;margin:0 auto;padding:56px 20px;">
      <p style="color:#B6FF3B;font-family:monospace;text-transform:uppercase;letter-spacing:.08em;">The Great Logout</p>
      <h1 style="font-size:38px;line-height:1.05;margin:0 0 18px;">You are unsubscribed.</h1>
      <p>You will not receive more logout guide emails at this address.</p>
      <p><a href="${env.PUBLIC_SITE_URL}" style="color:#B6FF3B;">Return to the website</a></p>
    </main>
  </body>
</html>`, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}

function handlePostSvg(url) {
  const text = cleanText(url.searchParams.get("text") || "The exit is the message.", 280);
  const color = url.searchParams.get("color") === "green" ? "#B6FF3B" : "#f4f4ef";
  const svg = buildSocialPostSvg(text, color);

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Content-Disposition": "attachment; filename=\"great-logout-post.svg\""
    }
  });
}

function buildSocialPostSvg(text, color) {
  const width = 1080;
  const height = 1080;
  const lines = wrapSvgText(text, 18);
  const fontSize = Math.max(54, Math.min(108, Math.floor(width / Math.max(9, Math.max(...lines.map(line => line.length || 1)) * 0.58))));
  const lineHeight = Math.round(fontSize * 1.14);
  const startY = Math.round((height - 180 - lines.length * lineHeight) / 2 + fontSize);
  const tspans = lines.map((line, index) => `<tspan x="50%" y="${startY + index * lineHeight}">${escapeHtml(line)}</tspan>`).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <rect width="100%" height="100%" fill="#070807"/>
  <defs>
    <pattern id="grid" width="120" height="120" patternUnits="userSpaceOnUse">
      <path d="M 120 0 L 0 0 0 120" fill="none" stroke="rgba(244,244,239,0.055)" stroke-width="2"/>
    </pattern>
  </defs>
  <rect width="100%" height="100%" fill="url(#grid)"/>
  <text text-anchor="middle" font-family="Arial, sans-serif" font-size="${fontSize}" font-weight="800" fill="${color}">${tspans}</text>
  <g transform="translate(108 880) scale(.36)" fill="none" stroke="#B6FF3B" stroke-width="18" stroke-linecap="round" stroke-linejoin="round">
    <path d="M152 48H78C61.43 48 48 61.43 48 78v100c0 16.57 13.43 30 30 30h74"/>
    <path d="M92 84v88"/>
    <path d="M108 128h96"/>
    <path d="M170 94l34 34-34 34"/>
  </g>
  <text x="208" y="924" font-family="Arial, sans-serif" font-size="28" font-weight="800" fill="#f4f4ef">The Great Logout</text>
  <text x="208" y="956" font-family="Arial, sans-serif" font-size="23" fill="#a4aaa1">A collective social media exit</text>
  <text x="972" y="956" text-anchor="end" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#B6FF3B">thegreatlogout.org</text>
</svg>`;
}

function wrapSvgText(text, maxChars) {
  const lines = [];
  text.split("\n").forEach(rawLine => {
    const words = rawLine.trim().split(/\s+/).filter(Boolean);
    if (!words.length) {
      lines.push("");
      return;
    }

    let line = "";
    words.forEach(word => {
      const test = line ? `${line} ${word}` : word;
      if (test.length <= maxChars || !line) {
        line = test;
      } else {
        lines.push(line);
        line = word;
      }
    });
    lines.push(line);
  });
  return lines;
}

function corsResponse(body, env, status = 200, request = null) {
  const origin = request?.headers?.get("Origin") || "";
  const allowedOrigins = String(env.ALLOWED_ORIGINS || env.ALLOWED_ORIGIN || "https://www.thegreatlogout.org")
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
  const allowedOrigin = allowedOrigins.includes(origin) ? origin : allowedOrigins[0];

  const headers = {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
    "Content-Type": "application/json"
  };

  if (body === null) {
    return new Response(null, { status, headers });
  }

  return new Response(JSON.stringify(body), { status, headers });
}

function normalizeEmail(value) {
  const email = String(value || "").trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : "";
}

function cleanText(value, maxLength) {
  return String(value || "").trim().slice(0, maxLength);
}

function cleanDate(value) {
  const date = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : "";
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
