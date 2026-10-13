/* Run against tests/browser_fixture.py with TGL_BROWSER_QUALITY=1.
   Only synthetic data; no messages are submitted. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({ignoreHTTPSErrors:true});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const base = 'https://127.0.0.1:8795';
    await page.goto(base + '/login');
    await page.getByLabel('E-Mail', {exact:true}).fill('browser@example.test');
    await page.getByLabel('Passwort', {exact:true}).fill('synthetic-browser-password');
    await page.getByRole('button', {name:'Anmelden', exact:true}).click();
    await page.waitForURL(base + '/');
    await page.goto(base + '/review');
    const search = page.getByLabel('In diesem Bereich suchen');
    await search.fill('EXCELLENT');
    assert.equal(await page.locator('[data-review-search]:visible').count(), 1);
    assert.equal(await page.locator('#review-result-count').textContent(), '1 von 2 Nachrichten');
    await search.fill('Kein passender Betreff');
    assert(await page.locator('#review-no-results').isVisible());
    await page.getByRole('button', {name:'Suche zurücksetzen'}).click();
    assert.equal(await search.inputValue(), '');
    assert.equal(await page.locator('[data-review-search]:visible').count(), 2);
    const draft = page.locator('#draft-2');
    await draft.getByText('Entwurf bearbeiten', {exact:true}).click();
    await draft.locator('textarea[name="body"]').fill('Ungespeicherter Testentwurf');
    await search.fill('Good');
    await search.fill('');
    assert.equal(await draft.locator('textarea[name="body"]').inputValue(), 'Ungespeicherter Testentwurf');
    await search.fill('Excellent');
    await page.evaluate(() => { location.hash = '#draft-1'; });
    await page.waitForFunction(() => document.querySelector('#draft-1').hidden === false);
    assert.equal(await search.inputValue(), '');
    assert(await page.locator('#draft-1 .context-details').evaluate(el => el.open));
    assert(await page.locator('#draft-1 button[value="approved"]').isDisabled());
    for (const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:960});
      for (const path of ['/contacts','/contacts/1','/opportunities?view=held','/review']) {
        await page.goto(base + path);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${path} at ${width}`);
        if (path === '/contacts' && width < 761) {
          assert(await page.locator('.contact-list').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
          assert(await page.getByText('Kontakt hinzufügen', {exact:true}).isVisible());
        }
        if (path.includes('view=held')) {
          assert.equal(await page.locator('.view-switch [aria-current="page"]').getAttribute('href'), '/opportunities?view=held');
        }
      }
    }
    assert.deepEqual(errors, []);
    console.log('Usability passed: search, empty state, reset, unsaved edits, deep links, held guards, mobile contacts, active occasion filters.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
