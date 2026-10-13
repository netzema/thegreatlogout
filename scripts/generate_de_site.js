const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const deDir = path.join(root, "de");
fs.mkdirSync(deDir, { recursive: true });

const site = "https://thegreatlogout.org";

function read(name) {
  return fs.readFileSync(path.join(root, name), "utf8");
}

function write(name, content) {
  fs.writeFileSync(path.join(root, name), content, "utf8");
}

function between(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  if (from < 0 || to < 0) throw new Error(`Could not extract ${start}`);
  return source.slice(from + start.length, to);
}

function ensureLanguageCss(style) {
  if (!style.includes(".language-switch")) {
    style = style.replace(
      /(\s+\.nav-cta[\s\S]*?\n\s+\})/,
      `$1

    .language-switch {
      color: var(--accent);
      font-family: var(--mono);
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }`
    );
  }

  if (style.includes(".menu-toggle")) return style;

  const menuCss = `

    .site-header .nav {
      position: relative;
    }

    .menu-toggle {
      display: none;
      width: 44px;
      height: 44px;
      align-items: center;
      justify-content: center;
      gap: 5px;
      flex-direction: column;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      color: var(--text);
      cursor: pointer;
    }

    .menu-toggle span {
      display: block;
      width: 18px;
      height: 2px;
      border-radius: 999px;
      background: currentColor;
      transition: transform 160ms ease, opacity 160ms ease;
    }

    .menu-toggle[aria-expanded="true"] span:nth-child(1) {
      transform: translateY(7px) rotate(45deg);
    }

    .menu-toggle[aria-expanded="true"] span:nth-child(2) {
      opacity: 0;
    }

    .menu-toggle[aria-expanded="true"] span:nth-child(3) {
      transform: translateY(-7px) rotate(-45deg);
    }

    @media (max-width: 900px) {
      .menu-toggle {
        display: inline-flex;
      }

      .nav-links {
        position: absolute;
        top: calc(100% + 10px);
        right: 0;
        left: auto;
        width: min(320px, calc(100vw - 40px));
        display: none;
        align-items: stretch;
        gap: 0;
        padding: 10px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(15, 17, 15, 0.98);
        box-shadow: var(--shadow, 0 24px 80px rgba(0, 0, 0, 0.45));
      }

      .site-header.is-menu-open .nav-links {
        display: grid;
      }

      .nav-links a {
        display: block;
        padding: 12px 14px;
        border-radius: 12px;
      }

      .nav-links a:hover {
        background: rgba(255,255,255,0.06);
      }

      .nav-links .nav-cta {
        margin-top: 6px;
        text-align: center;
      }
    }`;

  return style.replace(/\n\s+@media \(max-width:/, `${menuCss}\n\n    @media (max-width:`);
}

function mobileMenuButton(label = "Menu") {
  return `      <button class="menu-toggle" type="button" aria-label="${label}" aria-controls="siteNav" aria-expanded="false" data-menu-toggle>
        <span></span>
        <span></span>
        <span></span>
      </button>`;
}

function mobileMenuScript() {
  return `  <script>
    (() => {
      const header = document.querySelector(".site-header");
      const toggle = document.querySelector("[data-menu-toggle]");
      const nav = document.getElementById("siteNav");
      if (!header || !toggle || !nav) return;

      function setOpen(isOpen) {
        header.classList.toggle("is-menu-open", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
      }

      toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
      });

      nav.addEventListener("click", event => {
        if (event.target.closest("a")) setOpen(false);
      });

      document.addEventListener("keydown", event => {
        if (event.key === "Escape") setOpen(false);
      });

      window.matchMedia("(min-width: 901px)").addEventListener("change", event => {
        if (event.matches) setOpen(false);
      });
    })();
  </script>`;
}

function ensureMobileMenuMarkup(output, label = "Menu") {
  output = output.replace(/\n\s*<button class="menu-toggle"[\s\S]*?<\/button>/g, "");
  output = output.replace(/<nav class="nav-links"(?! id=)/g, '<nav class="nav-links" id="siteNav"');
  output = output.replace(/<\/nav>(\s*<\/div>\s*<\/header>)/, `</nav>\n${mobileMenuButton(label)}$1`);
  return output;
}

function ensureMobileMenuScript(output) {
  output = output.replace(/\n\s*<script>\s*\(\(\) => \{\s*const header = document\.querySelector\("\.site-header"\);[\s\S]*?<\/script>/g, "");
  return output.replace("</body>", `${mobileMenuScript()}\n</body>`);
}

function ensureAnalyticsAssets(output, prefix = "") {
  output = output
    .replace(/\n\s*<link rel="stylesheet" href="(?:\.\.\/)?assets\/analytics\.css" \/>/g, "")
    .replace(/\n\s*<script src="(?:\.\.\/)?assets\/analytics\.js"><\/script>/g, "");
  output = output.replace("</head>", `  <link rel="stylesheet" href="${prefix}assets/analytics.css" />\n</head>`);
  return output.replace("</body>", `  <script src="${prefix}assets/analytics.js"></script>\n</body>`);
}

function altLinks({ en, de }) {
  return `  <link rel="alternate" hreflang="en" href="${site}${en}" />
  <link rel="alternate" hreflang="de" href="${site}${de}" />
  <link rel="alternate" hreflang="x-default" href="${site}${en}" />`;
}

function updateHead(source, { en, de }) {
  source = source.replace(/\n  <link rel="alternate" hreflang="en"[\s\S]*?x-default" href="[^"]+" \/>\n/g, "\n");
  return source.replace(/(  <link rel="canonical" href="[^"]+" \/>\n)/, `$1${altLinks({ en, de })}\n`);
}

function updateEnglishPage(file, counterpart) {
  const source = read(file);
  const enPath = file === "index.html" ? "/" : `/${file}`;
  let output = updateHead(source, { en: enPath, de: counterpart });
  output = output.replace(/\n\s*<a class="language-switch" href="[^"]+" hreflang="de" lang="de">DE<\/a>/g, "");
  output = output.replace(/<style>([\s\S]*?)<\/style>/, (_match, style) => `<style>${ensureLanguageCss(style)}</style>`);
  const deHref = counterpart === "/de/" ? "de/" : `de/${path.basename(counterpart)}`;
  output = output.replace(
    /(<a href="index\.html#start-guide" class="nav-cta">Start<\/a>|<a href="#start-guide" class="nav-cta">Start<\/a>)/,
    `<a class="language-switch" href="${deHref}" hreflang="de" lang="de">DE</a>\n        $1`
  );
  output = ensureMobileMenuMarkup(output, "Menu");
  output = ensureMobileMenuScript(output);
  output = ensureAnalyticsAssets(output);
  write(file, output);
}

const dePostIdeas = [
  "Plattformen verdienen an meiner Aufmerksamkeit.\nIch will sie anders nutzen.",
  "Ich bereite meinen Ausstieg vor.\nWir können trotzdem in Kontakt bleiben.",
  "Ich verlasse diese Plattform.\nIn den nächsten Tagen erkläre ich warum.",
  "Ich möchte mit Freunden reden,\nohne nebenbei zu scrollen.",
  "Was beschäftigt dich,\nwenn du den Feed schließt?",
  "Ich sehe hier viele Menschen.\nMit ihnen zu sprechen fehlt mir trotzdem.",
  "Ich will meine Zeit nicht mehr\nmit endlosem Scrollen verbringen.",
  "Ich möchte Freunden zuhören,\nohne nebenbei durch den Feed zu scrollen.",
  "Ich logge mich aus,\nweil mir der Feed zu viel wird.",
  "Der Feed lernt aus deinen Klicks,\ndamit du länger bleibst.",
  "Du schuldest keiner Plattform dein Leben.",
  "Je länger wir scrollen,\ndesto mehr Werbung können sie verkaufen.",
  "Der Feed ist so gebaut,\ndass Aufhören schwerfällt.",
  "Ich bin kein Rohstoff.",
  "Ich möchte wieder lesen,\nohne immer aufs Handy zu schauen.",
  "Mein Kopf ist kein Werbeplatz.",
  "Ein paar Konzerne haben zu viel Einfluss\nauf das, was wir täglich sehen.",
  "Plattformen verdienen auch daran,\ndass wir aus Einsamkeit weiterscrollen.",
  "Der Feed macht mich oft wütend und müde.\nIch will ihn nicht länger nutzen.",
  "Ich will in Ruhe nachdenken,\nstatt nebenbei zu scrollen.",
  "Ich verlasse diese Plattform\nund möchte mit euch in Kontakt bleiben.",
  "Ich möchte wieder mehr erleben,\nohne gleich etwas darüber zu posten.",
  "Ich gehe, weil ich dieses Geschäftsmodell\nnicht länger unterstützen will.",
  "Der Algorithmus misst Reaktionen.\nEr weiß nicht, was mir guttut.",
  "Ich will selbst entscheiden,\nwelchen Themen ich meine Zeit widme.",
  "Ich will meine Zeit nicht länger\neinem endlosen Feed überlassen.",
  "Ich gehe, weil ich hier regelmäßig\nlänger bleibe, als ich will.",
  "Ich verlasse den Feed,\nnicht die Menschen.",
  "Du erreichst mich weiterhin hier: ...",
  "Plattformen verdienen daran, dass wir zurückkommen.\nOb es uns guttut, ist zweitrangig.",
  "Meine Aufmerksamkeit steht nicht zum Verkauf.",
  "Der Ausstieg ist die Botschaft.",
  "Ich logge mich aus.\nIch will meine Aufmerksamkeit anders nutzen.",
  "Ich möchte auch mal warten,\nohne sofort den Feed zu öffnen.",
  "Ich muss nicht alles mitbekommen,\nwas der Feed mir zeigt.",
  "Ich gehe, weil mir der Feed zu viel nimmt.\nWer möchte mitmachen?",
  "Sag, warum du gehst und wo man dich erreicht.\nDann log dich aus.",
  "Freundschaften brauchen keinen endlosen Feed.",
  "Das ist mein letzter Post hier.\nSo bleiben wir in Kontakt: ..."
];

function deIndexScript() {
  let script = between(read("index.html"), "<script>", "</script>");
  script = script
    .replace('const typeLineOne = "Millions logged in.";', 'const typeLineOne = "Millionen sind eingeloggt.";')
    .replace('const typeLineTwo = "Now we log out.";', 'const typeLineTwo = "Jetzt loggen wir uns aus.";')
    .replace(/const postIdeas = \[[\s\S]*?\];/, `const postIdeas = ${JSON.stringify(dePostIdeas, null, 6)};`)
    .replace('logoImage.src = "assets/the-great-logout-mark.svg";', 'logoImage.src = "../assets/the-great-logout-mark.svg";')
    .replaceAll("A collective social media exit", "Gemeinsam raus aus Social Media")
    .replaceAll("The exit is the message.", "Der Ausstieg ist die Botschaft.")
    .replace('value="en" />\n              <label for="email">Email address</label>', 'value="de" />\n              <label for="email">E-Mail-Adresse</label>')
    .replace('language: String(formData.get("language") || document.documentElement.lang || "en").trim().slice(0, 8)', 'language: String(formData.get("language") || document.documentElement.lang || "de").trim().slice(0, 8)')
    .replace('language: "en"', 'language: "de"')
    .replace('custom.textContent = "Custom text";', 'custom.textContent = "Eigener Text";')
    .replace('button.textContent = "Use this";', 'button.textContent = "Verwenden";')
    .replace('signupStatus.textContent = "Signup is not connected yet.";', 'signupStatus.textContent = "Die Anmeldung ist zurzeit nicht verfügbar. Bitte versuche es später erneut.";')
    .replace('signupStatus.textContent = "Adding you to the guide...";', 'signupStatus.textContent = "Deine Anmeldung wird verarbeitet …";')
    .replace('throw new Error(result.detail || result.error || "Signup failed.");', 'throw new Error(signupErrorMessage(result));')
    .replace('signupStatus.textContent = "You\'re in. Check your inbox for the first email.";', 'signupStatus.textContent = "Du bist angemeldet. Schau in deinem Postfach nach der ersten E-Mail.";')
    .replace('signupStatus.textContent = error.message || "Something went wrong. Please try again.";','signupStatus.textContent = error instanceof TypeError ? "Die Anmeldung konnte nicht übertragen werden. Prüfe deine Verbindung und versuche es erneut." : error.message || "Etwas ist schiefgelaufen. Bitte versuche es erneut.";');

  script = script.replace(
    /guideLength: Number\(formData\.get\("guideLength"\) \|\| 7\),\n          consent:/,
    'guideLength: Number(formData.get("guideLength") || 7),\n          language: "de",\n          consent:'
  );
  return script.trimEnd() + `
    function signupErrorMessage(result) {
      const messages = {
        "Please take a moment before submitting.": "Bitte warte einen Moment und sende die Anmeldung erneut ab.",
        "Consent is required.": "Bitte bestätige, dass du die E-Mails zum Logout-Guide erhalten möchtest.",
        "Origin not allowed": "Bitte melde dich direkt auf thegreatlogout.org für den Guide an.",
        "Invalid email address": "Bitte gib eine gültige E-Mail-Adresse ein.",
        "Invalid logout date": "Bitte prüfe das Datum für deinen Ausstieg."
      };
      if (Array.isArray(result.detail)) {
        return "Bitte prüfe deine Angaben und versuche es erneut.";
      }
      return messages[result.detail || result.error] || "Die Anmeldung ist fehlgeschlagen. Bitte versuche es später erneut.";
    }
`;
}

function deIndex() {
  const style = ensureLanguageCss(between(read("index.html"), "<style>", "</style>"));
  return `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />

  <title>The Great Logout - Gemeinsam raus aus süchtig machenden sozialen Medien.</title>
  <meta name="description" content="The Great Logout macht den Ausstieg aus süchtig machenden sozialen Medien sichtbar: Gründe posten, erreichbar bleiben, ausloggen." />
  <link rel="canonical" href="${site}/de/" />
${altLinks({ en: "/", de: "/de/" })}

  <meta property="og:title" content="The Great Logout" />
  <meta property="og:description" content="Eine öffentliche Kampagne für alle, die süchtig machende soziale Medien sichtbar verlassen wollen." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${site}/de/" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta property="og:image:secure_url" content="${site}/assets/og-image.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="The Great Logout - Sag, warum du gehst. Dann log dich aus." />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="The Great Logout" />
  <meta name="twitter:description" content="Eine öffentliche Kampagne für alle, die süchtig machende soziale Medien sichtbar verlassen wollen." />
  <meta name="twitter:image" content="${site}/assets/og-image.png" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="shortcut icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="../assets/apple-touch-icon.png" />

  <style>${style.replaceAll("assets/", "../assets/")}</style>
</head>

<body>
  <header class="site-header">
    <div class="wrap nav">
      <a class="brand" href="#top" aria-label="The Great Logout Startseite">
        <span class="brand-mark" aria-hidden="true">
          <img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" />
        </span>
        <span>The Great Logout</span>
      </a>

      <nav class="nav-links" aria-label="Hauptnavigation">
        <a href="#how">So geht es</a>
        <a href="#why">Warum?</a>
        <a href="#generator">Post-Generator</a>
        <a href="#guide">7-Tage-Guide</a>
        <a href="#support">Unterstützen</a>
        <a class="language-switch" href="../" hreflang="en" lang="en">EN</a>
        <a href="#start-guide" class="nav-cta">Start</a>
      </nav>
    </div>
  </header>

  <main id="top">
    <section class="hero">
      <div class="wrap hero-grid">
        <div>
          <div class="eyebrow">Eine Kampagne für den sichtbaren Social-Media-Ausstieg</div>
          <h1>Verlass Social Media. Sag, warum.</h1>

          <p class="hero-copy">
            The Great Logout hilft dir, süchtig machende soziale Medien bewusst und sichtbar zu verlassen. <strong>Erkläre ein bis sieben Tage lang in kurzen Posts, warum du gehst.</strong> Sag, wo man dich weiterhin erreicht, und logge dich anschließend aus. So können andere deine Entscheidung nachvollziehen und selbst einen Ausstieg erwägen.
          </p>

          <div class="button-row">
            <a class="btn btn-primary" href="#guide">7-Tage-Guide starten</a>
            <a class="btn btn-secondary" href="#generator">Post erstellen</a>
          </div>

          <p class="campaign-note">
            <strong>Dein Ausstieg ist ein öffentliches Nein zu diesem Geschäftsmodell.</strong> Indem du deine Gründe teilst, machst du deine Entscheidung auch für andere sichtbar.
          </p>
        </div>

        <aside class="campaign-card" aria-label="The Great Logout in drei Schritten">
          <div class="campaign-top">
            <span>/logout/sequence</span>
            <span class="mini-mark" aria-hidden="true">
              <img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" />
            </span>
          </div>
          <div class="campaign-body">
            <div class="type-panel" aria-label="Kampagnenbotschaft">
              <div class="type-label">/public-message/final-post.txt</div>
              <span class="type-line" id="typeLineOne"></span>
              <span class="type-line" id="typeLineTwo"></span>
              <span class="cursor" aria-hidden="true">█</span>
            </div>

            <ol class="logout-formula">
              <li class="formula-step">
                <span>Tag 1-7</span>
                <div>
                  <strong>Teile deine Gründe.</strong>
                  <p>Schreib jeden Tag kurz über einen Grund für deinen Ausstieg. Deine eigenen Worte reichen.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Vor dem Ausstieg</span>
                <div>
                  <strong>Bleib erreichbar.</strong>
                  <p>Sag, wie man dich ohne die Plattform erreicht: etwa per E-Mail, Telefon oder Messenger. Ihr könnt euch auch persönlich verabreden.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Letzter Post</span>
                <div>
                  <strong>Dann log dich aus.</strong>
                  <p>Logge dich aus und lösche die Apps. Wenn du möchtest, deaktiviere auch deine Accounts.</p>
                </div>
              </li>
            </ol>

            <div class="mobile-sequence-cta">
              <a class="btn btn-primary" href="#guide">Heute starten</a>
            </div>
          </div>
        </aside>
      </div>
    </section>

    <section id="how">
      <div class="wrap">
        <div class="section-head">
          <div>
            <div class="kicker">So geht es</div>
            <h2>Ein einfacher Plan für einen sichtbaren Ausstieg.</h2>
          </div>
        </div>

        <div class="steps">
          <article class="step"><div><h3>Wähle 1, 3 oder 7 Tage.</h3><p>Entscheide, wie viele Tage du vor dem Ausstieg posten möchtest. In sieben Tagen kannst du verschiedene Gründe erklären und Menschen erreichen, die nicht täglich mitlesen.</p></div></article>
          <article class="step"><div><h3>Teile jeden Tag einen Grund.</h3><p>Beschreibe, warum du gehst. Das kann eine Erfahrung aus deinem Alltag sein oder Kritik daran, wie die Plattform mit deiner Aufmerksamkeit Geld verdient.</p></div></article>
          <article class="step"><div><h3>Sag, wo man dich erreicht.</h3><p>Tausche mit den Menschen, die dir wichtig sind, Kontaktdaten aus. Sag auch in deinen Posts, wie man dich nach dem Ausstieg erreicht.</p></div></article>
          <article class="step"><div><h3>Lösch die Apps oder deaktiviere deine Accounts.</h3><p>Logge dich nach deinem letzten Post aus. Wenn die App nicht mehr auf deinem Handy ist, öffnest du sie auch nicht nebenbei aus Gewohnheit.</p></div></article>
          <article class="step"><div><h3>Sprich über deine Entscheidung.</h3><p>Wenn jemand nachfragt, erzähle von deinen Gründen und Erfahrungen. Das kann anderen helfen, ihren eigenen Ausstieg vorzubereiten.</p></div></article>
        </div>

        <div class="how-cta">
          <div>
            <h3>Bereit für den ersten Schritt?</h3>
            <p>Der E-Mail-Guide begleitet dich mit einer Aufgabe pro Tag bis zum Ausstieg. Danach erhältst du in größeren Abständen weitere E-Mails mit Fragen zu deinen Erfahrungen und Hintergründen zur Kampagne.</p>
          </div>
          <a class="btn btn-primary" href="#start-guide">Heute starten</a>
        </div>
      </div>
    </section>

    <section id="why">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Mehr als Bildschirmzeit</div><h2>Warum Ausloggen ein öffentliches Nein sein kann.</h2></div></div>
        <div class="why-case">
          <p><strong>The Great Logout ist eine öffentliche Absage an das Geschäftsmodell süchtig machender Plattformen.</strong> Sie sind im Alltag so selbstverständlich geworden, dass ihre Macht oft kaum noch auffällt. Mit einem sichtbaren Ausstieg stellst du diese Selbstverständlichkeit infrage.</p>
          <p>Der Essay erklärt in 13 Abschnitten, wie Plattformen Aufmerksamkeit binden und damit Geld verdienen. Er zeigt, was ihre Macht für Beziehungen, Kultur und politische Debatten bedeutet – und warum ein Ausstieg mehr sein kann als eine persönliche Entscheidung für weniger Bildschirmzeit.</p>
          <p>Wer aussteigt, entzieht Plattformen Aufmerksamkeit, von der sie wirtschaftlich leben. Damit widersprichst du einem Geschäftsmodell, das auch Wut, Einsamkeit, Unsicherheit und Gewohnheit gewinnbringend nutzt.</p>
          <div class="button-row compact-row">
            <a class="btn btn-secondary" href="essay.html">Die ausführliche Begründung lesen</a>
            <a class="btn btn-primary" href="#generator">Post-Ideen ansehen</a>
          </div>
        </div>
      </div>
    </section>

    <section id="generator">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Post-Generator</div><h2>Mach deinen Ausstieg sichtbar.</h2></div></div>
        <p>Du findest hier persönliche Abschiedsposts und allgemeine Kampagnenbotschaften. Wähle einen Vorschlag, der zu dir passt, und ergänze bei Bedarf deine Gründe und Kontakthinweise.</p>
        <div class="quote-carousel" id="quoteCarousel" aria-label="Beispielposts zum Ausstieg"></div>
        <div class="generator-panel">
          <div class="generator-controls">
            <div class="control-grid">
              <div class="field"><label for="postPreset">Post-Idee</label><select id="postPreset"></select></div>
              <div class="field"><label for="postText">Text bearbeiten</label><textarea id="postText">Meine Aufmerksamkeit steht nicht zum Verkauf.</textarea></div>
              <div class="field">
                <label for="postFormat">Format</label>
                <select id="postFormat">
                  <option value="instagram-post">Instagram Post - 1080 x 1080</option>
                  <option value="instagram-story">Instagram Story - 1080 x 1920</option>
                  <option value="instagram-reel">Instagram Reel - 1080 x 1920</option>
                  <option value="tiktok">TikTok - 1080 x 1920</option>
                  <option value="cover">Cover-Bild - 1500 x 500</option>
                </select>
              </div>
              <div class="color-options" aria-label="Schriftfarbe">
                <label title="Weißer Text" aria-label="Weißer Text"><input type="radio" name="postColor" value="#f4f4ef" checked /><span class="swatch swatch-white"></span></label>
                <label title="Grüner Text" aria-label="Grüner Text"><input type="radio" name="postColor" value="#B6FF3B" /><span class="swatch swatch-green"></span></label>
              </div>
              <div class="download-row" aria-label="Generierten Post herunterladen">
                <button type="button" data-download="png">PNG</button>
                <button type="button" data-download="jpg">JPG</button>
                <button type="button" data-download="svg">SVG</button>
                <button type="button" data-download="pdf">PDF</button>
              </div>
            </div>
          </div>
          <div class="generator-preview"><canvas id="postCanvas" width="1080" height="1080" aria-label="Vorschau des generierten Social-Media-Posts"></canvas></div>
        </div>
      </div>
    </section>

    <section id="guide">
      <div class="wrap">
        <div class="guide-panel">
          <div>
            <div class="kicker">7-Tage-Guide</div>
            <h2>Bereite deinen Ausstieg in sieben Tagen vor.</h2>
            <p class="lead">Du erhältst jeden Tag eine E-Mail mit einer konkreten Aufgabe und Vorschlägen für deinen Post. Übernimm, was zu dir passt, oder schreibe mit eigenen Worten. Am Ende veröffentlichst du deine Abschiedsnachricht und loggst dich aus.</p>
            <div class="guide-days">
              <article class="guide-day"><span>Tag 0</span><div><h3>Den Ausstieg vorbereiten</h3><p>Kontakte sichern, letzten Tag festlegen und entscheiden, wo man dich künftig erreicht.</p></div></article>
              <article class="guide-day"><span>Tag 1</span><div><h3>Warum ich gehe</h3><p>Kündige deinen Ausstieg an und erkläre, warum du dich dafür entschieden hast.</p></div></article>
              <article class="guide-day"><span>Tag 2</span><div><h3>Was der Feed mit mir macht</h3><p>Beschreibe eine Situation, in der du länger scrollst, als du eigentlich möchtest.</p></div></article>
              <article class="guide-day"><span>Tag 3</span><div><h3>Wofür ich mehr Zeit möchte</h3><p>Sag, was dir wichtig ist – etwa ungestört zu lesen oder bei Gesprächen weniger abgelenkt zu sein.</p></div></article>
              <article class="guide-day"><span>Tag 4</span><div><h3>Warum Big Tech zu viel Macht hat</h3><p>Erkläre, warum wenige Konzerne zu viel Einfluss darauf haben, was wir täglich sehen.</p></div></article>
              <article class="guide-day"><span>Tag 5</span><div><h3>Wo man mich findet</h3><p>Sag, wie du ohne die Plattform erreichbar bist, und tausche bei Bedarf Kontaktdaten aus.</p></div></article>
              <article class="guide-day"><span>Tag 6</span><div><h3>Andere einladen</h3><p>Lade andere zum Mitmachen ein, ohne ihnen vorzuwerfen, dass sie die Plattform nutzen.</p></div></article>
              <article class="guide-day"><span>Tag 7</span><div><h3>Abschiedspost und ausloggen</h3><p>Veröffentliche deinen letzten Post, logge dich aus und lösche die Apps.</p></div></article>
            </div>
          </div>

          <aside class="signup-card guide-signup" id="start-guide" aria-labelledby="signup-title">
            <h3 id="signup-title">Starte deinen Ausstieg</h3>
            <p>Erkläre ein bis sieben Tage lang, warum du gehst, und sag, wo man dich erreicht. Dann logge dich aus.</p>
            <p>Der Guide umfasst 25 E-Mails über rund 15 Monate. Du kannst dich jederzeit über den Link in jeder E-Mail abmelden.</p>
            <p class="signup-link">Brauchst du zuerst eine Formulierung? <a href="#generator">Zum Post-Generator.</a></p>
            <form class="signup-form" id="guideSignupForm" data-endpoint="/api/guide/subscribe">
              <input type="hidden" name="language" value="de" />
              <div aria-hidden="true" style="position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden;">
                <label for="website">Website</label>
                <input id="website" name="website" type="text" tabindex="-1" autocomplete="off" />
              </div>
              <label for="email">E-Mail-Adresse</label>
              <input id="email" name="email" type="email" placeholder="du@example.com" autocomplete="email" required />
              <label for="firstName">Vorname <span>(optional)</span></label>
              <input id="firstName" name="firstName" type="text" autocomplete="given-name" />
              <label for="logoutDate">Geplanter Tag für deinen Ausstieg <span>(optional)</span></label>
              <input id="logoutDate" name="logoutDate" type="date" />
              <label class="checkbox-field">
                <input id="emailConsent" name="consent" type="checkbox" required />
                <span>Ich möchte den Logout-Guide und die späteren Begleit-E-Mails erhalten. Kein Spam.</span>
              </label>
              <button type="submit">7-Tage-Guide starten</button>
              <p class="form-note" id="signupStatus" aria-live="polite"></p>
            </form>
          </aside>
        </div>
      </div>
    </section>

    <section id="manifesto">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Manifest</div><h2>Wir verlassen den Feed, nicht einander.</h2></div></div>
        <div class="manifesto"><p>Wir gehen, weil Plattformen daran verdienen, uns möglichst lange zu beschäftigen, unser Verhalten auszuwerten und uns immer wieder zurückzuholen. Auch Empörung und Unsicherheit werden dabei gewinnbringend genutzt. Unsere Kritik richtet sich gegen dieses Geschäftsmodell. Die Arbeit von Kreativen und die Gemeinschaften, die auf den Plattformen entstanden sind, verdienen Unterstützung. Dafür wollen wir Wege finden, die ohne süchtig machende Feeds auskommen.</p></div>
      </div>
    </section>

    <section id="support">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Unterstützen</div><h2>Hilf mit, die Kampagne unabhängig zu halten.</h2></div></div>
        <div class="support-grid">
          <div class="support-copy">
            <p>The Great Logout soll frei zugänglich und kostenlos nutzbar bleiben. Du kannst die Seite teilen, anderen den Guide empfehlen oder mit einem Beitrag helfen, die laufenden Kosten zu decken.</p>
            <div class="button-row compact-row"><a class="btn btn-primary" href="https://ko-fi.com/thegreatlogout" target="_blank" rel="noopener">Kampagne unterstützen</a></div>
          </div>
          <aside class="origin-card">
            <p><strong>The Great Logout wurde von <a href="https://www.danielnetzl.at" target="_blank" rel="noopener">Daniel Netzl</a> initiiert, einem österreichischen Data Scientist, der sich mit den sozialen, politischen und psychologischen Folgen süchtig machenden Plattformdesigns beschäftigt.</strong></p>
            <p>Die Kampagne ist unabhängig und nicht mit Instagram, TikTok, Meta, X oder einer anderen Social-Media-Plattform verbunden.</p>
          </aside>
        </div>
      </div>
    </section>
  </main>

  <footer class="footer">
    <div class="wrap footer-inner">
      <div>© 2026 The Great Logout</div>
      <nav class="footer-links" aria-label="Navigation am Seitenende">
        <a href="#how">So geht es</a>
        <a href="#guide">7-Tage-Guide</a>
        <a href="#generator">Post-Generator</a>
        <a href="essay.html">Essay</a>
        <a href="#support">Unterstützen</a>
        <a href="imprint.html">Impressum</a>
        <a href="privacy.html">Datenschutz</a>
        <a href="../" hreflang="en" lang="en">English</a>
        <button class="privacy-settings" type="button" data-analytics-settings>Datenschutz-Einstellungen</button>
      </nav>
    </div>
  </footer>

  <script>${deIndexScript()}</script>
</body>
</html>
`;
}

function legalStyle(sourceName) {
  return ensureLanguageCss(between(read(sourceName), "<style>", "</style>")).replaceAll("assets/", "../assets/");
}

function deEssay() {
  const style = legalStyle("essay.html");
  return `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>13 Gründe, dich auszuloggen | The Great Logout</title>
  <meta name="description" content="Ein Essay über süchtig machende Feeds, die Macht großer Tech-Konzerne, Aufmerksamkeit, Konsumdruck, politische Passivität und den sichtbaren Social-Media-Ausstieg." />
  <link rel="canonical" href="${site}/de/essay.html" />
${altLinks({ en: "/essay.html", de: "/de/essay.html" })}
  <meta property="og:title" content="13 Gründe, dich auszuloggen" />
  <meta property="og:description" content="Warum The Great Logout existiert und warum ein sichtbarer Ausstieg aus Social Media ein öffentliches Signal sein kann." />
  <meta property="og:type" content="article" />
  <meta property="og:url" content="${site}/de/essay.html" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="13 Gründe, dich auszuloggen" />
  <meta name="twitter:description" content="Warum ein sichtbarer Ausstieg aus Social Media ein öffentliches Signal sein kann." />
  <meta name="twitter:image" content="${site}/assets/og-image.png" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="../assets/apple-touch-icon.png" />
  <style>${style}</style>
</head>
<body>
  <header class="site-header"><div class="wrap nav"><a class="brand" href="index.html" aria-label="The Great Logout Startseite"><img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" /><span>The Great Logout</span></a><nav class="nav-links" aria-label="Hauptnavigation"><a href="index.html#how">So geht es</a><a href="index.html#why">Warum?</a><a href="index.html#generator">Post-Generator</a><a href="index.html#guide">7-Tage-Guide</a><a href="index.html#support">Unterstützen</a><a class="language-switch" href="../essay.html" hreflang="en" lang="en">EN</a><a href="index.html#start-guide" class="nav-cta">Start</a></nav></div></header>
  <main>
    <section class="hero"><div class="wrap"><div class="kicker">Essay</div><h1>13 Gründe, dich auszuloggen</h1><p class="intro">Der Feed beeinflusst, worauf wir achten, worüber wir streiten und was wir kaufen möchten. Dahinter stehen Unternehmen, die mit unserer Aufmerksamkeit Geld verdienen. The Great Logout ruft dazu auf, ihnen diese Aufmerksamkeit bewusst und öffentlich zu entziehen.</p><div class="meta" aria-label="Artikeldetails"><span>Von <a href="https://www.danielnetzl.at" target="_blank" rel="noopener">Daniel Netzl</a></span><span>Februar 2025</span><span>Für The Great Logout aktualisiert</span></div></div></section>
    <article><div class="wrap essay">
      <p>Bei Alkohol, Zigaretten, Glücksspiel oder Medikamenten wissen wir, dass Abhängigkeit mehr ist als eine Frage der Willenskraft. Deshalb gibt es Warnhinweise, Regeln, Altersgrenzen und Unterstützung.</p>
      <p>Auch soziale Plattformen können abhängig machen. Wir tragen sie ständig bei uns. Der Feed bietet immer einen weiteren Clip, einen Streit, einen Vergleich oder ein Angebot. Zugleich wird er daran angepasst, worauf wir reagieren und wie lange wir bleiben.</p>
      <p>Weil das im Alltag so gewöhnlich geworden ist, fällt leicht aus dem Blick, wie gezielt diese Angebote unsere Aufmerksamkeit beanspruchen.</p>
      <h2>1. Mit deiner Aufmerksamkeit wird Geld verdient</h2>
      <p>Aufmerksamkeit ist die Voraussetzung dafür, dass du jemandem zuhören, etwas lernen oder dich in eine Aufgabe vertiefen kannst. Du brauchst sie, um Beziehungen zu pflegen, einen Verlust zu verarbeiten oder gemeinsam mit anderen etwas zu verändern.</p>
      <p>Die großen Plattformen behandeln diese Aufmerksamkeit als wirtschaftlich verwertbaren Rohstoff. Sie messen, wo du beim Scrollen innehältst, welche Beiträge du kommentierst und was du spätabends noch anschaust. Aus solchen Reaktionen lernt das System, womit es dich länger beschäftigen kann.</p>
      <p>Das lässt sich nicht allein als persönliche Gewohnheit erklären. Eine Gewohnheit wiederholst du selbst; der Feed passt sich zusätzlich an dein Verhalten an, um möglichst viel daran zu verdienen.</p>
      <h2>2. Der Feed soll dich immer wieder zurückholen</h2>
      <p>Auf TikTok, Instagram, YouTube, Facebook, X und ähnlichen Plattformen begegnen sich Menschen. Doch die Unternehmen stellen dafür keinen neutralen Treffpunkt bereit. Sie bestimmen durch ihre Sortierung, welche Beiträge du siehst, was sich wiederholt und was kaum sichtbar wird.</p>
      <p>Ihr Geschäftsmodell belohnt es, wenn Menschen lange zuschauen, reagieren und häufig zurückkommen. Dabei entstehen Daten, mit denen sich Werbung gezielter ausspielen lässt. Je genauer sich Menschen für Werbung ansprechen lassen, desto wertvoller wird ihre Aufmerksamkeit für das Unternehmen.</p>
      <p>Vielleicht kennst du die Situation: Du öffnest eine App, um kurz etwas nachzusehen. Zwanzig Minuten später bist du immer noch da, ärgerst dich über einen Beitrag oder möchtest etwas kaufen. Nichts davon hattest du vor, als du das Handy in die Hand genommen hast.</p>
      <div class="pull">Wenige Konzerne bestimmen mit, was Milliarden Menschen von der Welt sehen. Das ist zu viel Macht.</div>
      <h2>3. Big Tech bestimmt das öffentliche Leben mit</h2>
      <p>Eine Handvoll Konzerne beeinflusst, welche Nachrichten, politischen Positionen und Lebensweisen Milliarden Menschen sehen. Das betrifft Wahlen ebenso wie Musik, Mode, Humor und Schönheitsideale. Was im eigenen Feed häufig vorkommt, kann leicht wie das wirken, was alle denken.</p>
      <p>Diese Macht ist politisch und kulturell. Wenn eine Plattform bestimmte Stimmen hervorhebt, andere kaum zeigt oder einen Streit immer weiter verbreitet, verändert sie die öffentliche Debatte. Aufmerksamkeit wird dabei nach wirtschaftlichen Interessen verteilt.</p>
      <p>Wir würden es problematisch finden, wenn ein Unternehmen die Titelseiten sämtlicher Zeitungen und die Debatten auf allen öffentlichen Plätzen kontrollierte. Bei sozialen Plattformen haben wir eine ähnliche Machtkonzentration weitgehend hingenommen, weil sie als Unterhaltung und bequeme Kommunikation in unseren Alltag kam.</p>
      <h2>4. Empörung wird belohnt</h2>
      <p>Algorithmen müssen weder jede Lüge noch jeden Konflikt erfinden. Es reicht, Beiträge häufiger zu zeigen, auf die Menschen stark reagieren. Wut, unerschütterliche Gewissheit und die Verachtung anderer können sich so eher durchsetzen als sorgfältige Einordnungen.</p>
      <p>Wenn jede Person immer wieder andere Ausschnitte der Welt sieht, passend zu ihren Vorlieben und Befürchtungen, wird Verständigung schwieriger. Dann streiten Menschen nicht nur darüber, wie ein Ereignis zu bewerten ist, sondern auch darüber, was überhaupt passiert ist.</p>
      <p>Das kann die Verbreitung von Falschinformationen und radikalen Positionen begünstigen. Für die Plattform kann ein eskalierender Streit erfolgreich sein, solange er Menschen zum Reagieren und Weiterschauen bringt. Für die öffentliche Debatte ist er deshalb noch lange kein Gewinn.</p>
      <h2>5. Der Feed füllt jede freie Minute</h2>
      <p>Beim Warten auf den Zug, beim Gehen oder in einer Schlange gibt es oft wenig zu tun. Solche Momente können langweilig und unangenehm sein. Sie lassen aber auch Zeit, einem Gedanken nachzugehen, ein Gespräch zu verarbeiten oder einen Plan zu fassen.</p>
      <p>Der Feed bietet für jede dieser Pausen sofort neue Reize. Daraus kann die Gewohnheit werden, schon bei der kleinsten Unterbrechung zum Handy zu greifen. Für Gedanken, die erst allmählich entstehen, bleibt dann wenig Zeit.</p>
      <p>Wenn alle paar Sekunden etwas Neues erscheint, kann der Alltag daneben langsam wirken. Doch freie Zeit muss weder ständig unterhalten noch etwas hervorbringen, um einen Wert zu haben.</p>
      <h2>6. Der ständige Vergleich wird zum Alltag</h2>
      <p>Im Feed folgen Bilder von Körpern, Wohnungen, Beziehungen, Reisen und Karrieren aufeinander. Irgendjemand scheint immer schöner, erfolgreicher oder zufriedener zu sein. Du vergleichst deinen ganzen Alltag mit ausgewählten Momenten aus vielen anderen Leben.</p>
      <p>Zu wissen, dass ein Foto gestellt oder bearbeitet ist, schützt nicht unbedingt vor diesem Vergleich. Was du immer wieder siehst, kann trotzdem beeinflussen, was du von dir und deinem Leben erwartest.</p>
      <p>Wer davon erschöpft ist, ist nicht einfach zu empfindlich. Der Druck entsteht auch durch ein Angebot, das unablässig neue Maßstäbe liefert und zugleich passende Produkte gegen das vermeintliche Ungenügen anbietet.</p>
      <h2>7. Einsamkeit ist profitabel</h2>
      <p>Plattformen versprechen Verbindung, und viele Menschen finden dort wichtige Freundschaften und Gemeinschaften. Trotzdem kann man Hunderte Beiträge sehen, den ganzen Tag erreichbar sein und jemanden vermissen, der wirklich zuhört.</p>
      <p>Die Hoffnung auf ein Gespräch, die Angst vor einer verpassten Einladung und das Gefühl, ohne die Plattform aus dem Blick zu geraten, können Menschen immer wieder zum Scrollen bringen. Davon profitiert das Unternehmen auch dann, wenn die erhoffte Nähe ausbleibt.</p>
      <p>Es geht deshalb darum, Beziehungen zu erhalten und unabhängiger von der Plattform zu machen. Ein Anruf, direkte Nachrichten oder regelmäßige Treffen können Kontakt ermöglichen, ohne dass du dafür ständig einen Feed verfolgen musst.</p>
      <h2>8. Politische Reaktionen ersetzen noch kein Handeln</h2>
      <p>Ein Like kann Zustimmung ausdrücken, ein geteilter Beitrag auf Unrecht aufmerksam machen und ein Kommentar eine wichtige Frage aufwerfen. Das kann helfen, etwa wenn Menschen dadurch eine Initiative finden und sich ihr anschließen.</p>
      <p>Es kann aber auch das Gefühl entstehen, bereits genug getan zu haben. Wir sehen Unrecht, reagieren darauf, diskutieren und scrollen weiter. Die Plattform zählt eine weitere Interaktion; am Problem hat sich dadurch noch nichts geändert.</p>
      <p>Politisches Handeln braucht häufig Zeit, die im schnellen Wechsel der Beiträge fehlt: für ein längeres Gespräch, gemeinsame Planung oder die Arbeit in einer Initiative. Die dauernde Aufforderung zur nächsten Reaktion kann diese Arbeit verdrängen.</p>
      <div class="pull">Eine Gesellschaft kann den ganzen Tag empört sein und trotzdem stillstehen.</div>
      <h2>9. Kultur gerät unter den Druck der Reichweite</h2>
      <p>Der Feed begünstigt Inhalte, die sich schnell verbreiten. Dadurch kann leicht der Eindruck entstehen, dass das meistgeteilte Video, der eingängigste Satz oder die lauteste Meinung auch am wichtigsten sei.</p>
      <p>Das beeinflusst Kunst, Sprache, Humor, Musik und politische Debatten. Wer sichtbar bleiben möchte, passt sich womöglich immer stärker an das an, was die Plattform belohnt. Schwierige Gedanken werden verkürzt, Eigenheiten zur vermarktbaren Marke und persönliche Erfahrungen zum nächsten Beitrag.</p>
      <p>Kultur braucht auch Geduld, Erinnerung und die Auseinandersetzung mit etwas, das sich nicht sofort erschließt. Dafür braucht es Orte, an denen ein Werk oder ein Gedanke nicht schon nach Sekunden an seiner Reichweite gemessen wird.</p>
      <h2>10. Zuschauen allein verändert wenig</h2>
      <p>Jede Person erhält im Feed eine anders sortierte Auswahl der Welt, die möglichst viele Reaktionen auslösen soll. Gemeinsame Probleme können dadurch unübersichtlich und kaum beeinflussbar wirken. Zwischen Krisenmeldungen bietet der nächste Beitrag Ablenkung, aber noch keine Möglichkeit zu handeln.</p>
      <p>Klimakrise, Ungleichheit, Krieg und die Gefährdung demokratischer Strukturen verlangen längerfristige Aufmerksamkeit. Wir brauchen Menschen, die sich zusammensetzen, widersprechen, planen, protestieren, füreinander sorgen und Alternativen aufbauen.</p>
      <p>Ausloggen ist dafür kein vollständiges politisches Programm. Es kann aber Zeit und Kraft freimachen, um sich gemeinsam mit anderen einzusetzen: in Schulen, am Arbeitsplatz, in der Nachbarschaft oder in einer Initiative. Die Entscheidung für den Ausstieg bekommt gesellschaftliche Bedeutung, wenn daraus auch gemeinsame Handlungsmöglichkeiten entstehen.</p>
      <h2>11. Der Feed weckt immer neue Kaufwünsche</h2>
      <p>Die Plattformen beeinflussen auch, was wir uns wünschen. Werbung und Beiträge legen nahe, dass das bessere Leben nur eine Reise, ein neues Gerät oder die richtige Kleidung entfernt sei. Sobald ein Wunsch erfüllt ist, erscheint das nächste Angebot.</p>
      <p>Das hat Folgen: mehr Konsum, ständigen Vergleich, mitunter Schulden und ökologische Schäden. Ein Trend, der nach zwei Wochen vorbei ist, kann Produktion, Flüge, Transporte, Verpackungen und Abfall verursachen, die viel länger nachwirken.</p>
      <p>Für dieses Geschäftsmodell müssen Menschen nicht zufrieden sein. Es reicht, wenn immer neue Wünsche sie zum Zurückkommen und Kaufen bewegen.</p>
      <h2>12. Beziehungen werden von Plattformen abhängig</h2>
      <p>Viele bleiben, weil sie befürchten, beim Gehen wichtige Kontakte zu verlieren. Das ist nachvollziehbar. Freundschaften, Familien, Kunstschaffende, Veranstaltende, Kundschaft und Gemeinschaften organisieren einen Teil ihres Austauschs über diese Plattformen.</p>
      <p>Doch lohnt es sich, stundenlang den Feed zu verfolgen, um gelegentlich mit einem bestimmten Menschen zu sprechen? Wenn du eine App wegen einer Nachricht öffnest und dann bei ganz anderen Beiträgen hängen bleibst, nutzt die Plattform eure Beziehung, um dich länger zu beschäftigen.</p>
      <p>Überlegt deshalb, wie ihr ohne den Feed in Verbindung bleibt. Tauscht E-Mail-Adressen oder Telefonnummern aus, schreibt euch über Signal oder verabredet euch. Für öffentliche Neuigkeiten können eine Website oder ein Newsletter passen. Nicht jeder Kontakt lässt sich ohne Aufwand verlagern, aber ihr könnt mit den wichtigsten anfangen.</p>
      <h2>13. Ein sichtbarer Ausstieg kann andere ermutigen</h2>
      <p>Wenn du ohne Erklärung gehst, fällt das im laufenden Feed womöglich kaum auf. Ein öffentlicher Abschied macht dagegen deine Gründe sichtbar.</p>
      <p>Erkläre ein bis sieben Tage lang in kurzen Posts, warum du die Plattform verlässt. So sehen andere einen Menschen, der sich bewusst gegen dieses Geschäftsmodell entscheidet. Der Ausstieg wird als öffentliche Weigerung erkennbar und muss nicht wie ein heimliches Scheitern an mangelnder Disziplin erscheinen.</p>
      <p>Du musst dafür kein perfektes Argument haben und nicht alle überzeugen. Teile deine Gründe, sag, wo man dich weiterhin erreicht, und logge dich anschließend aus. Andere können daran anknüpfen, auch wenn sie noch nicht selbst gehen.</p>
      <div class="action-box"><h2>Der Ausstieg ist die Botschaft</h2><p>The Great Logout richtet sich gegen Plattformen, die Abhängigkeit, Empörung, Überwachung, Einsamkeit und Unsicherheit gewinnbringend nutzen. Wir wollen das Internet nutzen können, ohne dieses Geschäftsmodell ständig mit unserer Aufmerksamkeit zu unterstützen.</p><p>Wenn du aussteigen möchtest, kannst du mit dem Generator einen Post erstellen oder dich vom E-Mail-Guide begleiten lassen. Mit einem Beitrag hilfst du außerdem, die Kampagne unabhängig zu halten.</p><div class="button-row"><a class="btn btn-primary" href="index.html#guide">Ausstieg vorbereiten</a><a class="btn btn-secondary" href="index.html#generator">Post erstellen</a><a class="btn btn-secondary" href="https://ko-fi.com/thegreatlogout" target="_blank" rel="noopener">Kampagne unterstützen</a></div></div>
    </div></article>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="imprint.html">Impressum</a> &middot; <a href="privacy.html">Datenschutz</a> &middot; <button class="privacy-settings" type="button" data-analytics-settings>Datenschutz-Einstellungen</button> &middot; <a href="../essay.html" hreflang="en" lang="en">English</a></p></div></footer>
</body>
</html>
`;
}

function dePrivacy() {
  const style = legalStyle("privacy.html");
  return `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Datenschutzerklärung | The Great Logout</title>
  <meta name="description" content="Datenschutzerklärung von The Great Logout: E-Mail-Guide, Post-Generator, Dienstleister und Kontakt." />
  <link rel="canonical" href="${site}/de/privacy.html" />
${altLinks({ en: "/privacy.html", de: "/de/privacy.html" })}
  <meta property="og:title" content="Datenschutzerklärung | The Great Logout" />
  <meta property="og:description" content="Datenschutzerklärung für The Great Logout." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${site}/de/privacy.html" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Datenschutzerklärung | The Great Logout" />
  <meta name="twitter:description" content="Datenschutzerklärung für The Great Logout." />
  <meta name="twitter:image" content="${site}/assets/og-image.png" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="../assets/apple-touch-icon.png" />
  <style>${style}</style>
</head>
<body>
  <header class="site-header"><div class="wrap nav"><a class="brand" href="index.html" aria-label="The Great Logout Startseite"><img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" /><span>The Great Logout</span></a><nav class="nav-links" aria-label="Hauptnavigation"><a href="index.html#how">So geht es</a><a href="index.html#why">Warum?</a><a href="index.html#generator">Post-Generator</a><a href="index.html#support">Unterstützen</a><a class="language-switch" href="../privacy.html" hreflang="en" lang="en">EN</a><a href="index.html#start-guide" class="nav-cta">Start</a></nav></div></header>
  <main>
    <section class="hero"><div class="wrap"><div class="kicker">Datenschutz</div><h1>Datenschutzerklärung</h1></div></section>
    <section class="wrap legal" aria-label="Datenschutzerklärung">
      <p class="muted">Zuletzt aktualisiert: 10. Oktober 2026</p>
      <div class="legal-card"><p><strong>Kurzfassung:</strong> The Great Logout läuft auf unserem eigenen Server. Der Post-Generator arbeitet in deinem Browser. Mit deiner Einwilligung nutzen wir eine datensparsame Website-Statistik auf demselben Server. Wir verwenden keine Werbetracker und kein Profiling.</p></div>
      <h2>Verantwortlicher</h2><p>Verantwortlich für diese Website ist:</p><p>The Great Logout<br />Eine Kampagne von Daniel Netzl<br />Landstraße 47<br />2464 Göttlesbrunn<br />Österreich<br /><a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a></p>
      <h2>Welche Daten wir erheben</h2><p>Wenn du dich für den E-Mail-Guide anmeldest, verarbeiten wir die Daten, die du selbst einträgst:</p><ul><li>E-Mail-Adresse</li><li>optional Vorname</li><li>optional geplantes Logout-Datum</li><li>gewählte Dauer des Guides</li><li>Einwilligung zum Erhalt des Guides</li></ul><p>Für Versand und Abmeldung speichern wir außerdem, soweit erforderlich, technische Informationen wie Kennungen für die Abmeldung, Anmeldezeitpunkt, Abmeldezeitpunkt, Versandstatus, Zustell-IDs und Fehlermeldungen.</p>
      <h2>Wofür wir diese Daten verwenden</h2><p>Wir verwenden diese Daten, um dir den Logout-Guide, spätere Begleit-E-Mails und verwandte Kampagnen-E-Mails zu schicken, die du angefordert hast. Rechtsgrundlage ist deine Einwilligung nach Art. 6 Abs. 1 lit. a DSGVO.</p><p>Begrenzte technische Daten können außerdem verarbeitet werden, um Website und E-Mail-System zu betreiben, abzusichern und zu verbessern. Rechtsgrundlage ist unser berechtigtes Interesse nach Art. 6 Abs. 1 lit. f DSGVO.</p>
      <h2>E-Mail-Guide und Abmeldung</h2><p>Du kannst dich jederzeit über den Abmeldelink in jeder E-Mail vom Guide abmelden. Alternativ erreichst du uns unter <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a>.</p><p>Nach einer Abmeldung senden wir keine Guide-E-Mails mehr. Eine begrenzte Dokumentation der Abmeldung kann gespeichert bleiben, damit wir keine weiteren E-Mails senden und die Einwilligungshistorie nachvollziehen können.</p>
      <h2>Post-Generator</h2><p>Der Post-Generator läuft in deinem Browser. Text, den du dort eingibst, wird genutzt, um das herunterladbare Bild auf deinem Gerät zu erstellen.</p><p>Einige E-Mail-Links können den Generator öffnen oder ein SVG über die Kampagnen-API anfordern. Dabei können ausgewählter Text, Format und Farbe in der URL enthalten sein, damit die Datei erzeugt werden kann.</p>
      <h2>Dienstleister</h2><p>Für den Betrieb der Kampagne nutzen wir folgende Dienstleister:</p><ul><li>Postmark, ein Dienst der AC PM LLC, für Transaktions- und Guide-E-Mails</li><li>Ko-fi, wenn du die Kampagne über den externen Beitragslink unterstützt</li></ul><p>Website, Anmeldedienst, Anmeldedatenbank, E-Mail-Zeitplan und Website-Statistik laufen auf unserem eigenen Server. Die für den E-Mail-Versand erforderlichen Daten werden an Postmark als Auftragsverarbeiter übermittelt. Weitere Informationen findest du in der <a href="https://postmarkapp.com/privacy-policy" rel="noopener noreferrer">Datenschutzerklärung von Postmark</a>.</p><p>Wenn du diese Website über externe Links verlässt, gilt die Datenschutzerklärung des jeweiligen externen Dienstes.</p>
      <h2 id="website-statistics">Cookies und Website-Statistik</h2><p>Mit deiner ausdrücklichen Zustimmung verwenden wir eine selbst betriebene, datensparsame Website-Statistik. Sie hilft uns zu verstehen, welche Seiten, Links, Aktionen zur Ansprache möglicher Unterstützender und Kampagnenmaterialien nützlich sind. Es werden keine Daten an einen externen Analysedienst übermittelt.</p><p>Erfasst werden Seitenaufrufe, pseudonyme Besucher- und Sitzungskennungen, die verweisende Domain, Herkunft und gegebenenfalls die Kampagnenparameter <code>utm_source</code>, <code>utm_medium</code>, <code>utm_campaign</code>, <code>utm_content</code> und <code>utm_term</code>, die grobe Geräteklasse, aktive Besuchszeit, angeklickte Linkziele, erfolgreiche Guide-Anmeldungen und Post-Downloads. Formularinhalte, E-Mail-Adressen, vollständige IP-Adressen und vollständige verweisende URLs werden nicht in der Analysedatenbank gespeichert.</p><p>Rechtsgrundlage ist deine Einwilligung gemäß Art. 6 Abs. 1 lit. a DSGVO und § 165 Abs. 3 TKG 2021. Vor deiner Zustimmung werden keine Analyseereignisse übertragen und keine Analysekennung gespeichert.</p><p>Deine Auswahl und die pseudonyme Besucherkennung werden für bis zu 180 Tage in den First-Party-Cookies <code>tgl_analytics_consent</code> und <code>tgl_analytics_visitor</code> gespeichert. Die Sitzungskennung liegt im Sitzungsspeicher deines Browsers und wird nach 30 Minuten Inaktivität erneuert. Einzelne Analyseereignisse werden nach spätestens 90 Tagen aus der aktiven Datenbank gelöscht.</p><p>Du kannst deine Entscheidung jederzeit ändern oder widerrufen. Beim Widerruf werden die Besucherkennung und die aktuelle Sitzungskennung auf deinem Gerät gelöscht; ab diesem Zeitpunkt werden keine weiteren Analyseereignisse übertragen.</p><p><button class="privacy-settings" type="button" data-analytics-settings>Datenschutz-Einstellungen öffnen</button></p>
      <h2>Server-Logs</h2><p>Beim Besuch verarbeitet unser Server technische Daten wie IP-Adresse, Anfragezeit, Browserinformationen und angeforderte URL, um den Dienst bereitzustellen, abzusichern und Fehler zu analysieren. Server-Logs werden nicht mit der optionalen Website-Statistik zusammengeführt und nicht für Profiling verwendet.</p>
      <h2>Kampagnenkorrespondenz und KI-gestützte Entwürfe</h2><p>Kampagnenbezogene Nachrichten, Kontaktdaten, Entwürfe und Entscheidungen über die Freigabe liegen in unserer geschützten Verwaltung. Adressen werden aus Nachrichten übernommen, die dem jeweiligen Kontakt zugeordnet wurden. Eine frühere Nachricht gilt nicht als Einwilligung in einen Verteiler. Wenn jemand einer weiteren Kontaktaufnahme widerspricht, wird dieser Widerspruch hinterlegt und weitere Ansprache verhindert.</p><p>Wir verwenden die OpenAI API, um öffentliche Quellen zu recherchieren und individuelle Entwürfe vorzubereiten. Die Recherche nutzt öffentliche Themen und Quellen zu Veranstaltungen, Veröffentlichungen, Kampagnen und Debatten. Relevante öffentliche Organisationen und Personen können mit Beleg ihrer Rolle sowie Links zu Website oder Kontaktseite als Kontakte aufgenommen werden. Öffentlich angegebene berufliche E-Mail-Adressen können von offiziellen Kontakt- oder Teamseiten samt Quelle übernommen werden, um den Empfänger für die menschliche Prüfung vorzubereiten. Der Abgleich mit bestehenden Kontakten erfolgt danach lokal. E-Mail-Adressen werden nicht erraten und aus einem Recherchefund wird keine Erlaubnis zur Kontaktaufnahme abgeleitet. Für Entwürfe werden begrenzte Auszüge relevanter Kampagnenkorrespondenz und Notizen verwendet; E-Mail-Adressen, telefonnummernähnliche Zahlen, Links und zitierte frühere Nachrichten werden soweit erkannt reduziert oder entfernt. Für die persönliche Anrede können gespeicherte Namen sowie Namen aus Anreden und eingehenden Signaturen enthalten sein. Das dient der Datenminimierung und garantiert keine Anonymität. Guide-Abonnentendaten und Website-Analysedaten werden diesen Funktionen nicht übermittelt. Entwürfe werden von einem Menschen geprüft und nicht automatisch versendet. Nach der Freigabe kann ein ausdrücklicher Versandklick die Nachricht über unser angebundenes E-Mail-Postfach versenden. Das Übermittlungsergebnis wird gespeichert und eine Kopie im Ordner Gesendet abgelegt. Diese Nachrichten enthalten kein Öffnungs- oder Klicktracking.</p><p>Die Speicherung von API-Antworten ist deaktiviert. OpenAI kann Anfrageinhalte zur Missbrauchserkennung speichern, grundsätzlich bis zu 30 Tage mit dort beschriebenen Ausnahmen. Siehe <a href="https://developers.openai.com/api/docs/guides/your-data" rel="noopener noreferrer">OpenAI API data controls</a>. Die Verarbeitung kann außerhalb der EU stattfinden.</p>
      <h2>Verschlüsselte Sicherungen</h2><p>Wir erstellen lokale Datenbanksicherungen und verschlüsselte Wiederherstellungskopien in einem separaten Ordner unseres Nextcloud-Speichers. Die Sicherungskopien werden nach 14 Tagen ersetzt. Gelöschte Datensätze und aus der aktiven Datenbank entfernte Analyseereignisse können bis zu 14 weitere Tage in verschlüsselten Wiederherstellungskopien verbleiben. Der Entschlüsselungsschlüssel wird getrennt von den hochgeladenen Archiven verwahrt. Sicherungen dienen ausschließlich der Wiederherstellung. Sie werden weder zur Kontaktaufnahme noch zur Analyse verwendet.</p>
      <h2>Speicherdauer</h2><p>Daten zum E-Mail-Guide speichern wir, solange dein Abo aktiv ist. Nach einer Abmeldung speichern wir nur, was nötig ist, um die Abmeldung zu respektieren, Versandnachweise zu erhalten und rechtliche oder betriebliche Fragen zu klären. Du kannst jederzeit die Löschung deiner Daten verlangen.</p>
      <h2>Deine Rechte</h2><p>Nach der DSGVO kannst du Auskunft über deine personenbezogenen Daten sowie deren Berichtigung oder Löschung verlangen. Du kannst auch die Einschränkung der Verarbeitung verlangen oder der Verarbeitung widersprechen. Eine erteilte Einwilligung kannst du jederzeit widerrufen.</p><p>Zur Ausübung deiner Rechte kontaktiere <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a>. Du hast außerdem das Recht, Beschwerde bei einer Datenschutzbehörde einzulegen.</p>
      <h2>Änderungen</h2><p>Wir können diese Datenschutzerklärung aktualisieren, wenn sich Kampagne, Website oder E-Mail-System ändern. Das Datum oben zeigt den Stand der aktuellen Version.</p>
    </section>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="imprint.html">Impressum</a> &middot; <button class="privacy-settings" type="button" data-analytics-settings>Datenschutz-Einstellungen</button> &middot; <a href="../privacy.html" hreflang="en" lang="en">English</a></p></div></footer>
</body>
</html>
`;
}

function deImprint() {
  const style = legalStyle("imprint.html");
  return `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Impressum | The Great Logout</title>
  <meta name="description" content="Impressum und Kontaktinformationen von The Great Logout." />
  <link rel="canonical" href="${site}/de/imprint.html" />
${altLinks({ en: "/imprint.html", de: "/de/imprint.html" })}
  <meta property="og:title" content="Impressum | The Great Logout" />
  <meta property="og:description" content="Impressum und Kontaktinformationen von The Great Logout." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${site}/de/imprint.html" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Impressum | The Great Logout" />
  <meta name="twitter:description" content="Impressum und Kontaktinformationen von The Great Logout." />
  <meta name="twitter:image" content="${site}/assets/og-image.png" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="../assets/apple-touch-icon.png" />
  <style>${style}</style>
</head>
<body>
  <header class="site-header"><div class="wrap nav"><a class="brand" href="index.html" aria-label="The Great Logout Startseite"><img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" /><span>The Great Logout</span></a><nav class="nav-links" aria-label="Hauptnavigation"><a href="index.html#how">So geht es</a><a href="index.html#why">Warum?</a><a href="index.html#generator">Post-Generator</a><a href="index.html#support">Unterstützen</a><a class="language-switch" href="../imprint.html" hreflang="en" lang="en">EN</a><a href="index.html#start-guide" class="nav-cta">Start</a></nav></div></header>
  <main>
    <section class="hero"><div class="wrap"><div class="kicker">Rechtlicher Hinweis</div><h1>Impressum</h1></div></section>
    <section class="wrap legal" aria-label="Impressum">
      <h2>Angaben gemäß österreichischen Offenlegungspflichten</h2>
      <div class="legal-card"><p><strong>The Great Logout</strong></p><p>Eine Kampagne von Daniel Netzl</p><p>Landstraße 47</p><p>2464 Göttlesbrunn</p><p>Österreich</p><p><a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a></p></div>
      <h2>Verantwortlich für den Inhalt</h2><p>Daniel Netzl ist für den Inhalt dieser Website verantwortlich.</p>
      <h2>Unabhängigkeit</h2><p>The Great Logout ist nicht mit Instagram, TikTok, Meta, X oder einer anderen Social-Media-Plattform verbunden.</p>
      <h2>Externe Links</h2><p>Diese Website kann auf externe Websites verlinken. Für die Inhalte und Verfügbarkeit externer Websites sowie deren Umgang mit personenbezogenen Daten übernehmen wir keine Verantwortung.</p>
      <p class="muted">Zuletzt aktualisiert: 19. Juni 2026</p>
    </section>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="privacy.html">Datenschutzerklärung</a> &middot; <button class="privacy-settings" type="button" data-analytics-settings>Datenschutz-Einstellungen</button> &middot; <a href="../imprint.html" hreflang="en" lang="en">English</a></p></div></footer>
</body>
</html>
`;
}

function patchEnglishIndexPayload() {
  let source = read("index.html");
  source = source.replace(
    /guideLength: Number\(formData\.get\("guideLength"\) \|\| 7\),\n          consent:/,
    'guideLength: Number(formData.get("guideLength") || 7),\n          language: "en",\n          consent:'
  );
  source = source.replace(
    /guideLength: Number\(formData\.get\("guideLength"\) \|\| 7\),\n          language: "en",/,
    'guideLength: Number(formData.get("guideLength") || 7),\n          language: String(formData.get("language") || document.documentElement.lang || "en").trim().slice(0, 8),'
  );
  source = source.replace(
    /<form class="signup-form" id="guideSignupForm" data-endpoint="\/api\/guide\/subscribe">\n(?!\s*<input type="hidden" name="language")/,
    '<form class="signup-form" id="guideSignupForm" data-endpoint="/api/guide/subscribe">\n              <input type="hidden" name="language" value="en" />\n'
  );
  write("index.html", source);
}

updateEnglishPage("index.html", "/de/");
updateEnglishPage("essay.html", "/de/essay.html");
updateEnglishPage("privacy.html", "/de/privacy.html");
updateEnglishPage("imprint.html", "/de/imprint.html");
patchEnglishIndexPayload();

write(path.join("de", "index.html"), ensureAnalyticsAssets(ensureMobileMenuScript(ensureMobileMenuMarkup(deIndex(), "Menü")), "../"));
write(path.join("de", "essay.html"), ensureAnalyticsAssets(ensureMobileMenuScript(ensureMobileMenuMarkup(deEssay(), "Menü")), "../"));
write(path.join("de", "privacy.html"), ensureAnalyticsAssets(ensureMobileMenuScript(ensureMobileMenuMarkup(dePrivacy(), "Menü")), "../"));
write(path.join("de", "imprint.html"), ensureAnalyticsAssets(ensureMobileMenuScript(ensureMobileMenuMarkup(deImprint(), "Menü")), "../"));

console.log("Generated German site and updated language metadata.");
