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
  check(`${lang} 的链接指向 ${url}`, r.href === url, `实际 ${r.href}`);
}

function menuRun(storedTheme) {
  const items = ["light", "dark", "system"].map((m) =>
    elem({ "data-mode": m, class: "menu-item" }, ""));
  items.forEach((i) => { i.innerHTML = "<svg></svg><span></span>"; });
  const menu = elem({ class: "menu", hidden: true });
  menu.hidden = true;
  items.forEach((i) => { i._up = menu; });
  menu.querySelectorAll = () => ({ length: items.length, forEach: (f) => items.forEach(f) });
  const btn = elem({ class: "icon-btn theme-btn", "aria-expanded": "false" });
  const wrap = elem({ class: "menu-wrap" });
  wrap.querySelector = (s) => (/theme-btn/.test(s) ? btn : /menu/.test(s) ? menu : null);
  wrap.contains = () => true;

  const root = elem({}, "");
  root.lang = "zh-cn";
  const stored = {};
  global.document = {
    documentElement: root,
    querySelector: (s) => (/menu-wrap/.test(s) ? wrap : null),
    querySelectorAll: () => ({ length: 0, forEach() {} }),
    getElementById: () => null, createElement: () => elem({}, ""),
    _h: {},
    addEventListener(type, f) { (this._h[type] = this._h[type] || []).push(f); },
    dispatchEvent() {}, title: "", activeElement: null,
  };
  global.window = { MIRROR_I18N: {}, addEventListener() {} };
  global.navigator = { language: "zh-CN" };
  global.localStorage = {
    getItem: (key) => key === "mirror-theme" ? storedTheme : null,
    setItem: (key, value) => { stored[key] = value; },
  };
  global.CustomEvent = class { constructor() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/strings.js"), "utf8"));
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/i18n.js"), "utf8"));
  return { menu, btn, items, root, stored };
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

{
  const { menu, btn, items } = menuRun();
  const at = () => (global.document.activeElement || {}).getAttribute("data-mode");

  btn.key("ArrowDown");
  check("在按钮上按下箭头会展开", menu.hidden === false, String(menu.hidden));
  check("并且聚焦到当前选中的那一项", at() === "system", String(at()));

  global.document.activeElement.key("ArrowDown");
  check("下箭头绕回第一项", at() === "light", String(at()));
  global.document.activeElement.key("End");
  check("End 到最后一项", at() === "system", String(at()));
  global.document.activeElement.key("Home");
  check("Home 到第一项", at() === "light", String(at()));
  global.document.activeElement.key("ArrowUp");
  check("上箭头从第一项绕到最后一项", at() === "system", String(at()));

  const zeros = items.filter((i) => i.getAttribute("tabindex") === "0");
  check("roving tabindex 只有一个 0", zeros.length === 1, String(zeros.length));

  global.document.activeElement.key("Escape");
  check("Escape 收起菜单", menu.hidden === true, String(menu.hidden));
  check("并且焦点回到按钮", global.document.activeElement === btn, "焦点不在按钮上");

  items[1].click();
  check("选一项之后 aria-checked 随之更新",
        items[1].getAttribute("aria-checked") === "true" &&
        items[2].getAttribute("aria-checked") === "false",
        items.map((i) => i.getAttribute("data-mode") + "=" + i.getAttribute("aria-checked")).join(" "));
}

{
  const { btn, items, root, stored } = menuRun("sepia");
  const label = btn.getAttribute("aria-label");
  check("无效主题值回到 system",
        root.getAttribute("data-theme-mode") === "system" &&
        root.getAttribute("data-theme") === undefined &&
        root.style.colorScheme === "light dark" &&
        items[2].getAttribute("aria-checked") === "true" &&
        !String(label).includes("undefined") &&
        stored["mirror-theme"] === "system",
        `mode=${root.getAttribute("data-theme-mode")} label=${label}`);
}

console.log(failed ? `\n  ${failed} 项不通过` : "\n  语言链接与主题菜单：全部通过");
process.exit(failed ? 1 : 0);
