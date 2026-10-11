/* Run against tests/browser_fixture.py only; all identities are synthetic. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({ignoreHTTPSErrors:true,acceptDownloads:true});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = 'https://127.0.0.1:8795';
  await page.goto(base+'/login');
  await page.getByLabel('E-Mail', {exact:true}).fill('browser@example.test');
  await page.getByLabel('Passwort', {exact:true}).fill('synthetic-browser-password');
  await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  await page.waitForURL(base+'/');
  await page.goto(base+'/settings');
  const style = page.getByLabel('Deine Schreibnotiz', {exact:true});
  assert.ok((await style.inputValue()).includes('keine Semikolons'));
  await style.fill((await style.inputValue())+'\nKurze Absätze verwenden.');
  await page.getByRole('button',{name:'Schreibnotiz speichern',exact:true}).click();
  await page.waitForURL(base+'/settings?writing_saved=1');
  assert.equal(await page.getByRole('status').innerText(),'Schreibnotiz gespeichert.');
  await page.reload();
  assert.ok((await page.getByLabel('Deine Schreibnotiz',{exact:true}).inputValue()).includes('Kurze Absätze verwenden.'));
  await page.goto(base+'/opportunities');
  assert.ok((await page.locator('main').innerText()).includes('Neuer Kontakt entdeckt'));
  await page.goto(base+'/contacts/1');
  assert.equal(await page.getByRole('link',{name:'Öffentliche Kontaktseite →',exact:true}).getAttribute('href'),'https://example.org/contact');
  await page.getByLabel('Betreff',{exact:true}).first().fill('A specific request');
  await page.getByLabel('Nachricht',{exact:true}).fill('Hello, could we discuss this research? Daniel');
  await page.getByRole('button',{name:'Zur Review-Queue'}).click();
  await page.waitForURL(base+'/review');
  await page.getByRole('button',{name:'Später',exact:true}).click();
  await page.waitForLoadState('networkidle');
  await page.getByText('Entwurf bearbeiten',{exact:true}).click();
  await page.getByLabel('Nachricht',{exact:true}).fill('Hello, could we exchange feedback on this research? Daniel');
  await page.getByRole('button',{name:'Ändern & erneut prüfen'}).click();
  await page.waitForLoadState('networkidle');
  await page.getByRole('button',{name:'Empfänger & Text freigeben'}).click();
  await page.waitForURL(base+'/review#draft-1');
  assert.ok((await page.locator('#draft-1 [role="status"]').innerText()).includes('Noch nicht versendet.'));
  assert.equal(await page.getByRole('button',{name:'Empfänger & Text freigeben'}).isVisible(), false);
  await page.waitForLoadState('networkidle');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button',{name:'Mailentwurf herunterladen'}).click();
  const download = await downloadPromise;
  assert.equal(download.suggestedFilename(),'draft-1.eml');
  for (const width of [1440,390,320]) {
    await page.setViewportSize({width,height:950});
    for (const route of ['/','/review','/contacts','/contacts/1','/opportunities','/outreach','/settings']) {
      const response=await page.goto(base+route);
      assert.equal(response.status(),200, route);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
      assert.equal(overflow,false,`${width} ${route} overflows`);
    }
    if (process.env.TGL_BROWSER_FIXTURE) {
      await page.goto(base+'/outreach');
      await page.screenshot({path:process.env.TGL_BROWSER_FIXTURE+`/outreach-${width}.png`,fullPage:true});
    }
  }
  await page.goto(base+'/review');
  await page.getByText('Tatsächlichen Versand bestätigen',{exact:true}).click();
  await page.getByLabel('Tatsächliches Versanddatum').fill('2026-10-10');
  await page.getByRole('button',{name:'Als versendet protokollieren'}).click();
  await page.waitForURL(base+'/contacts/1');
  await page.goto(base+'/opportunities');
  await page.getByRole('button',{name:'Alles vorbereiten',exact:true}).click();
  assert.ok((await page.getByRole('status').first().innerText()).includes('Vorbereitung eingeplant'));
  await page.getByRole('link',{name:'Zur Freigabe',exact:true}).waitFor({timeout:30000});
  await page.getByRole('link',{name:'Zur Freigabe',exact:true}).click();
  await page.waitForURL(base+'/review#draft-2');
  assert.equal(await page.locator('#draft-2 input[name="recipient"]').inputValue(), 'partner@example.test');
  assert.ok((await page.locator('#draft-2').innerText()).includes('A timely research conversation'));
  await page.getByRole('button',{name:'Abmelden',exact:true}).click();
  await page.waitForURL(base+'/login');
  assert.deepEqual(errors,[]);
  console.log('Browser flow passed: login, persisted writing note, draft, defer, edit, approve, export, synthetic send log, automatic opportunity package and live progress, logout; 21 responsive route checks.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
