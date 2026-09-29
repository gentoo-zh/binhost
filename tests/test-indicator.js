#!/usr/bin/env node
// indicator.js follows the selected item of every segmented track and tab row: on load, when a picker
// script moves the selection, when a label changes width (a language switch, a late count) and on resize.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "site/assets/indicator.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function item(left, width, on) {
  const classes = new Set(on ? ["on"] : []);
  return {
    offsetLeft: left, offsetTop: 0, offsetWidth: width, offsetHeight: 32, parentNode: null,
    classList: { contains: (c) => classes.has(c), toggle: (c, v) => (v ? classes.add(c) : classes.delete(c)) },
  };
}

function track(items) {
  const attrs = {};
  const t = {
    children: items.slice(),
    hasAttribute: (n) => n in attrs,
    setAttribute: (n, v) => { attrs[n] = String(v); },
    insertBefore(el) { t.children.unshift(el); el.parentNode = t; },
    querySelectorAll: () => t.children.filter((c) => c.classList),
  };
  items.forEach((i) => { i.parentNode = t; });
  return t;
}

function load(tracks) {
  const frames = [];
  const observers = [];
  const mutations = [];
  const docListeners = {};
  const winListeners = {};
  function Observer(cb) { this.cb = cb; observers.push(this); }
  Observer.prototype.observe = function () {};
  function Mutations(cb) { Observer.call(this, cb); mutations.push(this); }
  Mutations.prototype.observe = function () {};
  const document = {
    readyState: "complete",
    querySelectorAll: (sel) => (sel === ".seg" ? tracks : []),
    addEventListener: (n, f) => { docListeners[n] = f; },
    // As in a browser, setting hidden to true queues a mutation even when it already holds, and setting it to
    // false queues one only when the attribute was there.
    createElement: () => {
      const props = {};
      let hidden = false;
      const e = {
        className: "", parentNode: null,
        setAttribute() {},
        style: { setProperty: (k, v) => { props[k] = v; } },
        props,
      };
      Object.defineProperty(e, "hidden", {
        get: () => hidden,
        set: (v) => {
          const was = hidden;
          hidden = !!v;
          if (hidden || was) mutations.forEach((m) => m.cb([{ target: e, attributeName: "hidden" }]));
        },
      });
      return e;
    },
  };
  const window = { addEventListener: (n, f) => { winListeners[n] = f; } };
  vm.runInNewContext(src, {
    document, window, MutationObserver: Mutations, ResizeObserver: Observer,
    requestAnimationFrame: (f) => frames.push(f),
  });
  // Runs queued frames, at most max of them, and returns how many ran.
  function flush(max) {
    let n = 0;
    while (frames.length && n < (max || 1000)) { frames.shift()(); n++; }
    return n;
  }
  return { frames, flush, observers, docListeners, winListeners };
}

const a = item(0, 80, true), b = item(84, 120, false), c = item(208, 60, false);
const t = track([a, b, c]);
const env = load([t]);
const ind = t.children[0];

check("the track gets one indicator, first in the track", ind && ind.className === "seg-ind" && t.hasAttribute("data-ind"));
check("the indicator starts on the selected item", ind.props["--ind-x"] === "0px" && ind.props["--ind-w"] === "80px",
  JSON.stringify(ind.props));
check("it does not slide into its first position", !t.hasAttribute("data-ind-ready"));
env.flush();
check("later moves slide", t.hasAttribute("data-ind-ready"));

a.classList.toggle("on", false);
b.classList.toggle("on", true);
env.observers.forEach((o) => o.cb());
env.flush();
check("a selection change by a picker script moves it", ind.props["--ind-x"] === "84px" && ind.props["--ind-w"] === "120px",
  JSON.stringify(ind.props));

b.offsetWidth = 150; c.offsetLeft = 238;
env.docListeners.langchange();
env.flush();
check("a language change that widens the label resizes it", ind.props["--ind-w"] === "150px");

b.offsetLeft = 0; b.offsetTop = 36;
env.winListeners.resize();
env.flush();
check("a resize that wraps the track follows the item", ind.props["--ind-x"] === "0px" && ind.props["--ind-y"] === "36px");

b.offsetWidth = 0;
env.observers.forEach((o) => o.cb());
env.flush();
check("a hidden track hides its indicator", ind.hidden === true);

// A selected item in a hidden pane (the quick-setup pane of /binpkg-setup) has no width. The indicator hides
// once and the page goes idle: its own hidden attribute must not schedule the next frame.
const idleItem = item(0, 0, true);
const idle = track([idleItem, item(0, 0, false)]);
const idleEnv = load([idle]);
idleEnv.flush();
idleEnv.observers.forEach((o) => o.cb());
const frames = idleEnv.flush(1000);
check("a hidden selected item leaves the page idle", idle.children[0].hidden === true && frames < 10,
  frames + " frames");

// A choice made in the Picker (seg-picker.js) is a class change on a segment button; it still moves the indicator.
idleItem.offsetWidth = 70;
idleEnv.observers.forEach((o) => o.cb([{ target: idleItem, attributeName: "class" }]));
idleEnv.flush();
check("a mutation of an item still moves it", idle.children[0].hidden === false &&
  idle.children[0].props["--ind-w"] === "70px", JSON.stringify(idle.children[0].props));

const bare = track([item(0, 50, false), item(54, 50, false)]);
load([bare]);
check("a track with nothing selected shows no indicator", bare.children[0].hidden === true);

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("indicator: all passed");
