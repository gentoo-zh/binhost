#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/packages.html"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function list(items) {
  return { length: items.length, forEach(fn) { items.forEach(fn); } };
}

function element(id) {
  const listeners = {};
  return {
    id, innerHTML: "", textContent: "", hidden: false, value: "",
    href: "", dataset: {}, parentElement: { hidden: false },
    classList: { toggle() {} },
    addEventListener(name, listener) { listeners[name] = listener; },
    setAttribute() {},
    querySelectorAll() { return list([]); },
    listeners,
  };
}

const nodes = {};
const tables = { pkgs: element("pkgs-table"), deps: element("deps-table") };
const documentListeners = {};

global.document = {
  documentElement: { lang: "zh-cn" },
  getElementById(id) {
    if (!nodes[id]) nodes[id] = element(id);
    return nodes[id];
  },
  querySelector(selector) {
    if (selector === ".pkgs") return tables.pkgs;
    if (selector === ".deps-table") return tables.deps;
    return null;
  },
  querySelectorAll() { return list([]); },
  addEventListener(name, listener) { documentListeners[name] = listener; },
};
nodes.out = element("out");
nodes.out.querySelector = function (selector) {
  return selector === ".listing" ? tables.pkgs : null;
};
nodes.q = element("q");

global.window = { MIRROR_I18N: {}, addEventListener() {} };
global.location = { pathname: "/packages", hash: "" };
global.MutationObserver = class { observe() {} };

let resolveFirstStable;
let stableJsonRequests = 0;
const firstStable = new Promise(function (resolve) { resolveFirstStable = resolve; });
const stableData = {
  schema: 4,
  packages: [{ cp: "app-misc/stable", binhost: true, dist: [] }],
  deps: [{ cp: "dev-libs/stable", slot: "0", ver: "1" }],
};
const unstableData = {
  schema: 4,
  packages: [{ cp: "app-misc/unstable", binhost: true, dist: [] }],
  deps: [{ cp: "dev-libs/unstable", slot: "0", ver: "2" }],
};

function response(body, kind) {
  return {
    ok: true,
    json() { return Promise.resolve(body); },
    text() { return Promise.resolve(kind === "text" ? body : JSON.stringify(body)); },
  };
}

global.fetch = function (url) {
  if (url === "/packages.json") {
    stableJsonRequests++;
    return stableJsonRequests === 1
      ? firstStable.then(function () { return response(stableData); })
      : Promise.resolve(response(stableData));
  }
  if (url === "/packages-unstable.json") {
    return Promise.resolve(response(unstableData));
  }
  if (url === "/binpkgs/x86-64/Packages") {
    return Promise.resolve(response(
      "PACKAGES: 1\n\nCPV: app-misc/stable-1\nREPO: gentoo-zh\nSIZE: 10", "text"));
  }
  if (url === "/unstable/binpkgs/x86-64/Packages") {
    return Promise.resolve(response(
      "PACKAGES: 1\n\nCPV: app-misc/unstable-2\nREPO: gentoo-zh\nSIZE: 20", "text"));
  }
  if (url === "/distfiles-index.json") {
    return Promise.resolve(response({ generated: 1, files: [] }));
  }
  return Promise.resolve({ ok: false, status: 404 });
};

(0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((match) => match[1]);
(0, eval)(blocks.sort((left, right) => right.length - left.length)[0]);

function change(detail) {
  documentListeners.channelchange({ detail });
}

function settle() {
  return new Promise(function (resolve) { setImmediate(resolve); });
}

(async function () {
  change({
    channel: "unstable",
    path: "/unstable/binpkgs/x86-64",
    packages: "/packages-unstable.json",
    packageText: "/packages-unstable.txt",
    depsText: "/deps-unstable.txt",
  });
  await settle();
  await settle();

  check("切换频道会同时更新包与依赖列表",
        nodes.rows.innerHTML.includes("app-misc/unstable") &&
        !nodes.rows.innerHTML.includes("app-misc/stable") &&
        nodes.depRows.innerHTML.includes("dev-libs/unstable"),
        nodes.rows.innerHTML + " / " + nodes.depRows.innerHTML);
  check("切换频道会更新纯文本清单链接",
        nodes.packagesText.href === "/packages-unstable.txt" &&
        nodes.depsText.href === "/deps-unstable.txt" &&
        nodes.depsTextDetail.href === "/deps-unstable.txt");

  resolveFirstStable();
  await settle();
  await settle();
  check("较晚返回的旧频道请求不会覆盖当前频道",
        nodes.rows.innerHTML.includes("app-misc/unstable") &&
        nodes.depRows.innerHTML.includes("dev-libs/unstable"));

  change({
    channel: "stable",
    path: "/binpkgs/x86-64",
    packages: "/packages.json",
    packageText: "/packages.txt",
    depsText: "/deps.txt",
  });
  await settle();
  await settle();
  check("切回 stable 会恢复 stable 数据与链接",
        nodes.rows.innerHTML.includes("app-misc/stable") &&
        nodes.depRows.innerHTML.includes("dev-libs/stable") &&
        nodes.packagesText.href === "/packages.txt" &&
        nodes.depsText.href === "/deps.txt");

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  包列表频道切换：全部通过");
  process.exit(failed ? 1 : 0);
}());
