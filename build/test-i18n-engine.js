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
    dataset: { i18n: a["data-i18n"], i18nHtml: a["data-i18n-html"], i18nHref: a["data-i18n-href"] },
    textContent: text || "", hidden: false, style: {},
    getAttribute: (k) => a[k], setAttribute: (k, v) => { a[k] = v; },
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    _h: {},
    addEventListener(type, f) { (e._h[type] = e._h[type] || []).push(f); },
    click() { (e._h.click || []).forEach((f) => f({ stopPropagation() {}, target: e })); },
    appendChild() {}, focus() {}, contains: () => false,
  };
  Object.defineProperty(e, "innerHTML", { get: () => inner, set: (v) => { inner = v; } });
  Object.defineProperty(e, "lastChild", {
    get: () => (/<[a-z]/i.test(inner) ? { textContent: "" } : null),
  });
  return e;
}

function run(lang) {
  const link = elem({ "data-i18n": "fCommunity", "data-i18n-href": "fCommunityUrl",
                      href: "https://gentoozh.org/" }, "Gentoo 中文社区");
  const list = (sel) => (/i18n-href/.test(sel) ? [link]
                       : /i18n-html/.test(sel) ? []
                       : /data-i18n\]/.test(sel) ? [link] : []);
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
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  return { href: link.getAttribute("href"), text: link.textContent };
}

const want = {
  "zh-cn": "https://gentoozh.org/",
  "zh-tw": "https://gentoozh.org/zh-tw/",
  "en": "https://gentoozh.org/en/",
};
for (const [lang, url] of Object.entries(want)) {
  const r = run(lang);
  check(`${lang} 的链接指向 ${url}`, r.href === url, `拿到 ${r.href}`);
}

function menuRun() {
  const items = ["light", "dark", "system"].map((m) =>
    elem({ "data-mode": m, class: "menu-item" }, ""));
  items.forEach((i) => { i.innerHTML = "<svg></svg><span></span>"; });
  const menu = elem({ class: "menu", hidden: true });
  menu.hidden = true;
  menu.querySelectorAll = () => ({ length: items.length, forEach: (f) => items.forEach(f) });
  const btn = elem({ class: "icon-btn theme-btn", "aria-expanded": "false" });
  const wrap = elem({ class: "menu-wrap" });
  wrap.querySelector = (s) => (/theme-btn/.test(s) ? btn : /menu/.test(s) ? menu : null);
  wrap.contains = () => true;

  global.document = {
    documentElement: { lang: "zh-cn", setAttribute() {}, removeAttribute() {},
                       classList: { remove() {} }, style: {} },
    querySelector: (s) => (/menu-wrap/.test(s) ? wrap : null),
    querySelectorAll: () => ({ length: 0, forEach() {} }),
    getElementById: () => null, createElement: () => elem({}, ""),
    addEventListener() {}, dispatchEvent() {}, title: "",
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {} };
  global.navigator = { language: "zh-CN" };
  global.localStorage = { getItem: () => null, setItem() {} };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  return { menu, btn, items };
}

const m = menuRun();
check("菜单一开始是收起的", m.menu.hidden === true);
m.btn.click();
check("点按钮展开", m.menu.hidden === false && m.btn.getAttribute("aria-expanded") === "true",
      `hidden=${m.menu.hidden} aria=${m.btn.getAttribute("aria-expanded")}`);
m.btn.click();
check("再点收起", m.menu.hidden === true && m.btn.getAttribute("aria-expanded") === "false",
      `hidden=${m.menu.hidden} aria=${m.btn.getAttribute("aria-expanded")}`);
m.btn.click();
m.items[1].click();
check("选一项之后菜单收起", m.menu.hidden === true);

console.log(failed ? `\n  ${failed} 项不通过` : "\n  语言链接与主题菜单：全部通过");
process.exit(failed ? 1 : 0);
