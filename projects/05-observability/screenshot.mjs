import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(resolve('apps/copilot/package.json'));
const { chromium } = require('playwright');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const browser = await chromium.launch({ executablePath: config.chromiumPath, headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--lang=en-US'] });
try {
  // Explicit BCP 47 locale prevents this executor's en-US@posix locale from
  // stopping Grafana's Intl initialization before its login form can render.
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  await page.goto(`${config.url}/login`);
  await page.locator('input[name="user"]').fill('admin');
  await page.locator('input[name="password"]').fill(config.password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await page.waitForURL(url => url.pathname !== '/login');
  await page.goto(`${config.url}/d/pais-operations/pais-application-reliability?from=now-5m&to=now&refresh=5s`);
  await page.getByText('Request volume', { exact: true }).waitFor({ timeout: 30000 });
  await page.waitForTimeout(5000);
  await page.screenshot({ path: config.output, fullPage: true });
  process.stdout.write(JSON.stringify({ screenshot: config.output, title: await page.title() }));
} finally {
  await browser.close();
}
