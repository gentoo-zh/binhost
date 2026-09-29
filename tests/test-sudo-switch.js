#!/usr/bin/env node
// sudo is on by default, in the static markup and after the script runs; turning it off persists across
// pages (mirror-sudo = "off"), turning it back on persists too, and unreadable storage means on.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "site/assets/sudo-switch.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

for (const page of ["binpkg-setup.html", "distfiles-setup.html", "overlay.html"]) {
  const html = fs.readFileSync(path.join(ROOT, "site", page), "utf8");
  // highlight.py adds its colour class to the sudo span; the text is what matters here.
  const spans = html.match(/<span class="sudo(?: t-\w)?"[^>]*>[^<]*<\/span>/g) || [];
  const btns = html.match(/<button[^>]*class="head-btn sudo-btn"[^>]*>/g) || [];
  check(page + ": without scripts every root command reads sudo",
    spans.length > 0 && spans.every((s) => />sudo <\/span>$/.test(s)), spans.find((s) => !s.includes(">sudo <")));
  check(page + ": without scripts the sudo toggle is pressed",
    btns.length > 0 && btns.every((b) => b.includes('aria-pressed="true"')));
}

function load(storage) {
  const attrs = {};
  const listeners = {};
  const clicks = [];
  const btns = [0, 1].map(() => {
    const a = { "aria-pressed": "true" };
    return {
      getAttribute: (n) => a[n], setAttribute: (n, v) => { a[n] = String(v); },
      addEventListener: (n, f) => clicks.push(f),
    };
  });
  const spans = [0, 1, 2].map(() => ({ textContent: "sudo ", hidden: false }));
  const document = {
    documentElement: { setAttribute: (n, v) => { attrs[n] = v; } },
    querySelectorAll: (sel) => (sel === ".code .sudo-btn, .install .sudo-btn" ? btns : sel === ".code .sudo" ? spans : []),
  };
  const window = { addEventListener: (n, f) => { listeners[n] = f; } };
  vm.runInNewContext(src, { document, window, localStorage: storage });
  return { attrs, btns, spans, clicks, listeners };
}

function store(initial) {
  const data = Object.assign({}, initial);
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
  };
}

let s = store({});
let env = load(s);
check("with nothing stored sudo is on", env.attrs["data-sudo"] === "on" && env.spans.every((x) => x.textContent === "sudo " && !x.hidden)
  && env.btns.every((b) => b.getAttribute("aria-pressed") === "true"));

env.clicks[0]();
check("turning it off removes sudo from every command", env.attrs["data-sudo"] === "off" && env.spans.every((x) => x.textContent === "" && x.hidden)
  && env.btns.every((b) => b.getAttribute("aria-pressed") === "false"));
check("turning it off is stored", s.data["mirror-sudo"] === "off");

env = load(s);
check("a stored off holds on the next page", env.attrs["data-sudo"] === "off" && env.spans.every((x) => x.hidden));

env.clicks[1]();
check("turning it back on is stored", s.data["mirror-sudo"] === "on" && env.attrs["data-sudo"] === "on");

s.data["mirror-sudo"] = "off";
env.listeners.pageshow({ persisted: true });
check("a page from the back-forward cache reads the choice again", env.attrs["data-sudo"] === "off");

env = load({ getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } });
check("storage that cannot be read means on", env.attrs["data-sudo"] === "on");
env.clicks[0]();
check("storage that cannot be written still toggles", env.attrs["data-sudo"] === "off");

env = load(store({ "mirror-sudo": "garbage" }));
check("an unknown stored value means on", env.attrs["data-sudo"] === "on");

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("sudo-switch: all passed");
