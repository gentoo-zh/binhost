
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = process.argv[2] || "site/assets";

function nodeList(items = []) {
  const list = Object.create(null);
  list.length = items.length;
  items.forEach((it, i) => { list[i] = it; });
  list.forEach = Array.prototype.forEach.bind(items);
  list.item = (i) => (i < items.length ? items[i] : null);
  list[Symbol.iterator] = items[Symbol.iterator].bind(items);
  return list;
}


function element() {
  let html = "";
  const el = {
    style: {},
    dataset: {},
    hidden: false,
    textContent: "",
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); },
    get lastChild() { return html ? { textContent: "" } : null; },

    classList: {
      add() {}, remove() {}, toggle() {}, contains: () => false,
    },
    setAttribute() {},
    removeAttribute() {},
    getAttribute: () => null,
    hasAttribute: () => false,
    appendChild() {},
    removeChild() {},
    addEventListener() {},
    focus() {},
    contains: () => false,
    closest: () => null,
    cloneNode: () => element(),
    querySelector: () => null,
    querySelectorAll: () => nodeList(),
    getBoundingClientRect: () => ({ width: 0, height: 0, top: 0, right: 0 }),
  };
  return el;
}

function environment() {
  const store = {};
  const context = {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
    },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    navigator: { language: "en-US", clipboard: { writeText: () => Promise.resolve() } },
    setTimeout: () => 0,
    clearTimeout() {},
    CustomEvent: class {
      constructor(type, opts) { this.type = type; Object.assign(this, opts || {}); }
    },
    document: {
      documentElement: element(),
      body: element(),
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => nodeList(),
      createElement: element,
      addEventListener() {},
      dispatchEvent() {},
    },
  };
  context.window = context;
  context.global = context;
  return vm.createContext(context);
}

function scriptsOf(text) {
  const scripts = [];
  const pattern = /<script\b[^>]*\bsrc=["']\/assets\/([^"'?]+\.js)(?:\?[^"']*)?["'][^>]*>/g;
  for (const match of text.matchAll(pattern)) scripts.push(match[1]);
  return scripts;
}

const site = path.join(DIR, "..");
const pages = fs.readdirSync(site).filter((f) => f.endsWith(".html")).sort();
const referenced = new Set();
let loaded = 0;

for (const page of pages) {
  const context = environment();
  const names = scriptsOf(fs.readFileSync(path.join(site, page), "utf8"));
  for (const name of names) {
    referenced.add(name);
    const file = path.join(DIR, name);
    if (!fs.existsSync(file)) {
      console.error(`!!! ${page} 引用了不存在的 ${file}`);
      process.exit(1);
    }
    try {
      vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });
    } catch (e) {
      console.error(`!!! ${page} 依页面顺序载入 ${file} 时失败： ${e.message}`);
      process.exit(1);
    }
    loaded++;
  }
  if (names.includes("i18n.js") &&
      (typeof context.MIRROR_T !== "function" ||
       context.MIRROR_T("brand") !== "distfiles.gentoozh.org")) {
    console.error(`!!! ${page} 的 i18n.js 没有取得先载入的共用字串`);
    process.exit(1);
  }
}

const present = fs.readdirSync(DIR).filter((f) => f.endsWith(".js")).sort();
const orphan = present.filter((f) => !referenced.has(f));
if (orphan.length) {
  console.error(`!!! ${orphan.join(", ")} 没有任何页面引用`);
  process.exit(1);
}

console.log(`  ${pages.length} 个页面依实际顺序载入了 ${loaded} 个脚本`);
