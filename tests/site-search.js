// Site search logic (site/assets/search.js): matching and ranking over the committed index, package
// matching, the arrow-key model and the shortcuts. Run by tests/test-site-checkers.py.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const context = { document: { getElementById: () => null }, navigator: {} };
context.window = context;
vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'site/assets/search.js'), 'utf8'), context);
const S = context.MIRROR_SEARCH;
const index = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/assets/search-index.json'), 'utf8'));

let bad = 0;
function check(name, ok, detail) {
  console.log((ok ? '  ✓ ' : '  ✗ ') + name + (ok || detail === undefined ? '' : '\n      ' + JSON.stringify(detail)));
  if (!ok) bad++;
}
const urls = list => list.map(e => e.url);

check('索引有分组、页面与章节', index.groups.length > 0 && index.entries.some(e => e.kind === 'page') &&
  index.entries.some(e => e.kind === 'section' && e.url.includes('#')));
check('每个分组都有图标', index.groups.every(g => g.icon && g.icon.paths.length));
check('每个条目三种语言齐全', index.entries.every(e => ['zh-cn', 'zh-tw', 'en'].every(l =>
  typeof e.title[l] === 'string' && e.title[l] && typeof e.desc[l] === 'string')));

const empty = S.search(index, 'zh-cn', '  ', '');
check('空查询只列出页面，按侧栏顺序', empty.length && empty.every(e => e.kind === 'page') &&
  empty[0].url === '/', urls(empty));
const help = S.search(index, 'zh-tw', '', 'help');
check('空查询按分类列出该分类的页面', help.length && help.every(e => e.group === 'help' && e.kind === 'page'),
  urls(help));
check('“包”分类不列页面', S.search(index, 'en', 'faq', 'pkgs').length === 0);

const faq = S.search(index, 'en', 'FAQ', '');
check('不分大小写，标题开头匹配的页面排第一', faq[0] && faq[0].url === '/faq', urls(faq).slice(0, 3));
const q9 = S.search(index, 'zh-cn', '如何自行建立镜像', '');
check('FAQ 问题与章节都能搜到', urls(q9).includes('/faq#q9') && urls(q9).includes('/mirrors#own'), urls(q9));
const same = S.search(index, 'zh-cn', '镜像', '');
check('同一档内页面排在章节之前', same.findIndex(e => e.url === '/mirrors') <
  same.findIndex(e => e.url === '/mirrors#list'), urls(same).slice(0, 6));

const own = S.search(index, 'zh-tw', '鏡像', '');
const fallback = S.search(index, 'zh-tw', 'gentoo-zh downloads', '');
check('当前语言的匹配排在其他语言之前', own.length && S.rank(own[0], 'zh-tw', '鏡像') < 8,
  urls(own).slice(0, 3));
check('当前语言没有匹配时回退到其他语言', fallback.length > 0 && fallback[0].url === '/' &&
  fallback.every(e => S.rank(e, 'zh-tw', 'gentoo-zh downloads') >= 8), urls(fallback).slice(0, 3));
check('全角与半角按 NFKC 视为相同', S.search(index, 'en', 'ＦＡＱ', '')[0].url === '/faq');
check('分类过滤查询结果', S.search(index, 'en', 'key', 'binhost').every(e => e.group === 'binhost'));
check('没有匹配时返回空列表', S.search(index, 'en', 'zz-no-such-thing', '').length === 0);

const pkgs = ['app-i18n/fcitx-rime', 'app-i18n/librime', 'app-i18n/rime-data', 'dev-python/pyrime',
  'rime-x/other', 'media-fonts/iansui'];
check('包查询少于 2 个字符时不匹配', S.packages(pkgs, 'r').total === 0 && S.packages(pkgs, ' r ').total === 0);
const rime = S.packages(pkgs, 'RIME');
check('包名开头优先，其次类别/包名开头，再次包含', JSON.stringify(rime.hits) === JSON.stringify(
  ['app-i18n/rime-data', 'rime-x/other', 'app-i18n/fcitx-rime', 'app-i18n/librime', 'dev-python/pyrime']),
  rime.hits);
const cut = S.packages(pkgs, 'rime', 2);
check('超出上限时截断并给出总数', cut.hits.length === 2 && cut.total === 5, cut);

check('ArrowDown 从无到第一个，末尾回到开头', S.step('ArrowDown', -1, 3) === 0 && S.step('ArrowDown', 2, 3) === 0);
check('ArrowUp 从无或开头到最后一个', S.step('ArrowUp', -1, 3) === 2 && S.step('ArrowUp', 0, 3) === 2 &&
  S.step('ArrowUp', 2, 3) === 1);
check('Home 与 End 到两端', S.step('Home', 2, 3) === 0 && S.step('End', 0, 3) === 2);
check('没有结果或其他按键时不处理', S.step('ArrowDown', -1, 0) === null && S.step('ArrowLeft', 0, 3) === null);

const key = (k, extra) => Object.assign({ key: k, target: { tagName: 'BODY' } }, extra);
check('Ctrl K 与 Command K 切换对话框', S.shortcut(key('k', { ctrlKey: true })) === 'toggle' &&
  S.shortcut(key('K', { metaKey: true })) === 'toggle');
check('输入法组字时不响应', S.shortcut(key('k', { ctrlKey: true, isComposing: true })) === null);
check('/ 在正文打开对话框', S.shortcut(key('/')) === 'open');
check('/ 在文本框与可编辑区域里照常输入', S.shortcut(key('/', { target: { tagName: 'INPUT', type: 'search' } })) === null &&
  S.shortcut(key('/', { target: { tagName: 'TEXTAREA' } })) === null &&
  S.shortcut(key('/', { target: { tagName: 'DIV', isContentEditable: true } })) === null);
check('/ 在按钮与复选框上仍打开对话框', S.shortcut(key('/', { target: { tagName: 'INPUT', type: 'checkbox' } })) === 'open');
check('带修饰键的 K 与普通按键不处理', S.shortcut(key('k', { ctrlKey: true, shiftKey: true })) === null &&
  S.shortcut(key('k')) === null);

// Every string search.js asks for exists in all three locales: zh-CN as a span in the nav template,
// zh-TW and en in strings.js. A key dropped from one of them leaves a blank label (the community chip once did).
{
  const src = fs.readFileSync(path.join(__dirname, '..', 'site', 'assets', 'search.js'), 'utf8');
  const nav = fs.readFileSync(path.join(__dirname, '..', 'site', 'tools', 'chrome', 'nav.html'), 'utf8');
  const strings = fs.readFileSync(path.join(__dirname, '..', 'site', 'assets', 'strings.js'), 'utf8');
  const keys = [...new Set([...src.matchAll(/\bt\('([A-Za-z0-9_]+)'\)/g)].map(m => m[1]))]
    .filter(k => !/Url$/.test(k));
  const missing = keys.filter(k => !nav.includes(`data-i18n="${k}"`) && !nav.includes(`data-i18n-label="${k}"`)
    || (strings.match(new RegExp(`\\b${k}:`, 'g')) || []).length < 2);
  check('search.js 用到的字符串三种语言都有', missing.length === 0, missing);
}

// The dialog itself, in a small DOM: the index and /packages.json arrive late or fail, and the list is rebuilt
// under the user's keyboard selection and focus.
function page() {
  const doc = { activeElement: null };
  function mk(tag, cls) {
    const e = {
      tagName: tag.toUpperCase(), children: [], parentNode: null, attrs: {}, listeners: {}, text: '',
      hidden: false, value: '', id: '', open: false,
      get className() { return this.attrs.class || ''; },
      set className(v) { this.attrs.class = v; },
      get textContent() { return this.text + this.children.map(c => c.textContent).join(''); },
      set textContent(v) { this.children.forEach(c => { c.parentNode = null; }); this.children = []; this.text = String(v); },
      getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
      setAttribute(n, v) { this.attrs[n] = String(v); },
      removeAttribute(n) { delete this.attrs[n]; },
      hasAttribute(n) { return n in this.attrs; },
      appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
      contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; },
      addEventListener(type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); },
      focus() { doc.activeElement = this; },
      select() {}, setSelectionRange() {}, scrollIntoView() {}, getClientRects() { return [1]; },
      showModal() { this.open = true; },
      close() { this.open = false; fire(this, 'close'); },
      click() { fire(this, 'click'); },
      querySelectorAll(sel) { const out = []; walk(this, n => { if (n !== this && matches(n, sel)) out.push(n); }); return out; },
      querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
      closest(sel) { for (let n = this; n; n = n.parentNode) if (matches(n, sel)) return n; return null; },
    };
    e.classList = { add: c => { e.className = (e.className + ' ' + c).trim(); } };
    if (cls) e.className = cls;
    return e;
  }
  function walk(n, f) { f(n); n.children.forEach(c => walk(c, f)); }
  function matches(n, sel) {
    return sel.split(',').some(part => {
      const m = part.trim().match(/^([a-z]*)((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/);
      if (!m || (m[1] && n.tagName !== m[1].toUpperCase())) return false;
      const classes = (n.className || '').split(/\s+/);
      if (m[2] && !m[2].slice(1).split('.').every(c => classes.includes(c))) return false;
      return (m[3].match(/\[[^\]]+\]/g) || []).every(a => {
        const [, name, val] = a.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
        return val === undefined ? n.hasAttribute(name) : n.getAttribute(name) === val;
      });
    });
  }
  function fire(target, type, props) {
    const e = Object.assign({ type, target, preventDefault() {}, stopPropagation() {} }, props);
    for (let n = target; n; n = n.parentNode) (n.listeners[type] || []).forEach(f => f(e));
    return e;
  }
  const body = mk('body');
  const dialog = body.appendChild(mk('dialog'));
  dialog.setAttribute('data-src', '/assets/search-index.json');
  const input = dialog.appendChild(mk('input', 'sd-input'));
  const chips = dialog.appendChild(mk('div', 'sd-chips'));
  const results = dialog.appendChild(mk('div', 'sd-results'));
  dialog.appendChild(mk('p', 'sd-msg'));
  const retry = dialog.appendChild(mk('button', 'sd-retry'));
  dialog.appendChild(mk('button', 'sd-close'));
  const root = mk('html');
  root.setAttribute('data-lang', 'en');
  const docListeners = {};
  Object.assign(doc, {
    documentElement: root,
    getElementById: id => (id === 'site-search' ? dialog : null),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener: (type, f) => { docListeners[type] = f; },
    createElement: tag => mk(tag),
    createElementNS: (ns, tag) => mk(tag),
  });
  doc.activeElement = body;
  const requests = [];
  const ctx = {
    document: doc, navigator: { platform: 'Linux' }, location: { pathname: '/' },
    MIRROR_T: key => key,
    fetch: url => new Promise((resolve, reject) => {
      requests.push({ url,
        ok: data => resolve({ ok: true, json: () => Promise.resolve(data) }),
        fail: () => resolve({ ok: false, status: 503 }) });
    }),
  };
  ctx.window = ctx;
  vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'site/assets/search.js'), 'utf8'), ctx);
  const settle = () => new Promise(r => setImmediate(r));
  const selected = () => results.querySelectorAll('[role="option"]')
    .filter(o => o.getAttribute('aria-selected') === 'true').map(o => o.href);
  function type(text) { input.value = text; fire(input, 'input'); }
  function key(k) { fire(input, 'keydown', { key: k }); }
  docListeners.keydown({ key: 'k', ctrlKey: true, target: body, preventDefault() {} });
  return { doc, dialog, input, chips, retry, requests, settle, selected, type, key };
}

(async () => {
  const p = page();
  p.type('mirror');
  p.requests.find(r => r.url === '/assets/search-index.json').ok(index);
  await p.settle();
  const before = p.selected();
  p.key('ArrowDown');
  const second = p.selected();
  const chip = p.chips.querySelector('[data-group="pkgs"]');
  chip.focus();
  p.requests.find(r => r.url === '/packages.json').ok({ packages: [{ cp: 'app-misc/mirrorselect' }] });
  await p.settle();
  check('包数据晚到时保留键盘选中的结果', before.length === 1 && second.length === 1 && second[0] !== before[0] &&
    JSON.stringify(p.selected()) === JSON.stringify(second), { before, second, after: p.selected() });
  const now = p.doc.activeElement;
  check('包数据晚到时焦点留在原来的分类按钮上', now !== chip && p.chips.contains(now) &&
    now.getAttribute('data-group') === 'pkgs', now && now.attrs);

  const q = page();
  q.type('mirror');
  q.requests.forEach(r => r.fail());
  await q.settle();
  const n = q.requests.length;
  q.retry.click();
  const again = q.requests.slice(n).map(r => r.url).sort();
  check('索引与包数据都失败时，点一次重试两者都重新请求',
    JSON.stringify(again) === JSON.stringify(['/assets/search-index.json', '/packages.json']), again);

  process.exit(bad ? 1 : 0);
})();

