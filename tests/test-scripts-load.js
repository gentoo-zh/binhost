
const fs = require("fs");
const path = require("path");

const DIR = process.argv[2] || "site/assets";
const ORDER = ["early.js", "strings.js", "util.js", "i18n.js", "mode-switch.js", "sudo-switch.js", "source-switch.js"];

const store = {};

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

global.window = global;
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
global.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
global.navigator = { language: "zh-CN", clipboard: { writeText: () => Promise.resolve() } };
global.setTimeout = (fn) => 0;
global.clearTimeout = () => {};
global.CustomEvent = class {
  constructor(type, opts) { this.type = type; Object.assign(this, opts || {}); }
};
global.document = {
  documentElement: element(),
  body: element(),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => nodeList(),
  createElement: element,
  addEventListener() {},
  dispatchEvent() {},
};

let loaded = 0;
for (const name of ORDER) {
  const file = path.join(DIR, name);
  if (!fs.existsSync(file)) {
    console.error(`!!! 找不到 ${file}`);
    process.exit(1);
  }
  try {
    (0, eval)(fs.readFileSync(file, "utf8"));
  } catch (e) {
    console.error(`!!! ${file} 载入时失败： ${e.message}`);
    process.exit(1);
  }
  loaded++;
}

const present = fs.readdirSync(DIR).filter((f) => f.endsWith(".js")).sort();
const missing = present.filter((f) => !ORDER.includes(f));
if (missing.length) {
  console.error(`!!! ${missing.join(", ")} 没有列进加载顺序`);
  process.exit(1);
}

{
  const site = path.join(DIR, "..");
  const pages = fs.readdirSync(site)
    .filter((f) => f.endsWith(".html"))
    .map((f) => fs.readFileSync(path.join(site, f), "utf8"))
    .join("\n");
  const orphan = fs.readdirSync(DIR)
    .filter((f) => f.endsWith(".js") && !pages.includes("/assets/" + f));
  if (orphan.length) {
    console.error(`!!! ${orphan.join(", ")} 没有任何页面引用`);
    process.exit(1);
  }
}

console.log(`  ${loaded} 个脚本都能载入`);
