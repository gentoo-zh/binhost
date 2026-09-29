#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function elem(attrs, text) {
  const a = Object.assign({}, attrs);
  let inner = text || "";
  const e = {
    dataset: { i18n: a["data-i18n"], i18nHtml: a["data-i18n-html"], i18nHref: a["data-i18n-href"],
               i18nLabel: a["data-i18n-label"],
               mode: a["data-mode"], lang: a["data-lang"] },
    textContent: text || "", hidden: false, style: {},
    getAttribute: (k) => a[k], setAttribute: (k, v) => { a[k] = v; },
    removeAttribute: (k) => { delete a[k]; },
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    _h: {},
    addEventListener(type, f) { (e._h[type] = e._h[type] || []).push(f); },
    click() { (e._h.click || []).forEach((f) => f({ stopPropagation() {}, target: e })); },
    key(k) {
      const ev = { key: k, preventDefault() {}, stopPropagation() {}, target: e };
      for (let n = e; n; n = n._up) (n._h.keydown || []).forEach((f) => f(ev));
      ((global.document._h || {}).keydown || []).forEach((f) => f(ev));
    },
    _up: null,
    appendChild() {}, focus() { global.document.activeElement = e; }, contains: () => false,
  };
  Object.defineProperty(e, "innerHTML", { get: () => inner, set: (v) => { inner = v; } });
  Object.defineProperty(e, "lastChild", {
    get: () => (/<[a-z]/i.test(inner) ? { textContent: "" } : null),
  });
  return e;
}

function run(lang) {
  const link = elem({ "data-i18n-href": "hrefDemo", href: "https://gentoozh.org/" }, "gentoozh.org");
  const nav = elem({ "data-i18n-label": "aPages", "aria-label": "页面" }, "");
  const list = (sel) => (/i18n-href/.test(sel) ? [link]
                       : /i18n-label/.test(sel) ? [nav]
                       : /i18n-html/.test(sel) ? []
                       : /data-i18n\]/.test(sel) ? [] : []);
  global.document = {
    documentElement: { style: {}, lang: "zh-cn", setAttribute() {}, removeAttribute() {}, classList: { remove() {} } },
    querySelectorAll: (sel) => ({ forEach: (f) => list(sel).forEach(f), length: list(sel).length }),
    querySelector: () => null,
    getElementById: () => null,
    createElement: () => elem({}, ""),
    addEventListener() {}, dispatchEvent() {}, title: "",
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {} };
  global.navigator = { language: lang === "en" ? "en-US" : lang === "zh-tw" ? "zh-TW" : "zh-CN" };
  global.localStorage = { getItem: () => lang, setItem() {} };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  // No production string swaps an href by language any more, so this test supplies its own pair to
  // keep data-i18n-href covered.
  window.MIRROR_I18N_COMMON["zh-tw"].hrefDemo = "https://gentoozh.org/zh-tw/";
  window.MIRROR_I18N_COMMON["en"].hrefDemo = "https://gentoozh.org/en/";
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  return { href: link.getAttribute("href"), text: link.textContent, label: nav.getAttribute("aria-label") };
}

const want = {
  "zh-cn": "https://gentoozh.org/",
  "zh-tw": "https://gentoozh.org/zh-tw/",
  "en": "https://gentoozh.org/en/",
};
for (const [lang, url] of Object.entries(want)) {
  const r = run(lang);
  check(`${lang} 的链接指向 ${url}`, r.href === url, `实际 ${r.href}`);
}
const labels = { "zh-cn": "页面", "zh-tw": "頁面", "en": "Pages" };
for (const [lang, label] of Object.entries(labels)) {
  const r = run(lang);
  check(`${lang} 的 aria-label 是 ${label}`, r.label === label, `实际 ${r.label}`);
}

// The theme toggle (nav.html #theme-toggle, i18n.js): following the system a press forces the other
// theme, a second press follows the system again; the name says the mode in force and what a press does.
function toggleRun(storedTheme, osDark, lang) {
  const btn = elem({ class: "icon-btn theme-btn", id: "theme-toggle" });
  const root = elem({}, "");
  root.lang = "zh-cn";
  const stored = {};
  if (storedTheme !== undefined) stored["mirror-theme"] = storedTheme;
  const query = { matches: !!osDark, _f: [], addEventListener(t, f) { this._f.push(f); } };
  global.document = {
    documentElement: root,
    querySelector: () => null,
    querySelectorAll: () => ({ length: 0, forEach() {} }),
    getElementById: (id) => (id === "theme-toggle" ? btn : null), createElement: () => elem({}, ""),
    _h: {},
    addEventListener(type, f) { (this._h[type] = this._h[type] || []).push(f); },
    dispatchEvent() {}, title: "", activeElement: null,
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {}, matchMedia: () => query };
  global.navigator = { language: "zh-CN" };
  global.localStorage = {
    getItem: (key) => (key === "mirror-lang" ? (lang || "zh-cn") : key in stored ? stored[key] : null),
    setItem: (key, value) => { stored[key] = value; },
    removeItem: (key) => { delete stored[key]; },
  };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  const osChange = (dark) => { query.matches = dark; query._f.forEach((f) => f({ matches: dark })); };
  return { btn, root, stored, osChange };
}

// OS theme × stored choice → theme attribute, name, and the modes two presses lead to.
const cases = [
  [false, undefined, undefined, "主题：跟随系统（浅色），按下改用深色", "dark", undefined],
  [true, undefined, undefined, "主题：跟随系统（深色），按下改用浅色", "light", undefined],
  [false, "dark", "dark", "主题：深色，按下恢复跟随系统", undefined, "dark"],
  [true, "dark", "dark", "主题：深色，按下恢复跟随系统", undefined, "light"],
  [false, "light", "light", "主题：浅色，按下恢复跟随系统", undefined, "dark"],
  [true, "light", "light", "主题：浅色，按下恢复跟随系统", undefined, "light"],
];
for (const [osDark, st, theme, label, afterOne, afterTwo] of cases) {
  const name = `系统${osDark ? "深色" : "浅色"}、保存 ${st || "无"}`;
  const { btn, root, stored } = toggleRun(st, osDark);
  check(`${name}：data-theme 为 ${theme || "无"}，名称正确`,
        root.getAttribute("data-theme") === theme && btn.getAttribute("aria-label") === label && btn.title === label,
        `theme=${root.getAttribute("data-theme")} label=${btn.getAttribute("aria-label")}`);
  btn.click();
  check(`${name}：按一次后是 ${afterOne || "跟随系统"}`,
        root.getAttribute("data-theme") === afterOne && stored["mirror-theme"] === afterOne &&
        root.style.colorScheme === (afterOne || "light dark"),
        `theme=${root.getAttribute("data-theme")} stored=${stored["mirror-theme"]}`);
  btn.click();
  check(`${name}：按两次后是 ${afterTwo || "跟随系统"}`,
        root.getAttribute("data-theme") === afterTwo && stored["mirror-theme"] === afterTwo,
        `theme=${root.getAttribute("data-theme")} stored=${stored["mirror-theme"]}`);
}

{
  const { btn, root, stored, osChange } = toggleRun(undefined, false);
  osChange(true);
  check("跟随系统时，系统改为深色后名称随之更新",
        btn.getAttribute("aria-label") === "主题：跟随系统（深色），按下改用浅色" && root.getAttribute("data-theme") === undefined,
        String(btn.getAttribute("aria-label")));
  btn.click();
  check("随后按下改用浅色", root.getAttribute("data-theme") === "light" && stored["mirror-theme"] === "light",
        String(root.getAttribute("data-theme")));
}

{
  const { btn, root, stored } = toggleRun("sepia", false);
  check("无效主题值回到跟随系统并清除保存值",
        root.getAttribute("data-theme") === undefined && root.style.colorScheme === "light dark" &&
        !("mirror-theme" in stored) && btn.getAttribute("aria-label") === "主题：跟随系统（浅色），按下改用深色",
        `theme=${root.getAttribute("data-theme")} label=${btn.getAttribute("aria-label")}`);
}

{
  const tw = toggleRun("dark", false, "zh-tw").btn.getAttribute("aria-label");
  const en = toggleRun(undefined, true, "en").btn.getAttribute("aria-label");
  check("繁体与英文的名称", tw === "主題：深色，按下恢復跟隨系統" && en === "Theme: system (dark), press to use light",
        `${tw} / ${en}`);
}

// The language menu: a menu button over three menuitemradio items (nav.html, i18n.js menuButton).
function langMenuRun(storedLang, search) {
  const values = ["zh-cn", "zh-tw", "en"];
  const items = values.map((v) => elem({ "data-value": v, role: "menuitemradio", "aria-checked": "false" }, ""));
  const menu = elem({ role: "menu" });
  menu.hidden = true;
  items.forEach((i) => { i._up = menu; });
  menu.querySelectorAll = () => ({ length: items.length, forEach: (f) => items.forEach(f) });
  const btn = elem({ class: "action-btn menu-trigger", "aria-expanded": "false" });
  const outside = elem({});
  const wrap = elem({ "data-menu": "lang" });
  wrap.querySelector = (s) => (/menu-trigger/.test(s) ? btn : /role="menu"/.test(s) ? menu : null);
  wrap.querySelectorAll = menu.querySelectorAll;
  wrap.contains = (n) => n === btn || n === menu || items.includes(n);

  const root = elem({}, "");
  root.lang = "zh-cn";
  const stored = {};
  global.document = {
    documentElement: root,
    querySelector: () => null,
    querySelectorAll: (s) => (/data-menu="lang"/.test(s) ? { length: 1, forEach: (f) => f(wrap) }
                                                         : { length: 0, forEach() {} }),
    getElementById: () => null, createElement: () => elem({}, ""),
    _h: {},
    addEventListener(type, f) { (this._h[type] = this._h[type] || []).push(f); },
    dispatchEvent() {}, title: "", activeElement: null,
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {}, location: { search: search || "" } };
  global.navigator = { language: "zh-CN" };
  global.localStorage = {
    getItem: (key) => (key === "mirror-lang" ? storedLang || null : null),
    setItem: (key, value) => { stored[key] = value; },
  };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  const clickOutside = () => (global.document._h.click || []).forEach((f) => f({ target: outside }));
  return { menu, btn, items, root, stored, clickOutside };
}

{
  const { menu, btn, items } = langMenuRun("zh-tw");
  const at = () => (global.document.activeElement || {}).getAttribute("data-value");
  check("语言按钮声明弹出菜单并以当前语言命名",
        btn.getAttribute("aria-expanded") === "false" && /繁體中文/.test(btn.getAttribute("aria-label")),
        String(btn.getAttribute("aria-label")));
  check("当前语言一项 aria-checked=true，其余为 false",
        items.map((i) => i.getAttribute("aria-checked")).join() === "false,true,false",
        items.map((i) => i.getAttribute("aria-checked")).join());
  btn.key("Enter");
  check("Enter 展开语言菜单并聚焦当前语言", menu.hidden === false &&
        btn.getAttribute("aria-expanded") === "true" && at() === "zh-tw", `${menu.hidden} ${at()}`);
  global.document.activeElement.key("ArrowDown");
  check("下箭头移到下一种语言", at() === "en", String(at()));
  global.document.activeElement.key("ArrowDown");
  check("下箭头在末项绕回首项", at() === "zh-cn", String(at()));
  global.document.activeElement.key("Escape");
  check("Escape 收起语言菜单并把焦点还给按钮",
        menu.hidden === true && btn.getAttribute("aria-expanded") === "false" && global.document.activeElement === btn,
        `${menu.hidden}`);
  btn.key(" ");
  check("空格也能展开", menu.hidden === false);
  items[2].click();
  check("选中 English 后菜单收起、焦点回按钮、语言切换",
        menu.hidden === true && global.document.activeElement === btn &&
        global.document.documentElement.lang === "en" && items[2].getAttribute("aria-checked") === "true" &&
        items[1].getAttribute("aria-checked") === "false" && /English/.test(btn.getAttribute("aria-label")),
        `${menu.hidden} ${global.document.documentElement.lang} ${btn.getAttribute("aria-label")}`);
}

{
  const { menu, btn, clickOutside } = langMenuRun("zh-cn");
  btn.key("ArrowUp");
  check("上箭头展开并聚焦末项", menu.hidden === false &&
        global.document.activeElement.getAttribute("data-value") === "en");
  clickOutside();
  check("点菜单外收起", menu.hidden === true && btn.getAttribute("aria-expanded") === "false");
  btn.click();
  check("点按钮展开", menu.hidden === false);
  btn.click();
  check("再点按钮收起", menu.hidden === true);
}

{
  const { root, stored } = langMenuRun("zh-cn", "?lang=en");
  check("?lang=en 链接选定英文并记住", root.lang === "en" && stored["mirror-lang"] === "en",
        `${root.lang} ${stored["mirror-lang"]}`);
  const bad = langMenuRun("zh-tw", "?lang=xx");
  check("无效的 ?lang= 被忽略", bad.root.lang === "zh-tw", bad.root.lang);
}

function copyRun(value) {
  const chip = elem({ class: "copy-chip", "data-copy": value }, "");
  chip.closest = (sel) => sel === ".copy-chip" ? chip : null;
  const root = elem({}, "");
  root.lang = "zh-cn";
  let copied;
  global.document = {
    documentElement: root,
    querySelector: () => null,
    querySelectorAll: () => ({ length: 0, forEach() {} }),
    getElementById: () => null,
    createElement: () => elem({}, ""),
    _h: {},
    addEventListener(type, f) { (this._h[type] = this._h[type] || []).push(f); },
    dispatchEvent() {}, title: "",
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {} };
  Object.defineProperty(global, "navigator", {
    configurable: true,
    value: {
      language: "zh-CN",
      clipboard: { writeText(v) { copied = v; return Promise.resolve(); } },
    },
  });
  global.localStorage = { getItem: () => "zh-cn", setItem() {} };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  (global.document._h.click || []).forEach((f) => f({ target: chip }));
  return copied;
}

const copyValue = "eselect repository enable gentoo-zh";
check("复制按钮写入完整且未改动的内容", copyRun(copyValue) === copyValue);

console.log(failed ? `\n  ${failed} 项不通过` : "\n  语言链接与主题菜单：全部通过");
process.exit(failed ? 1 : 0);
