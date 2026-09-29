#!/usr/bin/env node
// Copy after a mirror switch and after sudo is turned off: the text on the clipboard is the plain text of
// the block as it now reads, with the chosen mirror, without sudo, and without any colour markup. The page
// markup runs through the real source-switch.js and sudo-switch.js on a small DOM, and the copied text
// comes from the copy handler's own value() in i18n.js.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

// ---- a DOM just large enough for the three scripts ----
const VOID = new Set(["br", "img", "input", "meta", "link", "hr", "wbr", "source", "col", "area", "path"]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");

class Node {
  constructor(tag, attrs) {
    this.tag = tag; this.attrs = attrs || {}; this.children = []; this.parentNode = null; this.data = "";
    this.listeners = {};
  }
  get isText() { return this.tag === "#text"; }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  removeAttribute(n) { delete this.attrs[n]; }
  hasAttribute(n) { return n in this.attrs; }
  get hidden() { return this.hasAttribute("hidden"); }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get classList() {
    const node = this;
    const list = () => (node.attrs.class || "").split(/\s+/).filter(Boolean);
    const set = (l) => { node.attrs.class = l.join(" "); };
    return {
      contains: (c) => list().includes(c),
      toggle: (c, on) => { const l = list().filter((x) => x !== c); if (on === undefined ? !list().includes(c) : on) l.push(c); set(l); },
      add: (c) => { if (!list().includes(c)) set(list().concat(c)); },
      remove: (c) => set(list().filter((x) => x !== c)),
    };
  }
  get textContent() { return this.isText ? this.data : this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { const t = new Node("#text"); t.data = String(v); t.parentNode = this; this.children = v === "" ? [] : [t]; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  cloneNode() {
    const n = new Node(this.tag, Object.assign({}, this.attrs)); n.data = this.data;
    this.children.forEach((c) => n.appendChild(c.cloneNode(true)));
    return n;
  }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, e) { (this.listeners[t] || []).forEach((f) => f(e || {})); }
  click() { this.dispatch("click", { target: this }); }
  elements() { const out = []; const walk = (n) => n.children.forEach((c) => { if (!c.isText) { out.push(c); walk(c); } }); walk(this); return out; }
  matches(sel) { return sel.split(",").some((s) => matchChain(this, s.trim().split(/\s+/))); }
  querySelectorAll(sel) { return this.elements().filter((e) => e.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) { for (let n = this; n && !n.isText && n.tag !== "#root"; n = n.parentNode) if (n.matches(sel)) return n; return null; }
}

// One compound selector: tag, .class, [attr], [attr="v"], :not([attr]).
function matchOne(node, sel) {
  const not = [];
  sel = sel.replace(/:not\(([^)]*)\)/g, (_, inner) => { not.push(inner); return ""; });
  if (not.some((s) => matchOne(node, s))) return false;
  const tag = /^[a-z]+/.exec(sel);
  if (tag && node.tag !== tag[0]) return false;
  for (const m of sel.matchAll(/\.([\w-]+)/g)) if (!node.classList.contains(m[1])) return false;
  for (const m of sel.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (!node.hasAttribute(m[1])) return false;
    if (m[2] !== undefined && node.getAttribute(m[1]) !== m[2]) return false;
  }
  return true;
}
function matchChain(node, parts) {
  if (!matchOne(node, parts[parts.length - 1])) return false;
  if (parts.length === 1) return true;
  for (let p = node.parentNode; p && p.tag !== "#root"; p = p.parentNode) if (matchChain(p, parts.slice(0, -1))) return true;
  return false;
}

function parse(src) {
  const root = new Node("#root");
  let cur = root;
  const re = /<!--[\s\S]*?-->|<\/(\w+)\s*>|<(\w+)((?:\s+[\w:-]+(?:=(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|([^<]+)/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[0].startsWith("<!--")) continue;
    if (m[1]) { if (cur.tag === m[1].toLowerCase()) cur = cur.parentNode; else { let p = cur; while (p && p.tag !== m[1].toLowerCase()) p = p.parentNode; if (p) cur = p.parentNode; } continue; }
    if (m[2]) {
      const attrs = {};
      for (const a of m[3].matchAll(/([\w:-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attrs[a[1]] = decode(a[2] ?? a[3] ?? a[4] ?? "");
      const n = cur.appendChild(new Node(m[2].toLowerCase(), attrs));
      if (!VOID.has(n.tag) && !m[0].endsWith("/>")) cur = n;
      continue;
    }
    const t = new Node("#text"); t.data = decode(m[4]); cur.appendChild(t);
  }
  return root;
}

// ---- the copy handler's value(), taken from i18n.js as it ships ----
const i18n = read("site/assets/i18n.js");
const start = i18n.indexOf("var value = function (el) {");
const end = i18n.indexOf("\n    };", start);
check("i18n.js still defines the copy value() this test reads", start > 0 && end > start);
const value = vm.runInNewContext("(" + i18n.slice(start + "var value = ".length, end + 6) + ")");

function load(page) {
  const html = read(page);
  const main = /<main\b[\s\S]*?<\/main>/.exec(html)[0];
  const root = parse(main);
  const docEl = new Node("html", { "data-lang": "zh-cn" });
  const doc = {
    documentElement: docEl,
    querySelectorAll: (s) => root.querySelectorAll(s),
    querySelector: (s) => root.querySelector(s),
    addEventListener() {},
    dispatchEvent() {},
  };
  const store = {};
  const ctx = {
    document: doc, window: { addEventListener() {} }, CustomEvent: function () {},
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  };
  vm.runInNewContext(read("site/assets/source-switch.js"), ctx);
  vm.runInNewContext(read("site/assets/sudo-switch.js"), ctx);
  return { root, main };
}

// Plain text of a block's source markup, with the mirror and sudo changes a reader made.
function expected(preSource, fromUri, toUri, sudoOn) {
  let t = decode(preSource.replace(/<[^>]+>/g, ""));
  t = t.split(fromUri).join(toUri);
  if (!sudoOn) t = t.replace(/sudo /g, "");
  return t.replace(/\s+$/, "");
}

// Each case names a mirror picker; the install box around it holds the blocks it rewrites.
const CASES = [
  ["site/internal/design.html", "demo"],
  ["site/binpkg-setup.html", "repo"],
  ["site/overlay.html", "git"],
];
for (const [page, name] of CASES) {
  const { root, main } = load(page);
  const host = root.querySelector('[data-src-switch="' + name + '"]').parentNode;
  const opts = host.querySelectorAll(".src-opt");
  const from = opts[0].getAttribute("data-uri"), to = opts[1].getAttribute("data-uri");
  const chips = host.querySelectorAll(".code .copy-chip");
  const sources = [...main.matchAll(/<pre\b[^>]*>([\s\S]*?)<\/pre>/g)].map((m) => m[1]);
  const preOf = (chip) => chip.closest(".code").querySelector("pre");
  const sourceOf = (chip) => sources.find((s) => decode(s.replace(/<[^>]+>/g, "")) === decode(preOf(chip).textContent)) || null;

  const before = chips.map(sourceOf);
  check(page + ": each code block has a copy button", chips.length > 0 && before.every(Boolean));

  const sudo = root.querySelector(".sudo-btn");
  opts[1].click();
  sudo.click();
  chips.forEach((chip, i) => {
    const got = value(chip);
    const want = expected(before[i], from, to, false);
    check(page + ": copy " + (i + 1) + " after a mirror switch and sudo off is the plain text on screen",
      got === want, JSON.stringify(got) + "\n      expected " + JSON.stringify(want));
    check(page + ": copy " + (i + 1) + " holds no markup and no sudo", !/[<>]span|class=|sudo /.test(got));
  });
  sudo.click();
  chips.forEach((chip, i) => {
    const got = value(chip);
    check(page + ": copy " + (i + 1) + " with sudo back on", got === expected(before[i], from, to, true), JSON.stringify(got));
  });
}

process.exit(failed ? 1 : 0);
