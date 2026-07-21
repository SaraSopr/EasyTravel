import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 3 });

await page.goto('http://localhost:5176/demo', { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
await page.keyboard.press('3');
await page.waitForTimeout(1500);
for (let i = 0; i < 4; i++) {
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(1200);
}

const rows = await page.$$('.realism-timeline-row');
console.log('rows found:', rows.length);

// Dump all segments (kind, title, style left/width) for each row
const info = await page.evaluate(() => {
  const rows = document.querySelectorAll('.realism-timeline-row');
  return Array.from(rows).map(row => {
    const segs = row.querySelectorAll('.tl-segment');
    return Array.from(segs).map(seg => ({
      cls: seg.className,
      title: seg.getAttribute('title'),
      left: seg.style.left,
      width: seg.style.width,
      text: seg.textContent,
    }));
  });
});
console.log(JSON.stringify(info, null, 2));

await el2Shot(page);
async function el2Shot(page) {
  const el = await page.$('.demo-bottom.realism-audit-timelines');
  await el.screenshot({ path: '/tmp/step5_timelines_hd.png' });
}

await browser.close();
