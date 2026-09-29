#!/usr/bin/env node
// docs.js lists a page's sections only in "On this page" and in the top bar's section picker, never in the
// sidebar; both lists show only the visible pane's sections after a panechange, and the picker names the
// section being read, or the page title above the first section.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "site/assets/docs.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

// A small element: enough of the DOM for docs.js.
function el(tag, props) {
  const e = Object.assign({
    tagName: tag.toUpperCase(), children: [], parentNode: null, attrs: {}, listeners: {}, hidden: false,
    id: "", className: "", textContent: "", top: 0, shown: true, focused: false,
    appendChild(c) { c.parentNode = e; e.children.push(c); return c; },
    setAttribute(n, v) { e.attrs[n] = String(v); },
    getAttribute(n) { return n in e.attrs ? e.attrs[n] : null; },
    removeAttribute(n) { delete e.attrs[n]; },
    hasAttribute(n) { return n in e.attrs; },
    addEventListener(n, f) { (e.listeners[n] = e.listeners[n] || []).push(f); },
    fire(n, ev) { (e.listeners[n] || []).forEach((f) => f(Object.assign({ target: e, preventDefault() {}, stopPropagation() {} }, ev))); },
    insertAdjacentHTML() {},
    getClientRects() { return e.shown ? [1] : []; },
    getBoundingClientRect() { return { top: e.top }; },
    contains(x) { for (let n = x; n; n = n.parentNode) if (n === e) return true; return false; },
    closest(sel) { for (let n = e; n; n = n.parentNode) if (sel === "a" && n.tagName === "A") return n; return null; },
    focus() { doc.activeElement = e; },
    descendants() { return e.children.flatMap((c) => [c].concat(c.descendants())); },
    querySelectorAll(sel) {
      const all = e.descendants();
      if (sel === "h2") return all.filter((c) => c.tagName === "H2");
      if (sel === "a") return all.filter((c) => c.tagName === "A");
      return [];
    },
    querySelector(sel) {
      const all = e.descendants();
      if (sel === "h1") return all.find((c) => c.tagName === "H1") || null;
      if (sel === ".toc-list") return all.find((c) => c.className === "toc-list") || null;
      if (sel === "a[aria-current]") return all.find((c) => c.tagName === "A" && c.hasAttribute("aria-current")) || null;
      return null;
    },
  }, props || {});
  return e;
}

const root = el("html");
const main = el("main");
const h1 = main.appendChild(el("h1", { textContent: "Overlay", top: 100 }));
const heads = ["Add", "Keywords", "Install"].map((t, i) => main.appendChild(el("h2", { id: "s" + i, textContent: t, top: 400 + i * 600 })));
const side = el("nav", { className: "sidebar" });
const current = side.appendChild(el("a", { attrs: { "aria-current": "page" } }));
const toc = el("aside", { className: "toc", hidden: true, attrs: { "data-outline": "" } });
const list = toc.appendChild(el("ul", { className: "toc-list" }));
const bar = el("header", { className: "nav" });
const doc = el("document", { readyState: "complete", documentElement: root, activeElement: null });
doc.createElement = (tag) => el(tag);
doc.querySelector = (sel) => ({ main, ".sidebar": side, ".toc": toc, ".nav": bar }[sel] || null);

const frames = [];
const win = {
  innerHeight: 800, scrollY: 0,
  addEventListener() {},
};
vm.runInNewContext(src, {
  document: doc, window: win,
  getComputedStyle: () => ({ getPropertyValue: () => "72" }),
  requestAnimationFrame: (f) => frames.push(f),
});
Object.defineProperty(doc.documentElement, "scrollHeight", { value: 4000 });
const flush = () => { while (frames.length) frames.shift()(); };
flush();

const pick = bar.children.find((c) => c.className === "toc-pick");
const menu = pick && pick.children.find((c) => c.id === "toc-menu");
const btn = pick && pick.children.find((c) => c.id === "toc-pick-btn");
const label = btn && btn.children[0];
const texts = (ul) => ul.children.filter((li) => !li.hidden).map((li) => li.children[0].textContent);

check("the sidebar gains no section list", current.parentNode === side && side.children.length === 1 && current.children.length === 0);
check("the outline lists every h2 and shows", texts(list).join() === "Add,Keywords,Install" && !toc.hidden, texts(list).join());
check("the picker sits in the top bar", !!pick && !!menu && !!btn);
check("the picker lists the title, then every h2", texts(menu).join() === "Overlay,Add,Keywords,Install", menu && texts(menu).join());
check("above the first section the picker names the page", label.textContent === "Overlay", label.textContent);

heads[0].top = 50; heads[1].top = 60;
win.scrollY = 1000;
check("docs.js listens for panechange", (doc.listeners.panechange || []).length > 0);
heads[2].shown = false;
doc.fire("panechange");
flush();
check("a hidden pane's section leaves the outline", texts(list).join() === "Add,Keywords", texts(list).join());
check("a hidden pane's section leaves the picker", texts(menu).join() === "Overlay,Add,Keywords", texts(menu).join());
check("the picker names the section being read", label.textContent === "Keywords", label.textContent);
const curOutline = list.children.map((li) => li.children[0]).filter((a) => a.hasAttribute("aria-current"));
check("the outline marks the same section", curOutline.length === 1 && curOutline[0].textContent === "Keywords");

btn.fire("click");
check("a click opens the picker", !menu.hidden && btn.getAttribute("aria-expanded") === "true");
check("focus lands on the section being read", doc.activeElement && doc.activeElement.textContent === "Keywords");
menu.fire("keydown", { key: "ArrowDown" });
check("ArrowDown wraps past the last visible entry", doc.activeElement.textContent === "Overlay", doc.activeElement.textContent);
menu.fire("keydown", { key: "Escape" });
check("Escape closes and returns focus to the button", menu.hidden && btn.getAttribute("aria-expanded") === "false" && doc.activeElement === btn);
btn.fire("click");
doc.fire("click", { target: main });
check("a click outside closes it", menu.hidden);

// Two headings that would mint the same id (here, the same data-i18n key) must not collide: the
// second gets a -2 suffix instead of stealing the first's anchor.
(function () {
  var root2 = el("html");
  var main2 = el("main");
  main2.appendChild(el("h1", { textContent: "Overlay", top: 100 }));
  var dupHeads = ["First", "Second"].map(function (t) {
    return main2.appendChild(el("h2", { textContent: t, top: 400, dataset: { i18n: "navSame" } }));
  });
  var side2 = el("nav", { className: "sidebar" });
  side2.appendChild(el("a", { attrs: { "aria-current": "page" } }));
  var toc2 = el("aside", { className: "toc", hidden: true, attrs: { "data-outline": "" } });
  toc2.appendChild(el("ul", { className: "toc-list" }));
  var bar2 = el("header", { className: "nav" });
  var doc2 = el("document", { readyState: "complete", documentElement: root2, activeElement: null });
  doc2.createElement = function (tag) { return el(tag); };
  doc2.querySelector = function (sel) {
    return { main: main2, ".sidebar": side2, ".toc": toc2, ".nav": bar2 }[sel] || null;
  };
  vm.runInNewContext(src, {
    document: doc2, window: { innerHeight: 800, scrollY: 0, addEventListener: function () {} },
    getComputedStyle: function () { return { getPropertyValue: function () { return "72"; } }; },
    requestAnimationFrame: function () {},
  });
  check("two headings with the same minted id stay unique",
        dupHeads[0].id === "navSame" && dupHeads[1].id === "navSame-2",
        dupHeads.map(function (h) { return h.id; }).join(","));
})();

// Sidebar group state (nav.html's inline script, rendered into every page by render-chrome.py): the
// reader's own toggle — mouse, keyboard or a script setting .open — is recorded by reading g.open
// after it changes, not by guessing the opposite of the pre-toggle state from a click.
(function () {
  var navHtml = fs.readFileSync(path.join(__dirname, "..", "site", "index.html"), "utf8");
  var script = navHtml.slice(navHtml.indexOf("(function () {\n  var side"),
    navHtml.indexOf("</script>", navHtml.indexOf("(function () {\n  var side")));

  var stored = {}, listeners = {};
  function group(id) {
    return {
      getAttribute: function (k) { return k === "data-group" ? id : null; },
      hasAttribute: function () { return false; },
      contains: function () { return false; },
      open: true,
      addEventListener: function (evt, fn) { (listeners[id] = listeners[id] || {})[evt] = fn; },
    };
  }
  var groups = [group("overlay")];
  var side = {
    querySelector: function () { return null; },
    querySelectorAll: function (sel) {
      var items = sel === ".nav-group" ? groups : [];
      return { length: items.length, forEach: function (f) { items.forEach(f); } };
    },
  };
  global.document = { getElementById: function () { return side; } };
  global.sessionStorage = {
    getItem: function () { return JSON.stringify(stored); },
    setItem: function (k, v) { stored = JSON.parse(v); },
  };
  global.location = { pathname: "/" };
  (0, eval)(script);

  groups[0].open = true;
  listeners.overlay.toggle();
  check("a details toggle records the state it changed to, not the click's guess",
        stored.overlay === true, JSON.stringify(stored));
})();

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("ok");
