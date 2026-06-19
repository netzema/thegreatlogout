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
  "Aufmerksamkeit ist ihre Währung.\nGeh nicht für sie pleite.",
  "Ich bereite mich darauf vor, diese Plattform zu verlassen.\nIch verschwinde nicht.",
  "Ich verlasse diese Plattform.\nIn den nächsten Tagen poste ich warum.",
  "Ich richte meine Aufmerksamkeit und meine Beziehungen woanders hin.",
  "Was denkst du wirklich?\nIch wette, du weißt es kaum noch.",
  "Sie nennen es Verbindung.\nAber du fühlst dich allein.",
  "Hol dir deine Zeit zurück.\nSie gehörte nie ihnen.",
  "Ich entscheide mich für echte Freunde.\nUnd du?",
  "Suchst du den Hausverstand?\nVersuch es mit Ausloggen.",
  "Der Feed weiß, was dich schwach hält.\nDarum kommt er immer wieder.",
  "Du schuldest einer Plattform nicht dein Leben.",
  "Sie verkaufen deine Aufmerksamkeit.\nUnd dann die Lösung dagegen.",
  "Du bist nicht faul.\nDu wirst gegen dich selbst designt.",
  "Du bist der Ort der Ausbeutung.",
  "Weniger Scrollen.\nMehr Leben.",
  "Deine Gedanken sind kein Marktplatz.",
  "Ich will nicht, dass ein paar Firmen jeden Tag entscheiden, was ich sehe.",
  "Sie haben Einsamkeit profitabel gemacht.",
  "Wenn es dich wütend, müde, neidisch und taub macht:\nWarum ist es noch auf deinem Handy?",
  "Du hörst dich selbst nicht,\nwährend der Feed schreit.",
  "Ich verschwinde nicht.\nIch kehre zurück.",
  "Offline ist nicht leer.\nOffline wartet das Leben.",
  "Das ist kein Detox.\nDas ist eine Verweigerung.",
  "Der Algorithmus kennt dich nicht.\nEr kennt deine Schwächen.",
  "Ich will meine Gedanken nicht vorsortiert bekommen.",
  "Das echte Leben hat keinen unendlichen Scroll.",
  "Ich verlasse den Feed,\nbevor er den Rest von mir frisst.",
  "Ich verlasse den Feed,\nnicht die Menschen.",
  "Du erreichst mich weiterhin hier: ...",
  "Sie wollen nicht dein Glück.\nSie wollen deine Rückkehr.",
  "Meine Aufmerksamkeit steht nicht zum Verkauf.",
  "Der Ausstieg ist die Botschaft.",
  "Ich habe mich ausgeloggt,\num zu mir zurückzukommen.",
  "Was, wenn deine Langeweile\ndich retten wollte?",
  "Es gibt nichts zu verpassen.\nDu wirst aktiv hineingezogen.",
  "Wenn der Feed mehr nimmt als gibt,\nwieso gehst du nicht?",
  "Poste warum.\nSag, wo man dich findet.\nDann log dich aus.",
  "Behalte deine Freunde.\nVerlier den Feed.",
  "Das ist mein letzter Post hier.\nFindet mich im echten Leben."
];

function deIndexScript() {
  let script = between(read("index.html"), "<script>", "</script>");
  script = script
    .replace('const typeLineOne = "Millions logged in.";', 'const typeLineOne = "Millionen haben sich eingeloggt.";')
    .replace('const typeLineTwo = "Now we log out.";', 'const typeLineTwo = "Jetzt loggen wir uns aus.";')
    .replace(/const postIdeas = \[[\s\S]*?\];/, `const postIdeas = ${JSON.stringify(dePostIdeas, null, 6)};`)
    .replace('logoImage.src = "assets/the-great-logout-mark.svg";', 'logoImage.src = "../assets/the-great-logout-mark.svg";')
    .replaceAll("A collective social media exit", "Ein gemeinsamer Social-Media-Ausstieg")
    .replaceAll("The exit is the message.", "Der Ausstieg ist die Botschaft.")
    .replace('language: "en"', 'language: "de"')
    .replace('custom.textContent = "Custom text";', 'custom.textContent = "Eigener Text";')
    .replace('button.textContent = "Use this";', 'button.textContent = "Verwenden";')
    .replace('signupStatus.textContent = "Signup is not connected yet.";', 'signupStatus.textContent = "Die Anmeldung ist noch nicht verbunden.";')
    .replace('signupStatus.textContent = "Adding you to the guide...";', 'signupStatus.textContent = "Du wirst zum Guide hinzugefügt...";')
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

  <title>The Great Logout - Eine öffentliche Kampagne für den gemeinsamen Social-Media-Ausstieg.</title>
  <meta name="description" content="The Great Logout ist eine öffentliche Kampagne für den Ausstieg aus süchtig machenden sozialen Medien. Poste deine Gründe für 1 bis 7 Tage. Dann log dich aus." />
  <link rel="canonical" href="${site}/de/" />
${altLinks({ en: "/", de: "/de/" })}

  <meta property="og:title" content="The Great Logout" />
  <meta property="og:description" content="Eine öffentliche Kampagne für den gemeinsamen Ausstieg aus süchtig machenden sozialen Medien." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${site}/de/" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta property="og:image:secure_url" content="${site}/assets/og-image.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content="The Great Logout - Poste warum du gehst. Dann geh." />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="The Great Logout" />
  <meta name="twitter:description" content="Eine öffentliche Kampagne für den gemeinsamen Ausstieg aus süchtig machenden sozialen Medien." />
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
          <div class="eyebrow">Eine öffentliche Kampagne für den Social-Media-Ausstieg</div>
          <h1>Verlass Social Media. Sichtbar.</h1>

          <p class="hero-copy">
            The Great Logout ist eine öffentliche Kampagne, um süchtig machende soziale Medien gemeinsam zu verlassen. <strong>Poste 1 bis 7 Tage lang klare Botschaften</strong>, sag warum du gehst, sag wo man dich erreicht, und log dich dann aus. Nicht leise. Sichtbar.
          </p>

          <div class="button-row">
            <a class="btn btn-primary" href="#start-guide">7-Tage-Guide starten</a>
            <a class="btn btn-secondary" href="#generator">Post erstellen</a>
          </div>

          <p class="campaign-note">
            <strong>Es geht um Sichtbarkeit.</strong> Menschen sehen deine Entscheidung, bevor du von den Plattformen verschwindest.
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
                  <strong>Poste deine Gründe.</strong>
                  <p>Ein Grund pro Tag. Kurz ist okay. Ehrlich ist besser.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Vor dem Ausstieg</span>
                <div>
                  <strong>Lass einen Weg zu dir offen.</strong>
                  <p>E-Mail, Telefon, Website, echtes Leben. Was zu dir passt.</p>
                </div>
              </li>
              <li class="formula-step">
                <span>Letzter Post</span>
                <div>
                  <strong>Log dich aus.</strong>
                  <p>Lösch die Apps, deaktiviere Accounts oder hör auf zu posten.</p>
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
            <h2>Ein kleiner öffentlicher Ausstiegsplan.</h2>
          </div>
        </div>

        <div class="steps">
          <article class="step"><div><h3>Wähle 1, 3 oder 7 Tage.</h3><p>Nimm eine Länge, die du wirklich schaffst. Sieben Tage geben anderen Zeit, es zu bemerken.</p></div></article>
          <article class="step"><div><h3>Poste jeden Tag einen Grund.</h3><p>Schreib wie ein Mensch. Sag, was dich der Feed gekostet hat und was du zurückhaben willst.</p></div></article>
          <article class="step"><div><h3>Sag, wo man dich erreicht.</h3><p>Verschwinde nicht aus dem Leben von Menschen, die dir wichtig sind. Bring die Beziehung aus der Plattform heraus.</p></div></article>
          <article class="step"><div><h3>Lösch die Apps oder deaktiviere.</h3><p>Mach den Rückfall schwerer. Entferne die Abkürzung. Brich den Reflex.</p></div></article>
          <article class="step"><div><h3>Bleib draußen und hilf anderen dabei.</h3><p>Wenn jemand fragt, warum du gegangen bist, sag es einfach. So verbreitet sich das Signal.</p></div></article>
        </div>

        <div class="how-cta">
          <div>
            <h3>Bereit, es konkret zu machen?</h3>
            <p>Der Guide gibt dir Prompts, ein Ausstiegsdatum und spätere Check-ins.</p>
          </div>
          <a class="btn btn-primary" href="#start-guide">Heute starten</a>
        </div>
      </div>
    </section>

    <section id="why">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Verloren im Scrollen</div><h2>Warum Ausloggen mehr ist als weniger Handyzeit.</h2></div></div>
        <div class="why-case">
          <p><strong>The Great Logout ist eine öffentliche Verweigerung.</strong> Nicht weil jeder Teil des Internets schlecht ist. Sondern weil die dominanten Plattformen zu süchtig machend, zu mächtig und zu normal geworden sind.</p>
          <p>Der Essay bündelt 13 Gründe: süchtig machende Feeds, algorithmische Macht, Big Tech, Konsumdruck, passive Öffentlichkeit, Einsamkeit, Politik, Kultur und den leisen Diebstahl von Aufmerksamkeit.</p>
          <p>Der Punkt ist einfach: Hör auf, Systeme zu füttern, die Aufmerksamkeit, Wut, Einsamkeit, Unsicherheit und Gewohnheit in Profit verwandeln.</p>
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
              <div class="field"><label for="postText">Text bearbeiten</label><textarea id="postText">Aufmerksamkeit ist ihre Währung.
Geh nicht für sie pleite.</textarea></div>
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
            <h2>Eine Woche Posts. Dann der Logout.</h2>
            <p class="lead">Der Guide gibt dir jeden Tag einen klaren Impuls. Nutze ihn genau so, ändere ihn oder ignoriere die Hälfte. Wichtig ist: Du kommst raus.</p>
            <div class="guide-days">
              <article class="guide-day"><span>Tag 0</span><div><h3>Ausstieg vorbereiten</h3><p>Kontakte sichern, letzten Tag wählen und entscheiden, wo man dich erreicht.</p></div></article>
              <article class="guide-day"><span>Tag 1</span><div><h3>Warum ich gehe</h3><p>Beginne klar. Sag, dass es Absicht ist.</p></div></article>
              <article class="guide-day"><span>Tag 2</span><div><h3>Was der Feed mit meiner Aufmerksamkeit gemacht hat</h3><p>Benenne den Sog, das Wegdriften und die Zeit, die du zurückwillst.</p></div></article>
              <article class="guide-day"><span>Tag 3</span><div><h3>Was ich zurückhaben will</h3><p>Mehr Ruhe. Mehr Fokus. Mehr echte Menschen. Dein Grund gehört dir.</p></div></article>
              <article class="guide-day"><span>Tag 4</span><div><h3>Warum Big Tech zu viel Macht hat</h3><p>Sag, was ein paar Firmen nicht für dich entscheiden sollen.</p></div></article>
              <article class="guide-day"><span>Tag 5</span><div><h3>Wo man mich erreicht</h3><p>Gib Menschen einen anderen Weg. Behalte die Verbindung. Lass den Feed los.</p></div></article>
              <article class="guide-day"><span>Tag 6</span><div><h3>Andere einladen</h3><p>Kein Druck. Mach nur die Tür sichtbar.</p></div></article>
              <article class="guide-day"><span>Tag 7</span><div><h3>Letzter Post und Logout</h3><p>Poste die letzte Nachricht. Lösch die Apps. Geh.</p></div></article>
            </div>
          </div>

          <aside class="signup-card guide-signup" id="start-guide" aria-labelledby="signup-title">
            <h3 id="signup-title">Starte deinen Logout heute</h3>
            <p>Poste 1 bis 7 Tage. Dann log dich aus.</p>
            <p class="signup-link">Brauchst du zuerst einen Post? <a href="#generator">Zum Post-Generator.</a></p>
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
        <div class="manifesto"><p>Wir gehen, weil Plattformen zu Maschinen für Sucht, Empörung, Überwachung und Kontrolle geworden sind. The Great Logout ist nicht gegen Kreative. Es ist eine Weigerung, Plattformen weiter mit unserer Zeit, Wut, Freundschaft und Aufmerksamkeit zu füttern.</p></div>
      </div>
    </section>

    <section id="support">
      <div class="wrap">
        <div class="section-head"><div><div class="kicker">Unterstützen</div><h2>Hilf, die Kampagne unabhängig zu halten.</h2></div></div>
        <div class="support-grid">
          <div class="support-copy">
            <p>The Great Logout soll einfach, öffentlich und frei nutzbar bleiben. Wenn du helfen willst, kannst du die Seite teilen, den Generator benutzen, den Guide weitergeben oder die laufenden Kosten unterstützen.</p>
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
        <p>Poste warum. Sag, wo man dich findet. Dann log dich aus.</p>
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
  <meta name="description" content="Ein Essay über süchtig machende Algorithmen, Big-Tech-Macht, Aufmerksamkeit, Konsumdruck, passive Öffentlichkeit und warum The Great Logout existiert." />
  <link rel="canonical" href="${site}/de/essay.html" />
${altLinks({ en: "/essay.html", de: "/de/essay.html" })}
  <meta property="og:title" content="13 Gründe, dich auszuloggen" />
  <meta property="og:description" content="Warum The Great Logout existiert und warum Social Media zu verlassen eine öffentliche Verweigerung sein kann." />
  <meta property="og:type" content="article" />
  <meta property="og:url" content="${site}/de/essay.html" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="13 Gründe, dich auszuloggen" />
  <meta name="twitter:description" content="Warum Social Media zu verlassen eine öffentliche Verweigerung sein kann." />
  <meta name="twitter:image" content="${site}/assets/og-image.png" />
  <link rel="icon" href="../assets/favicon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="../assets/apple-touch-icon.png" />
  <style>${style}</style>
</head>
<body>
  <header class="site-header"><div class="wrap nav"><a class="brand" href="index.html" aria-label="The Great Logout Startseite"><img src="../assets/the-great-logout-mark.svg" alt="" decoding="async" /><span>The Great Logout</span></a><nav class="nav-links" aria-label="Hauptnavigation"><a href="index.html#how">So geht es</a><a href="index.html#why">Warum?</a><a href="index.html#generator">Post-Generator</a><a href="index.html#guide">7-Tage-Guide</a><a href="index.html#support">Unterstützen</a><a class="language-switch" href="../essay.html" hreflang="en" lang="en">EN</a><a href="index.html#start-guide" class="nav-cta">Start</a></nav></div></header>
  <main>
    <section class="hero"><div class="wrap"><div class="kicker">Essay</div><h1>13 Gründe, dich auszuloggen</h1><p class="intro">Es geht nicht nur darum, weniger Zeit am Handy zu verbringen. Der Feed prägt Aufmerksamkeit, Politik, Kultur, Konsum und das innere Wetter in unseren Köpfen. The Great Logout ist eine öffentliche Verweigerung, diese Maschine weiter zu füttern.</p><div class="meta" aria-label="Artikeldetails"><span>Von <a href="https://www.danielnetzl.at" target="_blank" rel="noopener">Daniel Netzl</a></span><span>Februar 2025</span><span>Für The Great Logout aktualisiert</span></div></div></section>
    <article><div class="wrap essay">
      <p>Über manche Süchte sprechen wir inzwischen klar: Alkohol, Zigaretten, Glücksspiel, Medikamente. Ihr Schaden ist sichtbar genug, dass wir Warnungen, Regeln, Altersgrenzen und Unterstützung entwickelt haben.</p>
      <p>Eine der stärksten Süchte unserer Zeit liegt aber in der Tasche. Sie leuchtet, aktualisiert sich, studiert dich und bietet immer noch einen Clip, eine Empörung, einen Vergleich, einen Kaufimpuls, einen Grund zu bleiben.</p>
      <p>Der Feed wirkt harmlos, weil er alltäglich geworden ist. Genau das ist Teil seiner Macht.</p>
      <h2>1. Deine Aufmerksamkeit wird abgeschöpft</h2><p>Aufmerksamkeit ist nichts Kleines. Sie ist die Art, wie wir ein Leben bauen: zuhören, lernen, lieben, denken, bemerken, schaffen, trauern, organisieren und verändern.</p><p>Die großen Plattformen behandeln diese Aufmerksamkeit als Rohstoff. Deine Pause, deine Wut, deine Neugier, deine Einsamkeit, deine Freundschaften, deine späte Schwäche in der Nacht. Alles wird messbar und in ein System zurückgespeist, das lernt, dich länger zu halten.</p>
      <h2>2. Der Feed wurde gebaut, damit du zurückkommst</h2><p>TikTok, Instagram, YouTube, Facebook, X und ähnliche Plattformen sind keine neutralen Räume. Sie sind Sortiermaschinen. Sie entscheiden, was erscheint, was verschwindet, was wiederholt wird und welche Stimmung der Tag bekommt.</p><p>Das Geschäftsmodell ist einfach: Menschen schauen lassen, reagieren lassen, zurückholen. Mehr Aufmerksamkeit heißt mehr Daten. Mehr Daten heißt bessere Zielgruppen. Bessere Zielgruppen heißen mehr Geld.</p>
      <div class="pull">Ein paar Unternehmen sitzen heute zwischen Milliarden Menschen und Wirklichkeit. Das ist zu viel Macht.</div>
      <h2>3. Big Tech wurde zu einer privaten Schicht über dem öffentlichen Leben</h2><p>Eine Handvoll Konzerne prägt, was Milliarden Menschen sehen, glauben, wollen, fürchten und diskutieren. Sie beeinflussen Wahlen, Beziehungen, Nachrichten, Kultur, Mode, Sprache, Humor, Musik, Empörung und Schönheitsideale.</p><p>Diese Macht sieht nicht immer aus wie Politik. Aber sie entscheidet, welche Stimmen steigen, welche begraben werden, was relevant erscheint und welche Konflikte am Leben bleiben, weil sie gut performen.</p>
      <h2>4. Empörung wird belohnt</h2><p>Algorithmen müssen nicht jede Lüge und jeden Konflikt erfinden. Sie müssen nur finden, was Menschen bindet, und es stärker ausspielen. Wut ist nützlich. Gewissheit ist nützlich. Stammesdenken ist nützlich. Nuance ist meistens zu langsam.</p><p>So verlieren Menschen einen gemeinsamen Boden. Jede Person sieht eine andere Welt, abgestimmt auf Ängste, Geschmack, Wunden und Schwächen.</p>
      <h2>5. Deine Langeweile wird kolonisiert</h2><p>Langeweile war einmal ein Teil des Lebens: warten, gehen, im Zug sitzen, in einer Schlange stehen, den Geist ohne Auftrag wandern lassen.</p><p>Diese Momente sind oft der Ort, an dem Ideen sich verbinden und man merkt, was man eigentlich als Nächstes tun will. Der Feed greift genau diesen Raum an.</p>
      <h2>6. Vergleich wurde normal</h2><p>Der Feed zeigt Körper, Wohnungen, Beziehungen, Reisen, Routinen, Gesichter, Karrieren und Lebensstile so angeordnet, dass ein Gefühl von Mangel entsteht.</p><p>Menschen wissen, dass vieles bearbeitet ist. Das macht es nicht harmlos. Wiederholung arbeitet unterhalb der Argumente.</p>
      <h2>7. Einsamkeit ist profitabel</h2><p>Plattformen versprechen Verbindung, liefern aber oft Kontakt ohne Nähe. Du kannst hunderte Menschen beobachten und dich trotzdem allein fühlen. Du kannst den ganzen Tag erreichbar sein und trotzdem nicht gekannt werden.</p><p>Die Antwort ist nicht Isolation. Die Antwort ist, Beziehungen wieder in Kanäle zu bringen, die keine Sucht brauchen, um zu überleben.</p>
      <h2>8. Politik wird Performance</h2><p>Ein Like kann sich wie eine Haltung anfühlen. Ein Repost kann sich wie Mut anfühlen. Ein Kommentar kann sich wie Handlung anfühlen. Manchmal hilft das. Oft ersetzt es das Tun außerhalb der Plattform.</p><p>Eine Gesellschaft kann den ganzen Tag wütend sein und trotzdem still bleiben.</p>
      <div class="pull">Eine Gesellschaft kann den ganzen Tag wütend sein und trotzdem still bleiben.</div>
      <h2>9. Kultur wird flacher</h2><p>Der Feed ist nicht gut in Tiefe. Er ist gut in Verbreitung. Was am schnellsten reist, beginnt so auszusehen, als wäre es am wichtigsten.</p><p>Das verändert Kunst, Sprache, Humor, Musik, Politik und sogar Persönlichkeit. Menschen formen sich für das System, das sie belohnt.</p>
      <h2>10. Menschen werden passiv gehalten</h2><p>Die Plattformen zersplittern unseren gemeinsamen Horizont. Jede Person erhält eine private Version der Wirklichkeit, optimiert auf Engagement und kurzfristige Emotion.</p><p>Wir brauchen aktive Gemeinschaften, nicht nur informierte Zuschauerinnen und Zuschauer. Wir brauchen Menschen, die zusammensitzen, widersprechen, planen, protestieren, füreinander sorgen und Alternativen bauen.</p>
      <h2>11. Begehren wird hergestellt</h2><p>Dieselben Systeme, die Meinung formen, formen auch Wünsche. Sie laden dich ein zu glauben, Erfüllung sei nur einen Kauf, eine Reise, ein Upgrade oder eine bessere Version von dir entfernt.</p><p>Diese Rastlosigkeit treibt Konsum, Müll, Vergleich, Schulden und ökologische Schäden.</p>
      <h2>12. Beziehungen werden durch Maschinen geleitet</h2><p>Viele bleiben, weil Gehen sich wie Verschwinden anfühlt. Diese Angst ist real. Plattformen haben sich zwischen Freundschaften, Familien, Kunst, Organisation, Kundschaft und Gemeinschaften geschoben.</p><p>Wenn die Beziehung wichtig ist, gib ihr einen direkten Weg: E-Mail, Signal, Telefon, Website, Newsletter, Tisch, Raum, echtes Leben.</p>
      <h2>13. Ein sichtbarer Ausstieg gibt anderen Erlaubnis</h2><p>Leise zu gehen ist gut für die Person, die geht. Öffentlich zu gehen ist nützlich für alle anderen.</p><p>Wenn du einfach verschwindest, schluckt die Plattform deine Abwesenheit. Wenn du aber postest, warum du gehst, sehen andere einen Ausgang. Sie sehen, dass Ausloggen öffentlich, bewusst und sozial sein kann.</p><p>Du brauchst kein perfektes Argument. Sag, warum du gehst. Sag, wo man dich erreicht. Dann geh.</p>
      <div class="action-box"><h2>Der Ausstieg ist die Botschaft</h2><p>The Great Logout ist nicht gegen das Internet. Es richtet sich gegen Plattformen, die Sucht, Empörung, Überwachung, Einsamkeit und Unsicherheit in ein Geschäftsmodell verwandeln.</p><p>Wenn dieser Essay dir geholfen hat, den Feed anders zu sehen, nutze diese Klarheit. Mach einen Post. Starte den Guide. Unterstütze die Kampagne, wenn du kannst.</p><div class="button-row"><a class="btn btn-primary" href="index.html#guide">Logout starten</a><a class="btn btn-secondary" href="index.html#generator">Post erstellen</a><a class="btn btn-secondary" href="https://ko-fi.com/thegreatlogout" target="_blank" rel="noopener">Auf Ko-fi unterstützen</a></div></div>
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
  <meta name="description" content="Datenschutzerklärung für The Great Logout, einschließlich E-Mail-Guide, Post-Generator und Spendenlinks." />
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
      <div class="legal-card"><p><strong>Kurzfassung:</strong> The Great Logout fragt nur nach den Daten, die für den E-Mail-Guide nötig sind. Der Post-Generator läuft in deinem Browser. Wir verwenden keine Tracking-Werbung, keine Analytics-Cookies und kein Profiling auf dieser Website.</p></div>
      <h2>Verantwortlicher</h2><p>Verantwortlich für diese Website ist:</p><p>The Great Logout<br />Eine Kampagne von Daniel Netzl<br />Landstraße 47<br />2464 Göttlesbrunn<br />Österreich<br /><a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a></p>
      <h2>Welche Daten wir erheben</h2><p>Wenn du dich für den E-Mail-Guide anmeldest, verarbeiten wir die von dir eingegebenen Daten:</p><ul><li>E-Mail-Adresse</li><li>optional Vorname</li><li>optional geplantes Logout-Datum</li><li>gewählte Guide-Länge</li><li>Einwilligung zum Erhalt des Guides</li></ul><p>Für Versand und Abmeldung speichern wir außerdem technische Datensätze wie Abmelde-Token, Anmeldezeit, Abmeldezeit, Versandstatus, Zustell-IDs und Fehlermeldungen, soweit nötig.</p>
      <h2>Warum wir diese Daten verwenden</h2><p>Wir verwenden diese Daten, um den Logout-Guide, spätere Check-ins und verwandte Kampagnen-E-Mails zu senden, die du angefordert hast. Rechtsgrundlage ist deine Einwilligung nach Art. 6 Abs. 1 lit. a DSGVO.</p><p>Begrenzte technische Daten können außerdem verarbeitet werden, um Website und E-Mail-System zu betreiben, abzusichern und zu verbessern. Rechtsgrundlage ist unser berechtigtes Interesse nach Art. 6 Abs. 1 lit. f DSGVO.</p>
      <h2>E-Mail-Guide und Abmeldung</h2><p>Du kannst dich jederzeit über den Abmeldelink in jeder E-Mail vom Guide abmelden. Du kannst uns auch unter <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a> kontaktieren.</p><p>Nach einer Abmeldung senden wir keine Guide-E-Mails mehr. Eine begrenzte Dokumentation der Abmeldung kann gespeichert bleiben, um weitere Zusendungen zu vermeiden und die Einwilligungshistorie zu dokumentieren.</p>
      <h2>Post-Generator</h2><p>Der Post-Generator läuft in deinem Browser. Text, den du eingibst, wird verwendet, um das herunterladbare Bild auf deinem Gerät zu erstellen.</p><p>Einige E-Mail-Links können den Generator öffnen oder ein SVG über die Kampagnen-API anfordern. Dabei können ausgewählter Text, Format und Farbe in der URL enthalten sein, damit die Datei erzeugt werden kann.</p>
      <h2>Dienstleister</h2><p>Wir nutzen Dienstleister für den Betrieb der Kampagne:</p><ul><li>GitHub Pages für das Hosting der statischen Website</li><li>Cloudflare für DNS, Sicherheit und die E-Mail-Anmelde-API</li><li>Cloudflare D1 zur Speicherung von Guide-Anmeldungen</li><li>Postmark für Transaktions- und Guide-E-Mails</li><li>Ko-fi für freiwillige Beiträge, wenn du die Kampagne dort unterstützt</li></ul><p>Wenn du diese Website über externe Links verlässt, gilt die Datenschutzerklärung des jeweiligen externen Dienstes.</p>
      <h2>Cookies und Analytics</h2><p>Derzeit verwendet diese Website keine Analytics-Cookies, Werbe-Cookies oder Tracking-Pixel. Falls sich das ändert, wird diese Erklärung aktualisiert.</p>
      <h2>Server-Logs</h2><p>Hosting-, DNS-, Sicherheits- und E-Mail-Anbieter können technische Daten wie IP-Adresse, Anfragezeit, Browserinformationen, angeforderte URL und Versandprotokolle verarbeiten, um ihre Dienste bereitzustellen und zu schützen. Wir verwenden diese Daten nicht, um Besucherinnen oder Besucher zu profilieren.</p>
      <h2>Speicherdauer</h2><p>Daten zum E-Mail-Guide werden gespeichert, solange dein Abo aktiv ist. Nach einer Abmeldung speichern wir nur, was nötig ist, um die Abmeldung zu respektieren, Versandnachweise zu erhalten und rechtliche oder betriebliche Fragen zu klären. Du kannst jederzeit Löschung verlangen.</p>
      <h2>Deine Rechte</h2><p>Nach der DSGVO kannst du Auskunft, Berichtigung, Löschung, Einschränkung oder Widerspruch gegen die Verarbeitung deiner personenbezogenen Daten verlangen. Du kannst eine Einwilligung jederzeit widerrufen.</p><p>Zur Ausübung deiner Rechte kontaktiere <a href="mailto:support@thegreatlogout.org">support@thegreatlogout.org</a>. Du hast außerdem das Recht, Beschwerde bei einer Datenschutzbehörde einzulegen.</p>
      <h2>Änderungen</h2><p>Wir können diese Datenschutzerklärung aktualisieren, wenn sich Kampagne, Website oder E-Mail-System ändern. Das Datum oben zeigt die aktuelle Version.</p>
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
  <meta name="description" content="Impressum und Kontaktinformationen für The Great Logout." />
  <link rel="canonical" href="${site}/de/imprint.html" />
${altLinks({ en: "/imprint.html", de: "/de/imprint.html" })}
  <meta property="og:title" content="Impressum | The Great Logout" />
  <meta property="og:description" content="Impressum und Kontaktinformationen für The Great Logout." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="${site}/de/imprint.html" />
  <meta property="og:image" content="${site}/assets/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Impressum | The Great Logout" />
  <meta name="twitter:description" content="Impressum und Kontaktinformationen für The Great Logout." />
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
      <h2>Externe Links</h2><p>Diese Website kann auf externe Websites verlinken. Für Inhalte, Verfügbarkeit oder Datenschutzpraktiken externer Websites übernehmen wir keine Verantwortung.</p>
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
