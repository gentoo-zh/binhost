#!/usr/bin/env node
// seg-picker.js shows a SegmentedControl as an S2 Picker when its options do not fit on one row: it measures
// the options against the container, keeps a margin before switching back, and a choice in the Picker is a
// click on the segment, so source-switch.js sets the same state, storage and addresses.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const pickerSrc = fs.readFileSync(path.join(ROOT, "site/assets/seg-picker.js"), "utf8");
const switchSrc = fs.readFileSync(path.join(ROOT, "site/assets/source-switch.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

// A small DOM: elements, compound selectors (tag, .class, [attr], [attr="v"]), events and focus.
let doc;
function el(tag, attrs, text) {
  const e = {
    tagName: tag.toUpperCase(), children: [], parentNode: null, attrs: {}, listeners: {}, _text: text || "",
    offsetWidth: 0, offsetHeight: 0, clientWidth: 0, hidden: false,
    get id() { return this.attrs.id || ""; },
    set id(v) { this.attrs.id = String(v); },
    set type(v) { this.attrs.type = v; },
    get className() { return this.attrs.class || ""; },
    set className(v) { this.attrs.class = v; },
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); },
    set textContent(v) { this.children = []; this._text = String(v); },
    get lastChild() { return this.children[this.children.length - 1]; },
    classList: {
      contains: (c) => (e.attrs.class || "").split(/\s+/).includes(c),
      add(c) { e.classList.toggle(c, true); },
      toggle(c, on) {
        const set = new Set((e.attrs.class || "").split(/\s+/).filter(Boolean));
        if (on) set.add(c); else set.delete(c);
        e.attrs.class = [...set].join(" ");
      },
    },
    getAttribute: (n) => (n in e.attrs ? e.attrs[n] : null),
    hasAttribute: (n) => n in e.attrs,
    setAttribute: (n, v) => { e.attrs[n] = String(v); },
    removeAttribute: (n) => { delete e.attrs[n]; },
    appendChild(c) { c.parentNode = e; e.children.push(c); return c; },
    insertBefore(c, ref) {
      c.parentNode = e;
      const i = ref ? e.children.indexOf(ref) : -1;
      if (i < 0) e.children.push(c); else e.children.splice(i, 0, c);
      return c;
    },
    removeChild(c) { e.children.splice(e.children.indexOf(c), 1); c.parentNode = null; return c; },
    insertAdjacentHTML() { e.appendChild(el("svg")); },
    addEventListener(n, f) { (e.listeners[n] = e.listeners[n] || []).push(f); },
    dispatch(n, props) {
      const ev = Object.assign({ target: e, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; },
        stopPropagation() {} }, props);
      for (let t = e; t; t = t.parentNode) (t.listeners[n] || []).forEach((f) => f(ev));
      (doc.listeners[n] || []).forEach((f) => f(ev));
      return ev;
    },
    click() { e.dispatch("click"); },
    focus() { doc.activeElement = e; },
    contains(o) { for (; o; o = o.parentNode) if (o === e) return true; return false; },
    closest(sel) { for (let t = e; t; t = t.parentNode) if (matches(t, sel)) return t; return null; },
    querySelectorAll(sel) { const out = []; walk(e, (d) => { if (d !== e && matches(d, sel)) out.push(d); }); return out; },
    querySelector(sel) { return e.querySelectorAll(sel)[0] || null; },
    getBoundingClientRect: () => ({ top: 100, bottom: 132, left: 0, right: 208 }),
  };
  Object.assign(e.attrs, attrs || {});
  return e;
}
function walk(e, f) { f(e); e.children.forEach((c) => walk(c, f)); }
function matches(e, sel) {
  const m = /^([a-z]*)((?:\.[\w-]+)*)((?:\[[\w-]+(?:="[^"]*")?\])*)$/.exec(sel);
  if (!m || !e.attrs) return false;
  if (m[1] && e.tagName !== m[1].toUpperCase()) return false;
  for (const c of m[2].split(".").filter(Boolean)) if (!e.classList.contains(c)) return false;
  for (const a of m[3].matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (!(a[1] in e.attrs)) return false;
    if (a[2] !== undefined && e.attrs[a[1]] !== a[2]) return false;
  }
  return true;
}

function setup(labels, box, uris) {
  const frames = [], resizers = [];
  const body = el("body");
  doc = {
    readyState: "complete", listeners: {}, activeElement: null,
    documentElement: el("html", { "data-lang": "zh-cn" }),
    createElement: (t) => el(t),
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); },
  };
  const group = body.appendChild(el("div", { class: "src-pick", role: "group", "aria-label": "镜像",
    "data-src-switch": "files" }));
  group.clientWidth = box;
  group.appendChild(el("span", { class: "src-label" }, "镜像"));
  const seg = group.appendChild(el("span", { class: "seg" }));
  const opts = labels.map((l, i) => {
    const b = seg.appendChild(el("button", { class: "src-opt" + (i === 0 ? " on" : ""),
      "data-uri": uris ? uris[i] : "u" + i }, l));
    b.offsetWidth = 100;
    return b;
  });
  const slot = body.appendChild(el("span", { "data-src-slot": "files" }, "u0"));
  const store = {};
  Object.assign(global, {
    document: doc,
    window: { innerHeight: 800, addEventListener() {} },
    getComputedStyle: () => ({ columnGap: "4px", paddingLeft: "0px", paddingRight: "0px" }),
    requestAnimationFrame: (f) => frames.push(f),
    MutationObserver: function () { this.observe = () => {}; },
    ResizeObserver: function (cb) { resizers.push(cb); this.observe = () => {}; },
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  });
  (0, eval)(pickerSrc);
  (0, eval)(switchSrc);
  const wrap = group.querySelector(".seg-pick");
  function resize(w) {
    group.clientWidth = w;
    resizers.forEach((cb) => cb([]));
    while (frames.length) frames.shift()();
  }
  return { group, seg, opts, slot, store, wrap, resize,
    btn: wrap.querySelector(".seg-pick-btn"), list: wrap.querySelector(".seg-pick-menu") };
}

// Three 100px options 4px apart need 308px.
let p = setup(["一", "二", "三"], 600);
const decide = global.window.SegPicker.decide;
check("the Picker follows a boundary with a margin",
  !decide(false, 308, 308) && decide(false, 309, 308) && decide(true, 300, 310) && !decide(true, 300, 316));
check("options that fit stay segments", p.wrap.hidden && !p.seg.hasAttribute("data-picked"));
p.resize(300);
check("options that overflow become a Picker", !p.wrap.hidden && p.seg.hasAttribute("data-picked"));
check("the Picker names the selected option", p.btn.querySelector(".seg-pick-value").textContent === "一");
check("the Picker lists every option, the selected one marked",
  p.list.querySelectorAll('[role="option"]').map((o) => o.getAttribute("aria-selected")).join() === "true,false,false");
check("the Picker's name is the group label", /-label /.test(p.btn.getAttribute("aria-labelledby") || ""),
  p.btn.getAttribute("aria-labelledby"));
p.resize(310);
check("a width just past the options' keeps the Picker", !p.wrap.hidden);
p.resize(330);
check("a width with room to spare brings the segments back", p.wrap.hidden && !p.seg.hasAttribute("data-picked"));

// A mirror picker: choosing in the Picker is a click on the segment.
p = setup(["教育网联合镜像站", "南京大学", "源站"], 250, ["https://a", "https://b", "https://c"]);
p.resize(250);
check("an overflowing mirror picker is a Picker", !p.wrap.hidden);
p.btn.dispatch("keydown", { key: "ArrowDown" });
check("ArrowDown opens the ListBox", !p.list.hidden && p.btn.getAttribute("aria-expanded") === "true");
const items = p.list.querySelectorAll('[role="option"]');
check("focus starts on the selected option", doc.activeElement === items[0]);
p.list.dispatch("keydown", { key: "ArrowDown" });
check("arrows move focus", doc.activeElement === items[1]);
p.list.dispatch("keydown", { key: "Enter" });
check("Enter selects the segment", p.opts[1].classList.contains("on") && !p.opts[0].classList.contains("on"));
check("the address follows the choice", p.slot.textContent === "https://b", p.slot.textContent);
check("the choice is stored as a click stores it", p.store["mirror-source"] === "https://b", JSON.stringify(p.store));
check("choosing closes the ListBox and returns focus",
  p.list.hidden && p.btn.getAttribute("aria-expanded") === "false" && doc.activeElement === p.btn);
check("the Picker shows the new choice", p.btn.querySelector(".seg-pick-value").textContent === "南京大学");
p.btn.click();
check("a click opens the ListBox", !p.list.hidden);
p.list.dispatch("keydown", { key: "Escape" });
check("Escape closes it and returns focus", p.list.hidden && doc.activeElement === p.btn);
p.btn.click();
p.list.querySelectorAll('[role="option"]')[2].click();
check("a click on an option selects it", p.opts[2].classList.contains("on") && p.slot.textContent === "https://c");

console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
