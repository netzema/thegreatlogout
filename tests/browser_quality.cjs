/* Existing fixture with TGL_BROWSER_QUALITY=1, no real API or mail transport. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({ignoreHTTPSErrors:true});
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const base='https://127.0.0.1:8795';
    await page.goto(base+'/login');
    await page.getByLabel('E-Mail',{exact:true}).fill('browser@example.test');
    await page.getByLabel('Passwort',{exact:true}).fill('synthetic-browser-password');
    await page.getByRole('button',{name:'Anmelden',exact:true}).click();
    await page.waitForURL(base+'/');
    await page.goto(base+'/opportunities');
    assert.deepEqual(await page.locator('#opportunity-list article h2').allTextContents(),['Excellent match','Good match']);
    await page.getByRole('link',{name:'Vorerst zurückgestellt (1)'}).click();
    assert.deepEqual(await page.locator('#opportunity-list article h2').allTextContents(),['Weak match']);
    await page.goto(base+'/review');
    await page.locator('.review-filters:not([hidden])').waitFor();
    assert.equal(await page.locator('#draft-1').isVisible(),false);
    assert.deepEqual(await page.locator('.review-card:visible .message-preview h3').allTextContents(),['Excellent match','Good match']);
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:950});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    }
    await page.getByRole('button',{name:/Ohne tragfähigen Anlass/}).click();
    assert.equal(await page.locator('#draft-1').isVisible(),true);
    assert.equal(await page.locator('#draft-1 button[value="approved"]').isDisabled(),true);
    await page.goto(base+'/review#draft-1');
    assert.equal(await page.locator('#draft-1').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('Quality browser passed: ranking, recommended/held separation, approval guard, direct anchors, desktop/mobile. No mail sent.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
