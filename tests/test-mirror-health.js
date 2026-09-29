#!/usr/bin/env node
// mirror-health.js reads the public status API once and marks each mirror picker option whose mirror is
// down or more than six hours behind, matching entries by the host of the option's data-uri. A failed
// request leaves the page as it was.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "site/assets/mirror-health.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function el(attrs) {
  return {
    attrs: Object.assign({}, attrs), title: "", textContent: "",
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    removeAttribute(k) { delete this.attrs[k]; if (k === "title") this.title = ""; },
    hasAttribute(k) { return k in this.attrs; },
  };
}

const HOSTS = {
  origin: "https://distfiles.gentoozh.org",
  nju: "https://mirror.nju.edu.cn/gentoo-zh",
  hernet: "https://mirrors.ha.edu.cn/gentoo-zh",
  osuosl: "https://ftp2.osuosl.org/pub/gentoo-zh",
  other: "https://unlisted.example/gentoo-zh",
};

const tree = (key, lagSec, up) => ({ key, name: key, up: up !== false, code: 200, lagSec });
const NOW = Math.floor(Date.now() / 1000);
const API = { updated: NOW, overall: "ok", sites: [], events: [], mirrors: { updated: NOW, published: 1, list: [
  { host: "distfiles.gentoozh.org", key: "src", origin: true, up: true, trees: [tree("stable", 0), tree("unstable", 0)] },
  { host: "mirror.nju.edu.cn", key: "nju", up: true, trees: [tree("stable", 84715), tree("unstable", 3600)] },
  { host: "mirrors.ha.edu.cn", key: "ha", up: true, trees: [tree("stable", 0), tree("unstable", 0, false)] },
  { host: "ftp2.osuosl.org", key: "osuosl", up: true, trees: [tree("stable", 21000), tree("unstable", 600)] },
] } };

// Runs the script against a page of options and cells; fetchImpl answers the one request.
function run(fetchImpl, lang) {
  const opts = Object.keys(HOSTS).map((k) => el({ "data-uri": HOSTS[k] }));
  const cells = ["mirrors.ha.edu.cn", "mirror.nju.edu.cn", "unlisted.example"].map((h) => el({ "data-mirror-host": h }));
  cells.forEach((c) => { c.textContent = "—"; });
  const listeners = {}, events = [], asked = [];
  const document = {
    documentElement: { lang: lang || "zh-CN" },
    querySelectorAll(sel) {
      if (sel === ".src-opt[data-uri]") return opts;
      if (sel === "[data-mirror-host]") return cells;
      throw new Error("unexpected selector " + sel);
    },
    addEventListener(type, fn) { listeners[type] = fn; },
    dispatchEvent(e) { events.push(e.type); },
  };
  const ctx = {
    document, window: {},
    CustomEvent: function (type) { this.type = type; },
    setTimeout: () => 0, clearTimeout: () => {},
    fetch: (url, init) => { asked.push(url); return fetchImpl(url, init); },
  };
  vm.runInNewContext(src, ctx);
  return { opts, cells, listeners, events, asked, document, api: ctx.window.MirrorHealth };
}
const byKey = (page) => Object.fromEntries(Object.keys(HOSTS).map((k, i) => [k, page.opts[i]]));
const settle = () => new Promise((r) => setImmediate(r));
const answer = (j) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(j) });

(async function () {
  const page = run(answer(API));
  await settle();
  const o = byKey(page);
  check("只请求一次状态 API", page.asked.length === 1 && page.asked[0] === "https://status.gentoozh.org/api/status",
        JSON.stringify(page.asked));
  check("落后超过 6 小时：取两棵树中较大的延迟，标记并提示",
        o.nju.hasAttribute("data-behind") && o.nju.title === "落后约 24 小时" && !o.nju.hasAttribute("data-down"),
        JSON.stringify([o.nju.attrs, o.nju.title]));
  check("按主机名匹配：mirrors.ha.edu.cn 对应 API 的 ha，任一树不可达即视为无法连接",
        o.hernet.hasAttribute("data-behind") && o.hernet.hasAttribute("data-down") &&
        o.hernet.title === "上次检查时无法连接", JSON.stringify([o.hernet.attrs, o.hernet.title]));
  check("延迟不足 6 小时与已同步的镜像不标记",
        !o.osuosl.hasAttribute("data-behind") && !o.origin.hasAttribute("data-behind") && o.osuosl.title === "",
        JSON.stringify([o.osuosl.attrs, o.origin.attrs]));
  check("API 未列出的镜像保持原样", !o.other.hasAttribute("data-behind") && o.other.title === "");
  check("镜像页状态列：落后、无法连接、未列出",
        page.cells[0].textContent === "无法连接" && page.cells[1].textContent === "落后约 24 小时" &&
        page.cells[2].textContent === "—", JSON.stringify(page.cells.map((c) => c.textContent)));
  check("结果到达后通知 source-switch.js 重写链接", page.events.join() === "sourcechange", page.events.join());

  page.document.documentElement.lang = "zh-TW";
  page.listeners.langchange();
  check("切换到臺灣正體后提示随之更新",
        o.nju.title === "落後約 24 小時" && o.hernet.title === "上次檢查時無法連線" &&
        page.cells[0].textContent === "無法連線", JSON.stringify([o.nju.title, o.hernet.title]));
  page.document.documentElement.lang = "en";
  page.listeners.langchange();
  check("切换到英文后提示随之更新",
        o.nju.title === "About 24 hours behind" && o.hernet.title === "Unreachable at the last check" &&
        page.cells[0].textContent === "Unreachable", JSON.stringify([o.nju.title, o.hernet.title]));

  const inSync = JSON.parse(JSON.stringify(API));
  inSync.mirrors.list.forEach((m) => m.trees.forEach((t) => { t.lagSec = 0; t.up = true; }));
  const ok = run(answer(inSync), "en");
  await settle();
  check("全部同步：不标记任何选项，状态列写已同步",
        ok.opts.every((x) => !x.hasAttribute("data-behind")) && ok.cells[1].textContent === "In sync",
        JSON.stringify(ok.opts.map((x) => x.attrs)));

  for (const [name, impl] of [
    ["请求失败", () => Promise.reject(new Error("offline"))],
    ["非 2xx 响应", () => Promise.resolve({ ok: false, json: () => Promise.resolve(API) })],
    ["响应缺少镜像列表", answer({ updated: 1 })],
    ["镜像检查已超过两小时未更新", answer(Object.assign({}, API, { mirrors: Object.assign({}, API.mirrors, { updated: NOW - 3 * 3600 }) }))],
    ["镜像检查时间缺失", answer(Object.assign({}, API, { mirrors: Object.assign({}, API.mirrors, { updated: undefined }) }))],
  ]) {
    const bad = run(impl);
    await settle();
    check(name + "：页面保持原样",
          bad.opts.every((x) => !x.hasAttribute("data-behind") && !x.hasAttribute("data-down")) &&
          bad.cells.every((c) => c.textContent === "—") && bad.events.length === 0,
          JSON.stringify(bad.opts.map((x) => x.attrs)));
  }

  check("hostOf 取 data-uri 的主机名", page.api.hostOf("https://Mirrors.HA.edu.cn/gentoo-zh") === "mirrors.ha.edu.cn");

  process.exit(failed ? 1 : 0);
})();
