const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const root = path.resolve(option('--site', path.join(__dirname, '..', 'site')));
const out = option('--out', '');
const widths = option('--widths', '360').split(',').map(Number);
const chromePath = process.env.CHROME || '/usr/bin/google-chrome-stable';
let hasChrome = true;
try { fs.accessSync(chromePath, fs.constants.X_OK); } catch (_) { hasChrome = false; }
if (!hasChrome) { console.log('SKIP mobile overflow: Chrome is absent'); process.exit(0); }
// Run from any directory; --site, --widths and --out also support a populated audit copy.
const now = Math.floor(Date.now() / 1000);
const fixtures = {
  '/packages.json': { schema: 4, generated: now, packages: [
    { cp: 'app-i18n/fcitx-rime', binhost: true, dist: ['fcitx-rime.tar.gz'] },
    { cp: 'media-fonts/iansui', binhost: true, dist: [] }
  ], deps: [{ cp: 'app-i18n/librime', slot: '0', ver: '1.16.0', size: 1234567 }] },
  '/distfiles-index.json': { generated: now, files: ['fcitx-rime.tar.gz'] },
  '/binpkgs/x86-64/Packages': `TIMESTAMP: ${now}\n\nCPV: app-i18n/fcitx-rime-0.3.3\nSIZE: 123456\n\n`,
  '/build-status.json': { state: 'done', phase: 'done', started: now - 6000, finished: now, duration: 6000, progress_at: now, generated: now },
  '/build-status-unstable.json': { state: 'done', phase: 'done', started: now - 6000, finished: now, duration: 6000, progress_at: now, generated: now },
  '/server-status.json': { uptime: 4771919, rx: 310287447560, tx: 1127324821421, generated: now },
  '/_ls/distfiles/': [
    { name: 'rime-data-with-a-long-file-name-1.0.tar.gz', type: 'file', size: 1234567, mtime: '2026-09-30T00:00:00Z' },
    { name: 'source', type: 'directory', mtime: '2026-09-30T00:00:00Z' }
  ]
};
const geometry = `(() => {
  const id = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().replace(/\\s+/g, '.') : '');
  const box = e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right }; };
  const scrollAncestor = e => { for (let a = e.parentElement; a; a = a.parentElement) if (['auto', 'scroll'].includes(getComputedStyle(a).overflowX)) return id(a); return null; };
  const elements = [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().width && getComputedStyle(e).visibility !== 'hidden');
  const overflow = elements.filter(e => e.getBoundingClientRect().right > innerWidth + 0.01 && !scrollAncestor(e)).map(e => ({ element: id(e), text: e.textContent.trim().slice(0, 70), ...box(e) }));
  const title = document.querySelector('.toc-pick');
  const tools = document.querySelector('.nav-tools');
  const titleOverlap = title && title.getBoundingClientRect().width && tools && title.getBoundingClientRect().right > tools.getBoundingClientRect().left - 4;
  return { viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth, pageOverflow: document.documentElement.scrollWidth > innerWidth, overflow, titleOverlap: !!titleOverlap,
    lang: document.documentElement.lang, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
    boxes: elements.filter(e => e.matches('main, .nav, .nav-tools, .toc-pick, .code, .code pre, .fpr, table, .table-scroll')).map(e => ({ element: id(e), ...box(e) })),
    scrollers: elements.filter(e => ['auto','scroll'].includes(getComputedStyle(e).overflowX) && e.scrollWidth > e.clientWidth).map(e => ({ element: id(e), clientWidth: e.clientWidth, scrollWidth: e.scrollWidth, ...box(e) })),
    rows: document.querySelectorAll('tbody tr').length };
})()`;
(async () => {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    let file = path.join(root, url);
    if (url === '/distfiles/') file = path.join(root, '_app.html');
    else if (url.endsWith('/')) file = path.join(file, url.startsWith('/_ls/') ? 'index.json' : 'index.html');
    else if (!path.extname(url) && !fs.existsSync(file)) file += '.html';
    if (fs.existsSync(file) && fs.statSync(file).isFile()) {
      const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };
      res.setHeader('Content-Type', types[path.extname(file)] || 'text/plain'); res.end(fs.readFileSync(file));
    } else if (fixtures[url] !== undefined || url.endsWith('/status.json') || url.endsWith('-status.json')) {
      const value = fixtures[url] === undefined ? { generated: now, timestamp: now, packages: 12 } : fixtures[url];
      res.setHeader('Content-Type', typeof value === 'string' ? 'text/plain' : 'application/json');
      res.end(typeof value === 'string' ? value : JSON.stringify(value));
    } else { res.statusCode = 404; res.end(); }
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const origin = `http://127.0.0.1:${server.address().port}`;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mobile-chrome-'));
  const chrome = spawn(chromePath, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-background-networking', '--no-first-run', '--no-default-browser-check', '--remote-debugging-pipe', `--user-data-dir=${profile}`], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const exited = once(chrome, 'exit');
  let seq = 0, buffer = '', session;
  const pending = new Map(), listeners = new Map();
  const call = (method, params = {}, browser = false) => new Promise((resolve, reject) => {
    const id = ++seq;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
    pending.set(id, { resolve, reject, timer });
    chrome.stdio[3].write(JSON.stringify({ id, method, params, ...(session && !browser ? { sessionId: session } : {}) }) + '\0');
  });
  const on = (method, fn) => { if (!listeners.has(method)) listeners.set(method, new Set()); listeners.get(method).add(fn); return () => listeners.get(method).delete(fn); };
  chrome.stdio[4].on('data', data => {
    buffer += data.toString();
    let end;
    while ((end = buffer.indexOf('\0')) !== -1) {
      const msg = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
      if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); clearTimeout(p.timer); msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result); }
      else for (const fn of listeners.get(msg.method) || []) fn(msg.params);
    }
  });
  const evaluate = async expression => {
    const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const report = [];
  try {
    const { targetId } = await call('Target.createTarget', { url: 'about:blank' }, true);
    session = (await call('Target.attachToTarget', { targetId, flatten: true }, true)).sessionId;
    await call('Page.enable'); await call('Network.enable');
    await call('Fetch.enable', { patterns: [{ urlPattern: 'https://*' }] });
    on('Fetch.requestPaused', p => {
      const file = path.join(root, 'mirror-api.json');
      const health = { mirrors: { updated: now, list: ['distfiles.gentoozh.org', 'mirrors.cernet.edu.cn', 'mirror.nju.edu.cn', 'mirror.nyist.edu.cn', 'mirrors.ha.edu.cn', 'ftp2.osuosl.org'].map((host, i) => ({ host, origin: !i, up: true, trees: [{ key: 'stable', up: true, lagSec: i ? 84715 : 0 }, { key: 'unstable', up: true, lagSec: 0 }] })) } };
      const body = p.request.url === 'https://status.gentoozh.org/api/status' ? (fs.existsSync(file) ? fs.readFileSync(file).toString('base64') : !args.includes('--no-health') ? Buffer.from(JSON.stringify(health)).toString('base64') : '') : '';
      call('Fetch.fulfillRequest', { requestId: p.requestId, responseCode: body ? 200 : 503, responseHeaders: [{ name: 'Access-Control-Allow-Origin', value: '*' }, { name: 'Content-Type', value: 'application/json' }], body }).catch(() => {});
    });
    const loading = new Set();
    let idleTimer, idleResolve;
    const idle = () => { clearTimeout(idleTimer); if (!loading.size && idleResolve) idleTimer = setTimeout(() => { idleResolve(); idleResolve = null; }, 100); };
    on('Network.requestWillBeSent', p => { loading.add(p.requestId); clearTimeout(idleTimer); });
    for (const event of ['Network.loadingFinished', 'Network.loadingFailed']) on(event, p => { loading.delete(p.requestId); idle(); });
    const pages = fs.readdirSync(root).filter(p => p.endsWith('.html') && (!args.includes('--pages') || option('--pages').split(',').includes(p))).sort();
    if (!pages.length || widths.some(w => !Number.isInteger(w) || w <= 0)) throw new Error('No pages or invalid widths');
    for (const page of pages) for (const width of widths) for (const theme of ['light', 'dark']) for (const lang of ['zh-cn', 'zh-tw', 'en']) {
      await call('Emulation.setDeviceMetricsOverride', { width, height: 844, deviceScaleFactor: 3, mobile: width < 500 });
      await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
      const ready = new Promise((resolve, reject) => { const timer = setTimeout(() => { off(); reject(new Error('Page load timeout')); }, 15000); const off = on('Page.loadEventFired', () => { off(); clearTimeout(timer); resolve(); }); });
      await call('Page.navigate', { url: origin + (page === '_app.html' ? '/distfiles/' : '/' + page) + '?lang=' + lang });
      await ready;
      await new Promise((resolve, reject) => { const timer = setTimeout(() => { idleResolve = null; reject(new Error('Network idle timeout')); }, 10000); idleResolve = () => { clearTimeout(timer); resolve(); }; idle(); });
      await evaluate(`document.fonts.ready.then(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))`);
      const result = { page: page.replace('.html', ''), width, theme, language: lang, ...await evaluate(geometry) };
      report.push(result);
      if (result.viewport !== width || result.lang !== lang || result.theme !== theme) throw new Error('Emulation or locale did not apply');
      if (out && args.includes('--screenshots')) { const shot = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }); fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, `${result.page}-${width}-${theme}-${lang}.png`), Buffer.from(shot.data, 'base64')); }
      const tabs = await evaluate(`[...document.querySelectorAll('.mode[role=tab]')].filter(e => e.getAttribute('aria-selected') !== 'true').map(e => e.id)`);
      for (const tab of tabs) {
        await evaluate(`document.getElementById(${JSON.stringify(tab)}).click(); new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))`);
        const state = { page: result.page, width, theme, language: lang, state: tab, ...await evaluate(geometry) };
        report.push(state);
        if (out && args.includes('--screenshots')) {
          const shot = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
          fs.writeFileSync(path.join(out, `${result.page}-${width}-${theme}-${lang}-${tab}.png`), Buffer.from(shot.data, 'base64'));
        }
      }
    }
    if (out) { fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'measurements.json'), JSON.stringify(report, null, 2)); }
    const bad = report.filter(r => r.pageOverflow || r.overflow.length || r.titleOverlap);
    for (const r of bad) console.log(`FAIL ${r.page}${r.state ? ':' + r.state : ''} ${r.width} ${r.theme} ${r.language}: page=${r.pageOverflow} elements=${r.overflow.map(e => e.element).join(',')} titleOverlap=${r.titleOverlap}`);
    console.log(`Mobile overflow: ${report.length - bad.length}/${report.length} passed (${pages.length} pages, ${widths.join('/')}px, 2 themes, 3 languages)`);
    if (bad.length) process.exitCode = 1;
  } finally {
    chrome.kill();
    await exited;
    server.close();
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
