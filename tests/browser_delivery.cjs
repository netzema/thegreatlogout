/* Isolated fixture with TGL_BROWSER_DIRECT_SEND=1; transport is synthetic. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({ignoreHTTPSErrors:true});
  const threaded=process.env.TGL_BROWSER_THREAD==='1';
  const expectedSubject=threaded ? 'Re: Existing conversation' : 'Direct delivery fixture';
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base='https://127.0.0.1:8795';
  await page.goto(base+'/login');
  await page.getByLabel('E-Mail',{exact:true}).fill('browser@example.test');
  await page.getByLabel('Passwort',{exact:true}).fill('synthetic-browser-password');
  await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  await page.waitForURL(base+'/');
  await page.goto(base+'/contacts/1');
  if(threaded) assert.equal(await page.locator('select[name="reply_message_id"]').inputValue(),'1');
  await page.getByLabel('Betreff',{exact:true}).first().fill('Direct delivery fixture');
  await page.getByLabel('Nachricht',{exact:true}).fill('Hello,\n\nyour research fits this conversation.\n\nDaniel');
  await page.getByRole('button',{name:'Zur Review-Queue'}).click();
  await page.waitForURL(base+'/review');
  if(threaded) {
    assert.equal(await page.getByText('Antwort im bisherigen Verlauf',{exact:true}).count(),1);
    assert.equal(await page.getByRole('link',{name:'Bezugsnachricht ansehen →'}).getAttribute('href'),'/contacts/1#message-1');
  }
  assert.equal(await page.getByRole('button',{name:'Jetzt senden',exact:true}).count(),0);
  await page.getByRole('button',{name:'Empfänger & Text freigeben'}).click();
  await page.waitForURL(base+'/review#draft-1');
  const csrf=await page.locator('form[action="/drafts/1/send"] input[name="csrf"]').inputValue();
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:950});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert.equal(await page.getByRole('button',{name:'Jetzt senden',exact:true}).isVisible(),true);
  }
  await page.getByRole('button',{name:'Jetzt senden',exact:true}).click();
  await page.waitForURL(base+'/contacts/1?delivery=1');
  assert.ok((await page.getByRole('status').innerText()).includes('Vom Mailserver zum Versand angenommen'));
  assert.ok((await page.locator('main').innerText()).includes('Kopie im Ordner Gesendet abgelegt.'));
  assert.equal(await page.getByRole('heading',{name:expectedSubject,exact:true}).count(),1);
  const repeat=await page.request.post(base+'/drafts/1/send',{headers:{Origin:base},form:{csrf,version:'2',confirm:'send'}});
  assert.equal(repeat.status(),200);
  await page.reload();
  assert.equal(await page.getByRole('heading',{name:expectedSubject,exact:true}).count(),1);
  await page.goto(base+'/review');
  assert.equal(await page.getByRole('button',{name:'Jetzt senden',exact:true}).count(),0);
  assert.deepEqual(errors,[]);
  await browser.close();
  console.log((threaded ? 'Threaded ' : '') + 'Direct delivery browser passed: approval, recipient, explicit send, confirmation, Sent copy, duplicate request, mobile widths. No real message sent.');
})().catch(e=>{console.error(e);process.exit(1);});
