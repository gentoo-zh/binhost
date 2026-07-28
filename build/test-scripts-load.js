// Load every front-end script once, in a minimal DOM.
//
// `node --check` parses; it does not run. A file can be perfectly valid syntax
// and still die the moment it is loaded -- a call to something that is not
// there, a property read off null. That kills language switching on every page
// while check-i18n, check-copy, check-css and node --check all stay green,
// which is the shape of an incident this repository has already had once.
//
// The DOM here answers just enough for the scripts to reach their end. It is
// not a browser: it proves loading, not behaviour. Behaviour is what the
// checks around it are for.

const fs = require("fs");
const path = require("path");

const DIR = process.argv[2] || "site/assets";
// Order matters: strings.js and util.js define what the others reach for.
// lang-early.js 排最前：页面把它放在 <head>，在其余脚本之前同步执行。
const ORDER = ["lang-early.js", "strings.js", "util.js", "i18n.js", "source-switch.js"];

const store = {};

// A NodeList, not an Array. The browser's has forEach and length and nothing
// else -- no map, no filter, no reduce. Handing back an Array lets code that
// would die in a browser run clean here.
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
  // lastChild 跟着 innerHTML 走，和浏览器一样：新建的元素没有子节点，赋过
  // innerHTML 之后才有。原来无条件给一个对象，于是「忘记先塞子元素就读
  // lastChild」这种在浏览器上必崩的写法在这里静静通过。
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
    // indirect eval，不是 new Function：后者把顶层的 function 声明关在自己的
    // 作用域里，而浏览器里 util.js 的 esc/human 是全局的。用 new Function 时
    // 一个引用了 esc 的脚本会在这里失败，而在浏览器上完全正常。
    (0, eval)(fs.readFileSync(file, "utf8"));
  } catch (e) {
    console.error(`!!! ${file} 载入时失败: ${e.message}`);
    process.exit(1);
  }
  loaded++;
}

// Anything in the directory that the list above forgot would go unloaded, and
// this test would keep passing while a new script broke every page.
const present = fs.readdirSync(DIR).filter((f) => f.endsWith(".js")).sort();
const missing = present.filter((f) => !ORDER.includes(f));
if (missing.length) {
  console.error(`!!! ${missing.join(", ")} 没有列进加载顺序`);
  process.exit(1);
}

console.log(`  ${loaded} 个脚本都能载入`);
