#!/usr/bin/env node
// mirror-health.js reads the public status API once and marks each mirror picker option whose mirror is
// down or behind, matching entries by the host of the option's data-uri. A tree is behind once the first
// index it lacks has been out more than 30 hours; until then it is only pending and marks nothing. A failed
// request leaves the page as it was. On the status page it also writes one row per mirror into
// #mirror-facts, or the fallback line when the answer is missing or stale.

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
    label: null, prepended: null,
    querySelector(sel) { return sel === ".channel-field" ? this.label : null; },
    prepend(n) { this.prepended = n; },
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
const API = { updated: NOW, overall: "ok", sites: [], events: [], mirrors: { updated: NOW,
  published: [{ key: "stable", ageSec: 3600 }, { key: "unstable", ageSec: 7200 }], list: [
  { host: "distfiles.gentoozh.org", key: "src", origin: true, up: true, trees: [tree("stable", 0), tree("unstable", 0)] },
  { host: "mirror.nju.edu.cn", key: "nju", up: true, trees: [tree("stable", 84715), tree("unstable", 3600)] },
  { host: "mirrors.ha.edu.cn", key: "ha", up: true, trees: [tree("stable", 0), tree("unstable", 0, false)] },
  { host: "ftp2.osuosl.org", key: "osuosl", up: true, trees: [tree("stable", 21000), tree("unstable", 0)] },
] } };

// The status page's mirror names, as i18n.js would return them for the current language.
const NAMES = {
  "zh-CN": { mNju: "南京大学", mHernet: "河南教育网", mOsuosl: "俄勒冈州立大学开源实验室" },
  en: { mNju: "Nanjing University", mHernet: "HERNET", mOsuosl: "Oregon State University Open Source Lab" },
};

// Runs the script against a page of options and cells, plus the status page's section when status is
// set; fetchImpl answers the one request.
function run(fetchImpl, lang, status) {
  const opts = Object.keys(HOSTS).map((k) => el({ "data-uri": HOSTS[k] }));
  const cells = ["mirrors.ha.edu.cn", "mirror.nju.edu.cn", "unlisted.example"].map((h) => el({ "data-mirror-host": h }));
  cells.forEach((c) => { c.textContent = "—"; });
  cells[0].label = { className: "channel-field" };
  const listeners = {}, events = [], asked = [];
  const ids = {};
  if (status) {
    ids["mirror-facts"] = el({ "aria-busy": "true" });
    ids["mirror-facts"].innerHTML = "<span class=\"row\" aria-hidden=\"true\"></span>";
    ids["mirror-more"] = el({});
    ids["mirror-failed"] = el({});
    ids["mirror-failed"].hidden = true;
  }
  const document = {
    documentElement: { lang: lang || "zh-CN" },
    getElementById(id) { return ids[id] || null; },
    querySelectorAll(sel) {
      if (sel === ".src-opt[data-uri]") return opts;
      if (sel === "[data-mirror-host]") return cells;
      throw new Error("unexpected selector " + sel);
    },
    addEventListener(type, fn) { listeners[type] = fn; },
    dispatchEvent(e) { events.push(e.type); },
  };
  const window = {};
  if (status) {
    window.MIRROR_T = (k) => NAMES[document.documentElement.lang][k];
    window.MirrorStatus = { age: () => document.documentElement.lang === "en" ? "3 minutes ago" : "3 分钟前" };
  }
  const ctx = {
    document, window,
    CustomEvent: function (type) { this.type = type; },
    setTimeout: () => 0, clearTimeout: () => {},
    fetch: (url, init) => { asked.push(url); return fetchImpl(url, init); },
  };
  vm.runInNewContext(src, ctx);
  return { opts, cells, ids, listeners, events, asked, document, api: ctx.window.MirrorHealth };
}
const byKey = (page) => Object.fromEntries(Object.keys(HOSTS).map((k, i) => [k, page.opts[i]]));
const settle = () => new Promise((r) => setImmediate(r));
const answer = (j) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(j) });
// A copy of the fake API with Nanjing University's stable lag, and the stable index's age when given.
function nju(lagSec, ageSec) {
  const j = JSON.parse(JSON.stringify(API));
  j.mirrors.list[1].trees[0].lagSec = lagSec;
  if (ageSec === undefined) delete j.mirrors.published;
  else j.mirrors.published[0].ageSec = ageSec;
  return j;
}

(async function () {
  const page = run(answer(API));
  await settle();
  const o = byKey(page);
  check("只请求一次状态 API", page.asked.length === 1 && page.asked[0] === "https://status.gentoozh.org/api/status",
        JSON.stringify(page.asked));
  check("落后约一天但最新索引刚发布一小时：尚未同步，不标记也不提示",
        !o.nju.hasAttribute("data-behind") && o.nju.title === "" && !o.nju.hasAttribute("data-down"),
        JSON.stringify([o.nju.attrs, o.nju.title]));
  check("按主机名匹配：mirrors.ha.edu.cn 对应 API 的 ha，任一树不可达即视为无法连接",
        o.hernet.hasAttribute("data-behind") && o.hernet.hasAttribute("data-down") &&
        o.hernet.title === "上次检查时无法连接", JSON.stringify([o.hernet.attrs, o.hernet.title]));
  check("尚未同步与已同步的镜像不标记",
        !o.osuosl.hasAttribute("data-behind") && !o.origin.hasAttribute("data-behind") && o.osuosl.title === "",
        JSON.stringify([o.osuosl.attrs, o.origin.attrs]));
  check("API 未列出的镜像保持原样", !o.other.hasAttribute("data-behind") && o.other.title === "");
  check("镜像页状态列：无法连接、尚未同步、未列出",
        page.cells[0].textContent === "无法连接" && page.cells[1].textContent === "尚未同步最新版" &&
        page.cells[2].textContent === "—" && page.cells[0].hasAttribute("data-behind") &&
        !page.cells[1].hasAttribute("data-behind"), JSON.stringify(page.cells.map((c) => [c.textContent, c.attrs])));
  check("镜像页状态列写入后保留窄屏字段标签",
        page.cells[0].prepended === page.cells[0].label && page.cells[1].prepended === null);
  check("结果到达后通知 source-switch.js 重写链接", page.events.join() === "sourcechange", page.events.join());

  page.document.documentElement.lang = "zh-TW";
  page.listeners.langchange();
  check("切换到臺灣正體后提示随之更新",
        o.nju.title === "" && o.hernet.title === "上次檢查時無法連線" &&
        page.cells[0].textContent === "無法連線" && page.cells[1].textContent === "尚未同步最新版",
        JSON.stringify([o.nju.title, o.hernet.title, page.cells[1].textContent]));
  page.document.documentElement.lang = "en";
  page.listeners.langchange();
  check("切换到英文后提示随之更新",
        o.nju.title === "" && o.hernet.title === "Unreachable at the last check" &&
        page.cells[0].textContent === "Unreachable" && page.cells[1].textContent === "Latest not synced yet",
        JSON.stringify([o.nju.title, o.hernet.title, page.cells[1].textContent]));

  // Staleness is the newest index's age plus each day of lag past the first; up to 30 hours is pending.
  for (const [name, j, cell, behind] of [
    ["落后两天多、最新索引发布两小时：共 27 小时，尚未同步", nju(2 * 86400 + 3600, 7200), "尚未同步最新版", false],
    ["正好 30 小时仍算尚未同步", nju(86400 + 29 * 3600, 3600), "尚未同步最新版", false],
    ["落后三天、最新索引发布一小时：共 49 小时，标记落后", nju(3 * 86400, 3600), "落后约 49 小时", true],
    ["缺少发布时间时按延迟本身判断", nju(40 * 3600), "落后约 40 小时", true],
    ["缺少发布时间且延迟不足 30 小时：尚未同步", nju(84715), "尚未同步最新版", false],
  ]) {
    const p = run(answer(j));
    await settle();
    const n = byKey(p).nju;
    check(name,
          p.cells[1].textContent === cell && p.cells[1].hasAttribute("data-behind") === behind &&
          n.hasAttribute("data-behind") === behind && n.title === (behind ? cell : "") &&
          !n.hasAttribute("data-down"), JSON.stringify([p.cells[1].textContent, p.cells[1].attrs, n.attrs, n.title]));
  }

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

  // The status page: one row per mirror in the API's order, the origin left out.
  const rowsOf = (html) => html.split('<span class="row">').slice(1);
  const part = (tree, word) => '<span class="sub">' + tree + '</span> <b class="num">' + word + "</b>";
  let pending;
  const st = run(() => new Promise((r) => { pending = r; }), "zh-CN", true);
  st.listeners.langchange();
  check("状态页：结果到达前保留骨架屏",
        st.ids["mirror-facts"].innerHTML.includes("aria-hidden") &&
        st.ids["mirror-facts"].getAttribute("aria-busy") === "true", st.ids["mirror-facts"].innerHTML);
  pending({ ok: true, json: () => Promise.resolve(API) });
  await settle();
  const box = st.ids["mirror-facts"], rows = rowsOf(box.innerHTML);
  check("状态页：每个下游镜像一行，跳过源站，顺序同 API",
        rows.length === 3 && rows[0].includes("南京大学") && rows[1].includes("河南教育网") &&
        rows[2].includes("俄勒冈州立大学开源实验室") && !box.innerHTML.includes("distfiles.gentoozh.org"),
        box.innerHTML);
  check("状态页：南京大学两棵树都尚未同步",
        rows[0].includes(part("stable", "尚未同步最新版")) && rows[0].includes(part("unstable", "尚未同步最新版")),
        rows[0]);
  check("状态页：河南教育网 unstable 无法连接",
        rows[1].includes(part("stable", "已同步")) && rows[1].includes(part("unstable", "无法连接")), rows[1]);
  check("状态页：无延迟的树写已同步",
        rows[2].includes(part("stable", "尚未同步最新版")) && rows[2].includes(part("unstable", "已同步")), rows[2]);
  check("状态页：时间列写检查时间", rows[0].includes('<span class="when">检查于 <b>3 分钟前</b>'), rows[0]);
  check("状态页：清除忙碌状态，显示说明行，隐藏失败提示",
        box.getAttribute("aria-busy") === "false" && !box.hidden && !st.ids["mirror-more"].hidden &&
        st.ids["mirror-failed"].hidden);
  st.document.documentElement.lang = "en";
  st.listeners.langchange();
  const en = rowsOf(box.innerHTML);
  check("状态页：切换到英文后重新渲染",
        en[0].includes("Nanjing University") && en[0].includes(part("stable", "Latest not synced yet")) &&
        en[1].includes(part("unstable", "Unreachable")) && en[2].includes(part("unstable", "In sync")) &&
        en[0].includes("Checked <b>3 minutes ago</b>"), box.innerHTML);

  const late = run(answer(nju(3 * 86400, 3600)), "zh-CN", true);
  await settle();
  const lateRows = rowsOf(late.ids["mirror-facts"].innerHTML);
  check("状态页：每棵树各写自己的状态",
        lateRows[0].includes(part("stable", "落后约 49 小时")) &&
        lateRows[0].includes(part("unstable", "尚未同步最新版")), lateRows[0]);

  const down = JSON.parse(JSON.stringify(API));
  down.mirrors.list[3].up = false;
  const off = run(answer(down), "zh-CN", true);
  await settle();
  const offRows = rowsOf(off.ids["mirror-facts"].innerHTML);
  check("状态页：镜像本身不可达时两棵树都写无法连接",
        offRows[2].includes(part("stable", "无法连接")) && offRows[2].includes(part("unstable", "无法连接")),
        offRows[2]);

  for (const [name, impl] of [
    ["请求失败", () => Promise.reject(new Error("offline"))],
    ["镜像检查已超过两小时未更新", answer(Object.assign({}, API, { mirrors: Object.assign({}, API.mirrors, { updated: NOW - 3 * 3600 }) }))],
  ]) {
    const bad = run(impl, "zh-CN", true);
    await settle();
    const b = bad.ids["mirror-facts"];
    check("状态页" + name + "：移除骨架屏，只显示失败提示",
          b.innerHTML === "" && b.hidden && b.getAttribute("aria-busy") === "false" &&
          bad.ids["mirror-more"].hidden && !bad.ids["mirror-failed"].hidden && bad.events.length === 0,
          JSON.stringify([b.innerHTML, b.hidden, bad.ids["mirror-failed"].hidden]));
  }

  check("hostOf 取 data-uri 的主机名", page.api.hostOf("https://Mirrors.HA.edu.cn/gentoo-zh") === "mirrors.ha.edu.cn");

  process.exit(failed ? 1 : 0);
})();
