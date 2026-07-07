import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

await page.goto('http://localhost:5176/demo', { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
await page.keyboard.press('3');
await page.waitForTimeout(1500);
for (let i = 0; i < 4; i++) {
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(600);
}
await page.waitForTimeout(3000); // let all GSAP animations finish
await page.screenshot({ path: '/tmp/greedy_step5_final.png', fullPage: true });
await browser.close();
