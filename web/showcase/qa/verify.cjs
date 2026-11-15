const { chromium, webkit } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
 const base = process.env.SHOWCASE_TEST_URL || 'http://127.0.0.1:8000/showcase/';
 for (const [name,engine] of [['chromium',chromium],['webkit',webkit]]) {
  const browser = await engine.launch({headless:true, executablePath:process.env[`${name.toUpperCase()}_EXECUTABLE`]});
  const page = await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
  const errors=[],badResponses=[],mutations=[],apiRequests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400)badResponses.push(r.url());});
  page.on('request',r=>{if(r.method()!=='GET')mutations.push(r.url());if(new URL(r.url()).pathname.startsWith('/api/'))apiRequests.push(r.url());});
  await page.goto(base);
  await page.locator('.hero-pager').evaluate(img=>img.decode());
  const slide=()=>page.locator('#main').getAttribute('data-slide');
  assert.equal(await slide(),'intro');
  assert.equal(await page.locator('.slide:not([hidden])').count(),1);
  await page.keyboard.press('ArrowLeft');assert.equal(await slide(),'intro');
  await page.keyboard.press('ArrowRight');assert.equal(await slide(),'problem');
  await page.keyboard.press('ArrowRight');assert.equal(await slide(),'product');
  await page.keyboard.press('PageDown');assert.equal(await slide(),'comparison');
  assert.equal(await page.locator('#product #live-product').count(),1);
  assert.equal(await page.locator('#live-product').count(),1);
  await page.keyboard.press('End');assert.equal(await slide(),'pricing');
  await page.keyboard.press('ArrowRight');assert.equal(await slide(),'pricing');
  await page.keyboard.press('Home');assert.equal(await slide(),'problem');
  await page.locator('.site-header .wordmark').click(); await page.waitForFunction(()=>document.querySelector('#main').dataset.slide === 'intro');assert.equal(await slide(),'intro');
  await page.locator('button[data-slide="product"]').click();
  assert.equal(await page.locator('#product #live-product').count(),1);
  const ids=['intro','problem','product','comparison','pricing'];
  const topics=['Welcome','The problem','The product','The comparison','Pricing'];
  let labelPosition;
  for (const id of ids) {
   if(id === 'intro') { if(await slide() !== 'intro') await page.locator('.site-header .wordmark').click(); await page.waitForFunction(()=>document.querySelector('#main').dataset.slide === 'intro'); } else await page.locator(`button[data-slide="${id}"]`).click();
   assert.equal(await slide(),id);
   assert.equal(await page.locator('#slide-topic').textContent(),id==='intro'?'':`${String(ids.indexOf(id)).padStart(2,'0')} / ${topics[ids.indexOf(id)]}`);
   const box=await page.locator('#slide-topic').boundingBox();
   if(labelPosition)assert.deepEqual({x:box.x,y:box.y},labelPosition);
   else labelPosition={x:box.x,y:box.y};
   assert.equal(await page.locator(`#${id}`).evaluate(el=>el.scrollWidth<=el.clientWidth),true,`${name}: horizontal slide overflow ${id}`);
   await page.screenshot({path:path.join(__dirname,`${name}-${id}.png`)});
  }
  assert.equal(await page.locator('a[href="/"]').count(),0);
  assert.equal(await page.locator('[data-finish],input[name="finish"]').count(),0);
  assert.equal(await page.locator('[data-price]').count(),0);
  assert.equal(await page.locator('.build-estimate strong').textContent(),'$25');
  assert.match(await page.locator('.first-user-plan').textContent(),/Cal Poly/);
  assert.equal(await page.locator('#price-heading').textContent(),'$59');
  assert.equal(await page.locator('#purchase-button').isDisabled(),false);
  assert.match(await page.locator('#purchase-button').textContent(),/Get PAIGER/);
  assert.equal(await page.locator('[data-shop]').count(),1);
  assert.equal(await page.locator('.cost-caveat').count(),0);
  assert.doesNotMatch(await page.locator('#main').textContent(),/prototype|demo|mock/i);
  await page.locator('[data-shop]').click();
  await page.keyboard.press('ArrowLeft');assert.equal(await slide(),'pricing','modal must not navigate deck');
  await page.locator('#quantity').selectOption('3');
  assert.equal(await page.locator('#order-total').textContent(),'$177 USD');
  assert.equal(await page.locator('#preview-order').isDisabled(),true);
  assert.equal(await page.locator('#preview-order').textContent(),'Out of stock');
  await page.locator('#preview-order').evaluate(el=>el.click());
  assert.equal(await page.locator('#shop-selection').isVisible(),true);
  assert.equal(await page.locator('#shop-review,#shop-confirmation').count(),0);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('[data-shop]').evaluate(el=>document.activeElement===el),true);
  await page.keyboard.press('Enter');
  for(let i=0;i<8;i++){await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>!!document.activeElement.closest('dialog')),true);}
  await page.keyboard.press('Escape');
  for(const [width,height] of [[320,700],[390,844],[768,720],[1024,768],[1440,720]]) {
   await page.setViewportSize({width,height});
   for(const id of ids){
    if(id === 'intro') { if(await slide() !== 'intro') await page.locator('.site-header .wordmark').click(); await page.waitForFunction(()=>document.querySelector('#main').dataset.slide === 'intro'); } else await page.locator(`button[data-slide="${id}"]`).click();
    assert.equal(await page.locator('.slide:not([hidden])').count(),1);
    assert.equal(await page.locator('#slide-topic').textContent(),id==='intro'?'':`${String(ids.indexOf(id)).padStart(2,'0')} / ${topics[ids.indexOf(id)]}`);
    assert.equal(await page.locator(`#${id}`).evaluate(el=>el.scrollWidth<=el.clientWidth),true,`${name}: slide ${id} overflow at ${width}`);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('.deck-controls').evaluate(el=>el.getBoundingClientRect().bottom<=innerHeight+1),true);
    if(width===390)await page.screenshot({path:path.join(__dirname,`${name}-mobile-${id}.png`)});
   }
   await page.locator('[data-shop]').click();
   assert.equal(await page.locator('#preview-order').isDisabled(),true);
   assert.equal(await page.locator('#shop-selection').isVisible(),true);
   if(width===390)await page.screenshot({path:path.join(__dirname,`${name}-mobile-checkout.png`)});
   await page.keyboard.press('Escape');
  }
  await page.goto(base+'#comparison');assert.equal(await slide(),'comparison','deep link');
  await page.keyboard.press('Home');assert.equal(await slide(),'problem');
  await page.locator('.site-header .wordmark').click(); await page.waitForFunction(()=>document.querySelector('#main').dataset.slide === 'intro');assert.equal(await slide(),'intro');
  await page.reload();assert.equal(await slide(),'intro');
  await page.goto(base+'#in-use');assert.equal(await slide(),'problem');
  assert.equal(await page.locator('#problem [data-pager]').count(),0);
  await page.goto(base+'#prototype');assert.equal(await slide(),'product');
  assert.equal(await page.locator('.product-steps,.product-specs').count(),0);
  assert.equal(await page.locator('#product .lead').textContent(),'Stay reachable without your phone');
  assert.equal(await page.locator('input').count(),0);
  assert.equal(await page.locator('.deck-controls button').count(),4);
  assert.equal(await page.locator('.deck-progress,.deck-arrows,.live-status').count(),0);
  assert.equal(await page.locator('#product-title').textContent(),'PAIGER');
  assert.equal(await page.locator('.deck-controls').evaluate(el=>getComputedStyle(el).borderTopWidth),'0px');
  assert.deepEqual(errors,[]);assert.deepEqual(badResponses,[]);assert.deepEqual(mutations,[]);assert.deepEqual(apiRequests,[]);
  console.log(`${name}: PASS — landing + four slides, arrow/Page/Home/End navigation, tabs, boundaries, deep links, shared-pager reuse, price math, checkout, keyboard/focus, responsive layouts, reduced motion, no API requests`);
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1);});
