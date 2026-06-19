const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const deDir = path.join(root, "de");
fs.mkdirSync(deDir, { recursive: true });

const site = "https://www.thegreatlogout.org";

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
  output = output.replace(/\s*&middot;\s*<a href="de\/[^"]*" hreflang="de" lang="de">Deutsch<\/a>/g, "");
  output = output.replace(/\s*&middot;\s*<a href="de\/" hreflang="de" lang="de">Deutsch<\/a>/g, "");
  output = output.replace(/<style>([\s\S]*?)<\/style>/, (_match, style) => `<style>${ensureLanguageCss(style)}</style>`);
  const deHref = counterpart === "/de/" ? "de/" : `de/${path.basename(counterpart)}`;
  output = output.replace(
    /(<a href="index\.html#start-guide" class="nav-cta">Start<\/a>|<a href="#start-guide" class="nav-cta">Start<\/a>)/,
    `<a class="language-switch" href="${deHref}" hreflang="de" lang="de">DE</a>\n        $1`
  );
  output = output.replace(
    /(<a href="privacy\.html">Privacy<\/a>|<a href="privacy\.html">Privacy<\/a><\/p>|<a href="imprint\.html">Imprint<\/a><\/p>|<a href="privacy\.html">Privacy Policy<\/a><\/p>)/,
    match => match.includes("</p>")
      ? match.replace("</p>", ` &middot; <a href="${deHref}" hreflang="de" lang="de">Deutsch</a></p>`)
      : `${match}\n        &middot;\n        <a href="${deHref}" hreflang="de" lang="de">Deutsch</a>`
  );
  output = ensureMobileMenuMarkup(output, "Menu");
  output = ensureMobileMenuScript(output);
  write(file, output);
}

const dePostIdeas = [
  "Aufmerksamkeit ist wertvoll.\nIch gebe sie nicht länger ab.",
  "Ich bereite meinen Ausstieg vor.\nIch verschwinde nicht.",
  "Ich verlasse diese Plattform.\nIn den nächsten Tagen erkläre ich warum.",
  "Meine Aufmerksamkeit und meine Beziehungen gehören wieder mir.",
  "Was denkst du eigentlich selbst?\nNicht der Feed. Du.",
  "Sie nennen es Verbindung.\nOft fühlt es sich nach Einsamkeit an.",
  "Ich hole mir meine Zeit zurück.\nSie war nie für den Feed bestimmt.",
  "Ich entscheide mich für echte Nähe.\nNicht für endloses Scrollen.",
  "Wenn alles nur noch rauscht,\nist Ausloggen ein Anfang.",
  "Der Feed kennt deine Schwächen.\nGenau deshalb funktioniert er.",
  "Du schuldest keiner Plattform dein Leben.",
  "Erst verkaufen sie deine Aufmerksamkeit.\nDann verkaufen sie dir die Ablenkung zurück.",
  "Du bist nicht undiszipliniert.\nDas System wurde gegen dich gebaut.",
  "Ich bin kein Rohstoff.",
  "Weniger Scrollen.\nMehr Leben.",
  "Mein Kopf ist kein Werbeplatz.",
  "Ich will nicht, dass ein paar Konzerne meinen Alltag vorsortieren.",
  "Einsamkeit ist für Plattformen ein Geschäftsmodell.",
  "Wenn es dich wütend, müde und leer macht:\nWarum ist es noch auf deinem Handy?",
  "Man hört sich selbst schlecht,\nwenn der Feed dauernd dazwischenredet.",
  "Ich verschwinde nicht.\nIch bin nur nicht mehr hier.",
  "Offline ist nicht leer.\nOffline ist das Leben.",
  "Das ist kein Detox.\nDas ist eine Grenze.",
  "Der Algorithmus kennt dich nicht.\nEr kennt nur deine Reaktionen.",
  "Ich will meine Gedanken nicht vorsortiert bekommen.",
  "Das echte Leben hat keinen endlosen Feed.",
  "Ich gehe,\nbevor der Feed noch mehr von mir frisst.",
  "Ich verlasse den Feed,\nnicht die Menschen.",
  "Du erreichst mich weiterhin hier: ...",
  "Sie wollen nicht, dass du glücklich bist.\nSie wollen, dass du zurückkommst.",
  "Meine Aufmerksamkeit steht nicht zum Verkauf.",
  "Der Ausstieg ist die Botschaft.",
  "Ich logge mich aus,\num wieder bei mir anzukommen.",
  "Vielleicht ist Langeweile kein Problem.\nVielleicht ist sie ein Signal.",
  "Du verpasst nicht alles.\nDu wirst in alles hineingezogen.",
  "Wenn der Feed mehr nimmt als gibt,\ndarfst du gehen.",
  "Sag warum.\nSag, wo man dich findet.\nDann log dich aus.",
  "Behalte die Menschen.\nVerlier den Feed.",
  "Das ist mein letzter Post hier.\nWir sehen uns im echten Leben."
];

function deIndexScript() {
  let script = between(read("index.html"), "<script>", "</script>");
  script = script
    .replace('const typeLineOne = "Millions logged in.";', 'const typeLineOne = "Millionen sind eingeloggt.";')
    .replace('const typeLineTwo = "Now we log out.";', 'const typeLineTwo = "Jetzt gehen wir raus.";')
    .replace(/const postIdeas = \[[\s\S]*?\];/, `const postIdeas = ${JSON.stringify(dePostIdeas, null, 6)};`)
    .replace('logoImage.src = "assets/the-great-logout-mark.svg";', 'logoImage.src = "../assets/the-great-logout-mark.svg";')
    .replaceAll("A collective social media exit", "Gemeinsam raus aus Social Media")
    .replaceAll("The exit is the message.", "Der Ausstieg ist die Botschaft.")
    .replace('language: "en"', 'language: "de"')
    .replace('custom.textContent = "Custom text";', 'custom.textContent = "Eigener Text";')
    .replace('button.textContent = "Use this";', 'button.textContent = "Verwenden";')
    .replace('signupStatus.textContent = "Signup is not connected yet.";', 'signupStatus.textContent = "Die Anmeldung ist noch nicht verbunden.";')
    .replace('signupStatus.textContent = "Adding you to the guide...";', 'signupStatus.textContent = "Deine Anmeldung wird eingetragen...";')
    .replace('throw new Error(result.error || "Signup failed.");', 'throw new Error(result.error || "Anmeldung fehlgeschlagen.");')
    .replace('signupStatus.textContent = "You\\\'re in. Check your inbox for the first email.";', 'signupStatus.textContent = "Du bist dabei. Die erste E-Mail ist unterwegs.";')
    .replace('signupStatus.textContent = error.message || "Something went wrong. Please try again.";','signupStatus.textContent = error.message || "Etwas ist schiefgelaufen. Bitte versuche es erneut.";');

  script = script.replace(
    /guideLength: Number\(formData\.get\("guideLength"\) \|\| 7\),\n          consent:/,
    'guideLength: Number(formData.get("guideLength") || 7),\n          language: "de",\n          consent:'
  );
  return script;
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
          <h1>Raus aus Social Media. Nicht heimlich.</h1>

          <p class="hero-copy">
            The Great Logout hilft dir, süchtig machende soziale Medien bewusst und sichtbar zu verlassen. <strong>Teile 1 bis 7 Tage lang kurze Ausstiegs-Posts</strong>, erklär warum du gehst, sag wo man dich weiterhin erreicht und log dich dann aus. Nicht still. Sondern so, dass andere merken: Man kann gehen.
          </p>

          <div class="button-row">
            <a class="btn btn-primary" href="#start-guide">7-Tage-Guide starten</a>
            <a class="btn btn-secondary" href="#generator">Post erstellen</a>
          </div>

          <p class="campaign-note">
            <strong>Es geht um ein sichtbares Signal.</strong> Andere sehen deine Entscheidung, bevor du aus ihrem Feed verschwindest.
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
                  <p>Ein Grund pro Tag. Kurz reicht. Ehrlich wirkt.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Vor dem Ausstieg</span>
                <div>
                  <strong>Bleib erreichbar.</strong>
                  <p>E-Mail, Telefon, Website, Messenger, echtes Leben. Hauptsache: nicht mehr über den Feed.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Letzter Post</span>
                <div>
                  <strong>Dann log dich aus.</strong>
                  <p>Lösch die Apps, deaktiviere Accounts oder nimm den Plattformen den automatischen Zugriff auf deinen Tag.</p>
                </div>
              </li>
            </ol>

            <div class="mobile-sequence-cta">
              <a class="btn btn-primary" href="#start-guide">Heute starten</a>
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
          <article class="step"><div><h3>Wähle 1, 3 oder 7 Tage.</h3><p>Nimm dir eine Dauer vor, die du wirklich durchziehst. Sieben Tage geben anderen genug Zeit, deinen Ausstieg wahrzunehmen.</p></div></article>
          <article class="step"><div><h3>Teile jeden Tag einen Grund.</h3><p>Schreib direkt und menschlich. Sag, was dir der Feed nimmt und was du dir zurückholen willst.</p></div></article>
          <article class="step"><div><h3>Sag, wo man dich erreicht.</h3><p>Verschwinde nicht aus dem Leben der Menschen, die dir wichtig sind. Verlege die Beziehung aus der Plattform heraus.</p></div></article>
          <article class="step"><div><h3>Lösch die Apps oder deaktiviere deine Accounts.</h3><p>Mach den Rückweg schwerer. Entferne die Abkürzung. Unterbrich den Reflex.</p></div></article>
          <article class="step"><div><h3>Bleib draußen und mach es anderen leichter.</h3><p>Wenn dich jemand fragt, warum du gegangen bist, antworte klar. So wird aus einem privaten Schritt ein öffentliches Signal.</p></div></article>
        </div>

        <div class="how-cta">
          <div>
            <h3>Bereit, es wirklich zu machen?</h3>
            <p>Der Guide gibt dir Tagesimpulse, ein konkretes Ausstiegsdatum und spätere Check-ins.</p>
          </div>
          <a class="btn btn-primary" href="#start-guide">Heute starten</a>
        </div>
      </div>
    </section>

    <section id="why">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Mehr als Bildschirmzeit</div><h2>Warum Ausloggen ein öffentliches Nein sein kann.</h2></div></div>
        <div class="why-case">
          <p><strong>The Great Logout ist eine öffentliche Absage.</strong> Nicht an das Internet. Sondern an Plattformen, die so normal geworden sind, dass ihre Macht kaum noch auffällt.</p>
          <p>Der Essay bündelt 13 Gründe: süchtig machende Feeds, algorithmische Kontrolle, Big Tech, Konsumdruck, passive Öffentlichkeit, Einsamkeit, Politik, Kultur und den schleichenden Verlust von Aufmerksamkeit.</p>
          <p>Der Kern ist einfach: Hör auf, Systeme zu füttern, die aus Aufmerksamkeit, Wut, Einsamkeit, Unsicherheit und Gewohnheit Profit machen.</p>
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
            <h2>Eine Woche sichtbar werden. Dann raus.</h2>
            <p class="lead">Der Guide gibt dir jeden Tag einen klaren Impuls. Du kannst ihn übernehmen, anpassen oder nur als Anstoß nutzen. Wichtig ist, dass aus dem Vorsatz ein Ausstieg wird.</p>
            <div class="guide-days">
              <article class="guide-day"><span>Tag 0</span><div><h3>Den Ausstieg vorbereiten</h3><p>Kontakte sichern, letzten Tag festlegen und entscheiden, wo man dich künftig erreicht.</p></div></article>
              <article class="guide-day"><span>Tag 1</span><div><h3>Warum ich gehe</h3><p>Fang klar an. Sag, dass dein Ausstieg bewusst ist.</p></div></article>
              <article class="guide-day"><span>Tag 2</span><div><h3>Was der Feed mit mir macht</h3><p>Benenne den Sog, das Wegdriften und die Zeit, die du zurückhaben willst.</p></div></article>
              <article class="guide-day"><span>Tag 3</span><div><h3>Was ich zurückholen will</h3><p>Mehr Ruhe. Mehr Fokus. Mehr echte Nähe. Dein Grund muss niemandem gefallen.</p></div></article>
              <article class="guide-day"><span>Tag 4</span><div><h3>Warum Big Tech zu viel Macht hat</h3><p>Sag, was ein paar Konzerne nicht länger für dich sortieren sollen.</p></div></article>
              <article class="guide-day"><span>Tag 5</span><div><h3>Wo man mich findet</h3><p>Gib Menschen einen anderen Weg zu dir. Behalte die Verbindung, nicht den Feed.</p></div></article>
              <article class="guide-day"><span>Tag 6</span><div><h3>Andere einladen</h3><p>Ohne Druck. Zeig nur, dass die Tür offen ist.</p></div></article>
              <article class="guide-day"><span>Tag 7</span><div><h3>Letzter Post. Logout.</h3><p>Poste deine letzte Nachricht. Lösch die Apps. Geh.</p></div></article>
            </div>
          </div>

          <aside class="signup-card guide-signup" id="start-guide" aria-labelledby="signup-title">
            <h3 id="signup-title">Starte deinen Ausstieg</h3>
            <p>1 bis 7 Tage sichtbar werden. Dann ausloggen.</p>
            <p class="signup-link">Brauchst du zuerst eine Formulierung? <a href="#generator">Zum Post-Generator.</a></p>
            <form class="signup-form" id="guideSignupForm" data-endpoint="https://api.thegreatlogout.org/subscribe">
              <label for="email">E-Mail-Adresse</label>
              <input id="email" name="email" type="email" placeholder="du@example.com" autocomplete="email" required />
              <label for="firstName">Vorname <span aria-hidden="true">(optional)</span></label>
              <input id="firstName" name="firstName" type="text" autocomplete="given-name" />
              <label for="logoutDate">Geplantes Logout-Datum <span aria-hidden="true">(optional)</span></label>
              <input id="logoutDate" name="logoutDate" type="date" />
              <label class="checkbox-field">
                <input id="emailConsent" name="consent" type="checkbox" required />
                <span>Schick mir den Logout-Guide und ein paar spätere Check-ins. Kein Feed, kein Spam.</span>
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
        <div class="section-head"><div><div class="kicker">Manifest</div><h2>Wir kündigen nicht einander.</h2></div></div>
        <div class="manifesto"><p>Wir gehen, weil Plattformen zu Maschinen für Sucht, Empörung, Überwachung und Kontrolle geworden sind. The Great Logout richtet sich nicht gegen Kreative oder Gemeinschaften. Es ist eine Weigerung, Plattformen weiter mit unserer Zeit, unserer Wut, unseren Beziehungen und unserer Aufmerksamkeit zu füttern.</p></div>
      </div>
    </section>

    <section id="support">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Unterstützen</div><h2>Hilf mit, die Kampagne unabhängig zu halten.</h2></div></div>
        <div class="support-grid">
          <div class="support-copy">
            <p>The Great Logout soll einfach, öffentlich und frei nutzbar bleiben. Du hilfst, indem du die Seite teilst, den Generator nutzt, den Guide weitergibst oder die laufenden Kosten unterstützt.</p>
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

  <footer class="site-footer">
    <div class="wrap footer-grid">
      <div>
        <a class="brand footer-brand" href="#top" aria-label="The Great Logout Startseite">
          <span class="brand-mark" aria-hidden="true"><img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" /></span>
          <span>The Great Logout</span>
        </a>
        <p>Sag warum. Sag, wo man dich findet. Dann log dich aus.</p>
      </div>
      <div class="footer-links" aria-label="Footer navigation">
        <a href="#how">So geht es</a>
        &middot;
        <a href="#guide">7-Tage-Guide</a>
        &middot;
        <a href="#generator">Post-Generator</a>
        &middot;
        <a href="essay.html">Essay</a>
        &middot;
        <a href="#support">Unterstützen</a>
        &middot;
        <a href="imprint.html">Impressum</a>
        &middot;
        <a href="privacy.html">Datenschutz</a>
        &middot;
        <a href="../" hreflang="en" lang="en">English</a>
      </div>
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
  <meta name="description" content="Ein Essay über süchtig machende Feeds, Big-Tech-Macht, Aufmerksamkeit, Konsumdruck, politische Passivität und den sichtbaren Social-Media-Ausstieg." />
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
    <section class="hero"><div class="wrap"><div class="kicker">Essay</div><h1>13 Gründe, dich auszuloggen</h1><p class="intro">Es geht nicht nur um weniger Bildschirmzeit. Der Feed prägt, worauf wir achten, worüber wir streiten, was wir begehren und wie sich unser Alltag anfühlt. The Great Logout ist eine öffentliche Absage an diese Normalität.</p><div class="meta" aria-label="Artikeldetails"><span>Von <a href="https://www.danielnetzl.at" target="_blank" rel="noopener">Daniel Netzl</a></span><span>Februar 2025</span><span>Für The Great Logout aktualisiert</span></div></div></section>
    <article><div class="wrap essay">
      <p>Über manche Süchte sprechen wir inzwischen offen: Alkohol, Zigaretten, Glücksspiel, Medikamente. Wir wissen, dass Willenskraft allein nicht immer reicht. Darum gibt es Warnungen, Regeln, Altersgrenzen und Unterstützung.</p>
      <p>Eine der stärksten Abhängigkeiten unserer Zeit tragen wir aber in der Tasche. Sie leuchtet, aktualisiert sich, beobachtet uns und bietet immer noch einen Clip, eine Empörung, einen Vergleich, einen Kaufimpuls, einen Grund zu bleiben.</p>
      <p>Der Feed wirkt harmlos, weil er alltäglich geworden ist. Genau darin liegt seine Macht.</p>
      <h2>1. Deine Aufmerksamkeit wird abgeschöpft</h2><p>Aufmerksamkeit ist nicht irgendeine Ressource. Sie ist die Grundlage dafür, wie wir leben: wie wir zuhören, lernen, lieben, denken, trauern, arbeiten, gestalten und handeln.</p><p>Die großen Plattformen behandeln diese Aufmerksamkeit wie Rohmaterial. Deine Pause, deine Wut, deine Neugier, deine Einsamkeit, deine Freundschaften, deine Schwäche um Mitternacht. Alles wird messbar. Alles fließt zurück in ein System, das lernt, dich länger zu halten.</p>
      <h2>2. Der Feed wurde gebaut, damit du zurückkommst</h2><p>TikTok, Instagram, YouTube, Facebook, X und ähnliche Plattformen sind keine neutralen Treffpunkte. Sie sind Sortiermaschinen. Sie entscheiden, was du siehst, was verschwindet, was wiederkommt und welche Stimmung sich durch deinen Tag zieht.</p><p>Das Geschäftsmodell ist simpel: Menschen schauen lassen, reagieren lassen, zurückholen. Mehr Aufmerksamkeit bedeutet mehr Daten. Mehr Daten bedeuten bessere Zielgruppen. Bessere Zielgruppen bedeuten mehr Geld.</p>
      <div class="pull">Ein paar Unternehmen sitzen heute zwischen Milliarden Menschen und der Wirklichkeit. Das ist zu viel Macht.</div>
      <h2>3. Big Tech legt sich über das öffentliche Leben</h2><p>Eine Handvoll Konzerne prägt, was Milliarden Menschen sehen, glauben, fürchten, begehren und diskutieren. Sie beeinflussen Wahlen, Beziehungen, Nachrichten, Kultur, Mode, Sprache, Humor, Musik, Empörung und Schönheitsideale.</p><p>Diese Macht sieht nicht immer wie Politik aus. Aber sie entscheidet mit, welche Stimmen lauter werden, welche verschwinden, was relevant erscheint und welche Konflikte weiterlaufen, weil sie Aufmerksamkeit bringen.</p>
      <h2>4. Empörung wird belohnt</h2><p>Algorithmen müssen nicht jede Lüge und jeden Konflikt erfinden. Sie müssen nur erkennen, was Menschen festhält, und es stärker ausspielen. Wut funktioniert. Gewissheit funktioniert. Verachtung funktioniert. Nuance ist meistens zu langsam.</p><p>So verlieren Menschen den gemeinsamen Boden. Jede Person bekommt eine eigene Welt, abgestimmt auf Ängste, Vorlieben, Verletzungen und Schwächen.</p>
      <h2>5. Selbst Langeweile wird besetzt</h2><p>Langeweile war einmal ein normaler Teil des Lebens: warten, gehen, im Zug sitzen, in einer Schlange stehen, den Gedanken freien Lauf lassen.</p><p>Diese Momente sind nicht leer. Oft entstehen genau dort Ideen, Entscheidungen und der erste klare Gedanke nach viel Lärm. Der Feed greift genau diesen Raum an.</p>
      <h2>6. Vergleich wurde Alltag</h2><p>Der Feed zeigt Körper, Wohnungen, Beziehungen, Reisen, Routinen, Gesichter, Karrieren und Lebensstile so, dass fast immer ein Mangel bleibt.</p><p>Natürlich wissen viele, dass Bilder gestellt und bearbeitet sind. Das macht sie nicht harmlos. Wiederholung wirkt, auch wenn man ihr nicht glaubt.</p>
      <h2>7. Einsamkeit ist profitabel</h2><p>Plattformen versprechen Verbindung, liefern aber oft nur Kontakt ohne Nähe. Du kannst hunderte Menschen sehen und dich trotzdem allein fühlen. Du kannst den ganzen Tag erreichbar sein und trotzdem nicht wirklich vorkommen.</p><p>Die Antwort ist nicht Rückzug aus der Welt. Die Antwort ist, Beziehungen wieder in Kanäle zu bringen, die nicht davon leben, dass du abhängig bleibst.</p>
      <h2>8. Politik wird zur Performance</h2><p>Ein Like kann sich wie Haltung anfühlen. Ein Repost wie Mut. Ein Kommentar wie Handlung. Manchmal hilft das. Oft ersetzt es das, was außerhalb der Plattform passieren müsste.</p><p>Eine Gesellschaft kann den ganzen Tag empört sein und trotzdem stillstehen.</p>
      <div class="pull">Eine Gesellschaft kann den ganzen Tag empört sein und trotzdem stillstehen.</div>
      <h2>9. Kultur wird flacher</h2><p>Der Feed ist nicht auf Tiefe ausgelegt. Er ist auf Verbreitung ausgelegt. Was schnell reist, wirkt schnell wichtiger, als es ist.</p><p>Das verändert Kunst, Sprache, Humor, Musik, Politik und sogar Persönlichkeit. Menschen beginnen, sich für ein System zu formen, das aktiv unsere Aufmerksamkeit lenkt.</p>
      <h2>10. Menschen werden passiv gehalten</h2><p>Plattformen zersplittern unseren gemeinsamen Horizont. Jede Person bekommt eine private Version der Wirklichkeit, optimiert auf Engagement und kurzfristige Emotion.</p><p>Wir brauchen aktive Gemeinschaften, nicht nur informierte Zuschauerinnen und Zuschauer. Wir brauchen Menschen, die zusammensitzen, widersprechen, planen, protestieren, füreinander sorgen und Alternativen aufbauen.</p>
      <h2>11. Begehren wird produziert</h2><p>Dieselben Systeme, die Meinung formen, formen auch Wünsche. Sie legen nahe, dass Erfüllung nur einen Kauf, eine Reise, ein Upgrade oder eine bessere Version von dir entfernt ist.</p><p>Diese Rastlosigkeit hat Folgen: Konsum, Müll, Vergleich, Schulden und ökologische Schäden.</p>
      <h2>12. Beziehungen laufen durch Maschinen</h2><p>Viele bleiben, weil Gehen sich wie Verschwinden anfühlt. Diese Angst ist real. Plattformen haben sich zwischen Freundschaften, Familien, Künstlerinnen, Organisatoren, Kundschaft und Gemeinschaften geschoben.</p><p>Wenn eine Beziehung wichtig ist, gib ihr einen direkten Weg: E-Mail, Signal, Telefon, Website, Newsletter, Tisch, Raum, echtes Leben.</p>
      <h2>13. Ein sichtbarer Ausstieg macht anderen Mut</h2><p>Leise zu gehen hilft der Person, die geht. Sichtbar zu gehen hilft auch den anderen.</p><p>Wenn du einfach verschwindest, schluckt die Plattform deine Abwesenheit. Wenn du aber sagst, warum du gehst, sehen andere einen Ausgang. Sie sehen, dass Ausloggen nicht nur privates Scheitern an Disziplin ist, sondern eine bewusste Entscheidung.</p><p>Du brauchst kein perfektes Argument. Sag, warum du gehst. Sag, wo man dich erreicht. Dann geh.</p>
      <div class="action-box"><h2>Der Ausstieg ist die Botschaft</h2><p>The Great Logout ist nicht gegen das Internet. Es richtet sich gegen Plattformen, die Sucht, Empörung, Überwachung, Einsamkeit und Unsicherheit in ein Geschäftsmodell verwandeln.</p><p>Wenn dieser Essay dir geholfen hat, den Feed anders zu sehen, nutze diese Klarheit. Erstelle einen Post. Starte den Guide. Unterstütze die Kampagne, wenn du kannst.</p><div class="button-row"><a class="btn btn-primary" href="index.html#guide">Logout starten</a><a class="btn btn-secondary" href="index.html#generator">Post erstellen</a><a class="btn btn-secondary" href="https://ko-fi.com/thegreatlogout" target="_blank" rel="noopener">Kampagne unterstützen</a></div></div>
    </div></article>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="imprint.html">Impressum</a> &middot; <a href="privacy.html">Datenschutz</a> &middot; <a href="../essay.html" hreflang="en" lang="en">English</a></p></div></footer>
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
      <p class="muted">Zuletzt aktualisiert: 19. Juni 2026</p>
      <div class="legal-card"><p><strong>Kurzfassung:</strong> The Great Logout erhebt nur die Daten, die für den E-Mail-Guide nötig sind. Der Post-Generator läuft in deinem Browser. Auf dieser Website verwenden wir keine Werbetracker, keine Analytics-Cookies und kein Profiling.</p></div>
      <h2>Verantwortlicher</h2><p>Verantwortlich für diese Website ist:</p><p>The Great Logout<br />Eine Kampagne von Daniel Netzl<br />Landstraße 47<br />2464 Göttlesbrunn<br />Österreich<br /><a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a></p>
      <h2>Welche Daten wir erheben</h2><p>Wenn du dich für den E-Mail-Guide anmeldest, verarbeiten wir die Daten, die du selbst einträgst:</p><ul><li>E-Mail-Adresse</li><li>optional Vorname</li><li>optional geplantes Logout-Datum</li><li>gewählte Guide-Länge</li><li>Einwilligung zum Erhalt des Guides</li></ul><p>Für Versand und Abmeldung speichern wir außerdem, soweit erforderlich, technische Informationen wie Abmelde-Token, Anmeldezeitpunkt, Abmeldezeitpunkt, Versandstatus, Zustell-IDs und Fehlermeldungen.</p>
      <h2>Wofür wir diese Daten verwenden</h2><p>Wir verwenden diese Daten, um dir den Logout-Guide, spätere Check-ins und verwandte Kampagnen-E-Mails zu schicken, die du angefordert hast. Rechtsgrundlage ist deine Einwilligung nach Art. 6 Abs. 1 lit. a DSGVO.</p><p>Begrenzte technische Daten können außerdem verarbeitet werden, um Website und E-Mail-System zu betreiben, abzusichern und zu verbessern. Rechtsgrundlage ist unser berechtigtes Interesse nach Art. 6 Abs. 1 lit. f DSGVO.</p>
      <h2>E-Mail-Guide und Abmeldung</h2><p>Du kannst dich jederzeit über den Abmeldelink in jeder E-Mail vom Guide abmelden. Alternativ erreichst du uns unter <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a>.</p><p>Nach einer Abmeldung senden wir keine Guide-E-Mails mehr. Eine begrenzte Dokumentation der Abmeldung kann gespeichert bleiben, damit wir keine weiteren E-Mails senden und die Einwilligungshistorie nachvollziehen können.</p>
      <h2>Post-Generator</h2><p>Der Post-Generator läuft in deinem Browser. Text, den du dort eingibst, wird genutzt, um das herunterladbare Bild auf deinem Gerät zu erstellen.</p><p>Einige E-Mail-Links können den Generator öffnen oder ein SVG über die Kampagnen-API anfordern. Dabei können ausgewählter Text, Format und Farbe in der URL enthalten sein, damit die Datei erzeugt werden kann.</p>
      <h2>Dienstleister</h2><p>Für den Betrieb der Kampagne nutzen wir folgende Dienstleister:</p><ul><li>GitHub Pages für das Hosting der statischen Website</li><li>Cloudflare für DNS, Sicherheit und die E-Mail-Anmelde-API</li><li>Cloudflare D1 zur Speicherung von Guide-Anmeldungen</li><li>Postmark für Transaktions- und Guide-E-Mails</li><li>eine externe Plattform für freiwillige Beiträge, wenn du die Kampagne unterstützt</li></ul><p>Wenn du diese Website über externe Links verlässt, gilt die Datenschutzerklärung des jeweiligen externen Dienstes.</p>
      <h2>Cookies und Analytics</h2><p>Derzeit verwendet diese Website keine Analytics-Cookies, Werbe-Cookies oder Tracking-Pixel. Falls sich das ändert, wird diese Erklärung aktualisiert.</p>
      <h2>Server-Logs</h2><p>Hosting-, DNS-, Sicherheits- und E-Mail-Anbieter können technische Daten wie IP-Adresse, Anfragezeit, Browserinformationen, angeforderte URL und Versandprotokolle verarbeiten, um ihre Dienste bereitzustellen und zu schützen. Wir nutzen diese Daten nicht, um Besucherinnen oder Besucher zu profilieren.</p>
      <h2>Speicherdauer</h2><p>Daten zum E-Mail-Guide speichern wir, solange dein Abo aktiv ist. Nach einer Abmeldung speichern wir nur, was nötig ist, um die Abmeldung zu respektieren, Versandnachweise zu erhalten und rechtliche oder betriebliche Fragen zu klären. Du kannst jederzeit Löschung verlangen.</p>
      <h2>Deine Rechte</h2><p>Nach der DSGVO kannst du Auskunft, Berichtigung, Löschung, Einschränkung oder Widerspruch gegen die Verarbeitung deiner personenbezogenen Daten verlangen. Eine erteilte Einwilligung kannst du jederzeit widerrufen.</p><p>Zur Ausübung deiner Rechte kontaktiere <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a>. Du hast außerdem das Recht, Beschwerde bei einer Datenschutzbehörde einzulegen.</p>
      <h2>Änderungen</h2><p>Wir können diese Datenschutzerklärung aktualisieren, wenn sich Kampagne, Website oder E-Mail-System ändern. Das Datum oben zeigt den Stand der aktuellen Version.</p>
    </section>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="imprint.html">Impressum</a> &middot; <a href="../privacy.html" hreflang="en" lang="en">English</a></p></div></footer>
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
      <h2>Externe Links</h2><p>Diese Website kann auf externe Websites verlinken. Für Inhalte, Verfügbarkeit und Datenschutzpraktiken externer Websites übernehmen wir keine Verantwortung.</p>
      <p class="muted">Zuletzt aktualisiert: 19. Juni 2026</p>
    </section>
  </main>
  <footer class="footer"><div class="wrap"><p>&copy; 2026 The Great Logout</p><p><a href="index.html">Zur Kampagne</a> &middot; <a href="privacy.html">Datenschutzerklärung</a> &middot; <a href="../imprint.html" hreflang="en" lang="en">English</a></p></div></footer>
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
  write("index.html", source);
}

updateEnglishPage("index.html", "/de/");
updateEnglishPage("essay.html", "/de/essay.html");
updateEnglishPage("privacy.html", "/de/privacy.html");
updateEnglishPage("imprint.html", "/de/imprint.html");
patchEnglishIndexPayload();

write(path.join("de", "index.html"), ensureMobileMenuScript(ensureMobileMenuMarkup(deIndex(), "Menü")));
write(path.join("de", "essay.html"), ensureMobileMenuScript(ensureMobileMenuMarkup(deEssay(), "Menü")));
write(path.join("de", "privacy.html"), ensureMobileMenuScript(ensureMobileMenuMarkup(dePrivacy(), "Menü")));
write(path.join("de", "imprint.html"), ensureMobileMenuScript(ensureMobileMenuMarkup(deImprint(), "Menü")));

console.log("Generated German site and updated language metadata.");
