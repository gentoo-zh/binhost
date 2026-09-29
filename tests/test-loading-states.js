#!/usr/bin/env node
// Loading states: each region that fills after a fetch reserves its final size in the markup, and each
// page asks for its data from the head, for the same URL its script then fetches.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function inlineScripts(html) {
  return [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
}
function headScript(html, marker) {
  return inlineScripts(html.slice(0, html.indexOf("</head>"))).filter((s) => s.includes(marker))[0];
}
const nodeList = (items) => ({ length: items.length, forEach(f) { items.forEach(f); } });

// The head's preloads, given the address and the stored channel.
function preloads(script, pathname, stored) {
  const links = [];
  global.location = { pathname };
  global.localStorage = { getItem: (k) => (k === "mirror-channel" ? stored : null) };
  global.document = {
    createElement: () => ({}),
    head: { appendChild: (l) => links.push(l) },
  };
  (0, eval)(script);
  return links;
}

function el(id, attrs) {
  const a = Object.assign({}, attrs);
  return {
    id, innerHTML: "", textContent: "", className: "", hidden: false, value: "",
    dataset: {}, style: {}, attrs: a,
    parentElement: { hidden: false, setAttribute() {}, removeAttribute() {} },
    classList: { toggle() {}, contains: (c) => (a.class || "").split(" ").includes(c) },
    getAttribute: (k) => (k in a ? a[k] : null),
    setAttribute(k, v) { a[k] = String(v); }, removeAttribute(k) { delete a[k]; },
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return nodeList([]); },
  };
}

// Runs a page's main script with the given DOM extras and returns the URLs it fetched.
function mainFetches(html, pathname, stored, options) {
  const asked = [];
  const nodes = {};
  global.location = { pathname, hash: "", search: "", replace() {} };
  global.localStorage = { getItem: (k) => (k === "mirror-channel" ? stored : null) };
  global.window = { MIRROR_I18N: {}, addEventListener() {}, MIRROR_T: (k) => k };
  global.document = {
    documentElement: { lang: "zh-cn" },
    getElementById: (id) => (nodes[id] = nodes[id] || el(id)),
    querySelector: (sel) => ([".pkgs", ".deps-table", "#out .listing"].includes(sel) ? el(sel) : null),
    querySelectorAll: (sel) => nodeList(sel.includes("data-channel") ? options : []),
    addEventListener() {},
  };
  global.fetch = (url) => { asked.push(url); return new Promise(() => {}); };
  global.setTimeout = () => 0;
  global.clearTimeout = () => {};
  global.MutationObserver = class { observe() {} };
  (0, eval)(read("site/assets/util.js"));
  const scripts = inlineScripts(html);
  (0, eval)(scripts.sort((a, b) => b.length - a.length)[0]);
  return asked;
}

// The file browser: the head asks for the listing the page script fetches, at the root and below it.
const app = read("site/_app.html");
const appHead = headScript(app, "preload");
for (const p of ["/files/", "/distfiles/", "/binpkgs/x86-64/app-i18n/", "/distfiles/%E4%B8%AD%E6%96%87/"]) {
  const links = preloads(appHead, p);
  // The mirror status is a second, optional request that the head does not preload.
  const fetched = mainFetches(app, p, null, []).filter(function (u) { return u !== "/mirror-status.json"; });
  check(`文件浏览器 ${p}：head 预载的就是脚本请求的列表`,
        links.length === 1 && links[0].rel === "preload" && links[0].as === "fetch" &&
        links[0].crossOrigin === "anonymous" && fetched.length === 1 && links[0].href === fetched[0],
        JSON.stringify({ links, fetched }));
}

// The package list: the head preloads the stored channel's files, and the first load asks for exactly
// those, so no channel is fetched in vain.
const pkg = read("site/packages.html");
const pkgHead = headScript(pkg, "mirror-channel");
const options = [...pkg.matchAll(/<button type="button" class="(src-opt[^"]*)" data-channel="(\w+)"\s+data-path="([^"]+)" data-status="([^"]+)"\s+data-packages="([^"]+)"\s+data-package-text="([^"]+)"\s+data-deps-text="([^"]+)"/g)]
  .map((m) => el(m[2], { class: m[1], "data-channel": m[2], "data-path": m[3], "data-status": m[4],
                          "data-packages": m[5], "data-package-text": m[6], "data-deps-text": m[7] }));
check("包列表页有两个频道按钮", options.length === 2, String(options.length));
for (const stored of [null, "stable", "unstable", "bogus"]) {
  const links = preloads(pkgHead, "/packages", stored).map((l) => l.href).sort();
  const fetched = mainFetches(pkg, "/packages", stored, options).sort();
  check(`包列表页（存的频道：${stored}）：首次请求与 head 预载一致`,
        fetched.length === 3 && JSON.stringify(links) === JSON.stringify(fetched),
        JSON.stringify({ links, fetched }));
}

// Skeleton rows have the columns of the table they stand in for.
function columns(table) { return (table.match(/<th\b/g) || []).length; }
for (const [id, cls] of [["rows", "pkgs"], ["depRows", "deps-table"]]) {
  const table = pkg.slice(pkg.indexOf(`class="listing ${cls}"`));
  const head = table.slice(0, table.indexOf("</thead>"));
  const body = table.slice(table.indexOf(`<tbody id="${id}">`), table.indexOf("</tbody>"));
  const rows = [...body.matchAll(/<tr class="skeleton-row" aria-hidden="true">(.*?)<\/tr>/g)];
  check(`#${id} 的骨架行与表头列数相同`,
        rows.length > 0 && rows.every((r) => (r[1].match(/<td\b/g) || []).length === columns(head)),
        `${rows.length} 行`);
}
check("包列表加载期间标记为忙，加载提示只给读屏",
      /<div id="out" aria-busy="true">/.test(pkg) &&
      /<p class="msg visually-hidden" id="msg" role="status">/.test(pkg));

// The status page: the skeleton has as many rows as a complete status draws, in each region.
const status = read("site/status.html");
global.window = {};
global.document = { documentElement: { lang: "zh-cn", getAttribute: () => "zh-cn" },
                    getElementById: () => null, querySelector: () => null, addEventListener() {} };
global.fetch = () => new Promise(() => {});
(0, eval)(read("site/assets/status-data.js"));
const now = Math.floor(Date.now() / 1000);
const data = {
  channels: { stable: { overlay: 218, deps: 102, generated: now }, unstable: { overlay: 229, deps: 120, generated: now } },
  builds: { stable: { state: "done", finished: now, duration: 1757 }, unstable: { state: "done", finished: now, duration: 900 } },
  dist: { files: 1679, generated: now }, server: { uptime: 4595520, tx: 1076530502180, generated: now },
};
const rowsIn = (s) => (s.match(/<span class="row"/g) || []).length;
for (const [id, draw] of [["facts", "facts"], ["server-facts", "server"]]) {
  const region = status.slice(status.indexOf(`id="${id}"`), status.indexOf("</p>", status.indexOf(`id="${id}"`)));
  const drawn = rowsIn(global.window.MirrorStatus[draw](data));
  check(`状态页 #${id}：骨架 ${rowsIn(region)} 行，数据到后 ${drawn} 行`,
        /aria-busy="true"/.test(region) && rowsIn(region) === drawn && drawn > 0);
}

// Every JSON the status page and the overview always read is preloaded in the head.
for (const page of ["site/status.html", "site/index.html"]) {
  const html = read(page);
  const head = html.slice(0, html.indexOf("</head>"));
  const needed = ["/binpkgs/x86-64/status.json", "/unstable/binpkgs/x86-64/status.json", "/build-status.json",
                  "/build-status-unstable.json", "/distfiles-status.json", "/server-status.json"]
    .concat(page.endsWith("index.html") ? ["/packages.json"] : []);
  const missing = needed.filter((u) => !head.includes(`<link rel="preload" href="${u}" as="fetch" crossorigin>`));
  check(`${path.basename(page)} 在 head 预载全部数据`, missing.length === 0, missing.join(" "));
}

// Skeleton pulses and the ProgressCircle turn only when the reader has not asked for reduced motion.
const css = read("site/assets/site.css");
const block = css.slice(css.indexOf("@media (prefers-reduced-motion: no-preference) {\n  /* ProgressCircle"));
const outside = css.replace(block.slice(0, block.indexOf("\n}\n")), "");
check("加载动画只在未要求减少动态时播放",
      /\.progress-circle \{ animation: spin/.test(block) && !/animation: (spin|pulse)/.test(outside));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  加载状态：全部通过");
process.exit(failed ? 1 : 0);
