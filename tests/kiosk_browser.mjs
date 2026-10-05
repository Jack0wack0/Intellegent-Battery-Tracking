import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true});
try {
const page=await browser.newPage({viewport:{width:390,height:844}});
await page.goto('http://127.0.0.1:8765/');
await page.locator('#enrollForm input[name=name]').fill('Native Pit A');
await page.locator('#enrollForm input[name=brand]').fill('Test Battery');
await page.locator('#enrollForm input[name=purchaseDate]').fill('2025-01-01');
await page.locator('#enrollForm button').click();
await page.locator('#pullForm input[name=currentVoltage]').fill('12.7');
await page.locator('#pullForm button').click();
await page.waitForFunction(()=>document.querySelector('#pull').hidden);
await page.reload();
await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('connected'));
assert.equal(await page.locator('#pull').isVisible(),false);
const state=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
assert.equal(Object.keys(state.pullRequests).length,0);
assert.ok(state.pendingEvents>0);
await page.screenshot({path:process.env.KIOSK_SCREENSHOT || '/tmp/ibt-native-kiosk-mobile.png',fullPage:true});
console.log('PASS native offline enrollment → voltage-only pull → reload; durable cloud backlog retained');
} finally { await browser.close(); }
