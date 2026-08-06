#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/packages.html"), "utf8");
const faq = fs.readFileSync(path.join(ROOT, "site/faq.html"), "utf8");

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function el(id) {
  const e = {
    id, innerHTML: "", textContent: "", className: "", hidden: false,
    dataset: {}, style: {}, value: "", parentElement: { hidden: false },
    classList: { toggle() {} },
    addEventListener() {},
    setAttribute() {},
    querySelectorAll() { return nodeList([]); },
  };
  e.querySelector = (sel) => (id === "out" && /listing/.test(sel) ? tables.pkgs : null);
  return e;
}
function nodeList(items) {
  return { length: items.length, forEach(f) { items.forEach(f); } };
}
const tables = { pkgs: el("pkgs-table"), deps: el("deps-table") };
const nodes = {};
global.document = {
  documentElement: { lang: "zh-cn" },
  getElementById(id) { return (nodes[id] = nodes[id] || el(id)); },
  querySelector(sel) {
    if (sel === ".pkgs") return tables.pkgs;
    if (sel === ".deps-table") return tables.deps;
    return null;
  },
  querySelectorAll() { return nodeList([]); },
  addEventListener() {},
};
global.window = { MIRROR_I18N: {}, addEventListener() {} };
global.location = { pathname: "/packages", hash: "" };
global.fetch = () => new Promise(() => {});
global.MutationObserver = class { observe() {} };

(0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));

const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1]);
if (!blocks.length) { console.log("  ✗ packages.html 未包含内联脚本"); process.exit(1); }
const script = blocks.sort((a, b) => b.length - a.length)[0] +
  "\n;globalThis.__t = { setRows: function (v) { rows = v; }, parsePackages: parsePackages };";
(0, eval)(script);

const setRows = (data) => globalThis.__t.setRows(data);

function renderWith(query) {
  nodes.q = nodes.q || el("q");
  nodes.q.value = query;
  document.getElementById("rows").innerHTML = "";
  render();
  return document.getElementById("rows").innerHTML;
}

setRows([
  { cp: "www-client/firefox-zh", desc: "Firefox 中文版", binhost: true, excluded: "",
    ver: "1.0", size: 10, declaresDist: true, dist: true, policy: "", why: "" },
  { cp: "app-misc/foobar", desc: "A fast web browser thing", binhost: true, excluded: "",
    ver: "2.0", size: 20, declaresDist: true, dist: true, policy: "", why: "" },
]);

const byName = renderWith("firefox");
check("包名搜索保留匹配行",
      byName.includes("www-client/firefox-zh") && !byName.includes("app-misc/foobar"),
      byName.slice(0, 400));

const byDescription = renderWith("browser");
check("说明字段不参与搜索", !byDescription, byDescription.slice(0, 400));

setRows([{ cp: "media-sound/open-orpheus-bin", desc: "Orpheus", binhost: false,
           excluded: "", ver: "", size: 0, declaresDist: true, dist: true,
           policy: "bindist", why: "prebuilt" }]);
const bindist = renderWith("");
check("发布政策与构建清单原因分别显示",
      (bindist.match(/>why_bindist<\/span>/g) || []).length === 1 &&
      !bindist.includes(">why_prebuilt</span>") &&
      bindist.includes("whyLong_bindist whyLong_prebuilt") &&
      /why_bindist<\/span><\/td><td class="mark yes">/.test(bindist),
      bindist.slice(0, 500));

const packages = [
  "PACKAGES: 3",
  "",
  "CPV: app-misc/same-9\nREPO: gentoo\nSIZE: 90",
  "",
  "CPV: app-misc/same-1\nREPO: gentoo-zh\nSIZE: 10",
  "",
  "CPV: app-misc/other-2\nREPO: gentoo-zh\nSIZE: 20",
].join("\n");
const overlayBuilt = globalThis.__t.parsePackages(packages, "gentoo-zh");
check("只把 gentoo-zh stanza 算作 overlay 二进制包",
      overlayBuilt["app-misc/same"].ver === "1" &&
      overlayBuilt["app-misc/other"].ver === "2",
      JSON.stringify(overlayBuilt));

setRows([
  { cp: "app-misc/both", binhost: true, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: true, dist: true, policy: "", why: "" },
  { cp: "app-misc/bin-only", binhost: true, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "" },
  { cp: "app-misc/src-only", binhost: false, excluded: "", present: true,
    ver: "", size: 0, declaresDist: true, dist: true, policy: "", why: "candidate" },
  { cp: "virtual/neither", binhost: false, excluded: "", present: true,
    ver: "", size: 0, declaresDist: false, dist: false, policy: "meta", why: "meta" },
  { cp: "app-i18n/libkkc-data", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: true, dist: false, policy: "", why: "candidate" },
  { cp: "acct-group/aptly", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "meta", why: "meta" },
  { cp: "app-misc/license-retiring", binhost: true, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "license", why: "" },
  { cp: "app-misc/excluded-retiring", binhost: false, excluded: "manual exclusion", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "candidate" },
  { cp: "app-misc/removed", binhost: false, excluded: "", present: false,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "removed" },
  { cp: "app-misc/channel-only", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "",
    channelExcluded: true },
]);
const matrix = renderWith("");
check("发布状态、当前政策与删除过渡同时渲染",
      (matrix.match(/class="mark yes"/g) || []).length === 10 &&
      (matrix.match(/class="mark no"/g) || []).length === 10 &&
      (matrix.match(/>why_retiring<\/span>/g) || []).length === 5 &&
      matrix.includes("whyLong_license") && matrix.includes("whyLong_removed") &&
      matrix.includes("whyLong_channelExcluded") &&
      !matrix.includes('href="https://github.com/gentoo-zh/overlay/tree/master/app-misc/removed"'),
      matrix.slice(0, 1800));

const closureDependency = renderWith("app-i18n/libkkc-data");
check("依赖闭包里的清单外套件不标成待移除",
      closureDependency.includes("app-i18n/libkkc-data") &&
      !closureDependency.includes("why_retiring"),
      closureDependency.slice(0, 600));

const sourceOnly = renderWith("acct-group/aptly");
check("公开索引里的本地安装类别标成待移除",
      (sourceOnly.match(/>why_meta<\/span>/g) || []).length === 1 &&
      sourceOnly.includes("why_retiring") &&
      /why_retiring<\/span><\/td><td class="mark yes">/.test(sourceOnly),
      sourceOnly.slice(0, 600));

const localOnly = renderWith("virtual/neither");
check("未发布的本地安装类别只显示一个状态标签",
      (localOnly.match(/>why_meta<\/span>/g) || []).length === 1 &&
      !localOnly.includes("why_retiring") &&
      /why_meta<\/span><\/td><td class="mark no"/.test(localOnly),
      localOnly.slice(0, 600));

check("图例分别说明发布、清单、政策与退役状态",
      ["lgBuilt", "lgPending", "lgExcluded", "lgChannelExcluded", "lgDashBin",
       "lgRetiring", "lgDashDist"]
        .every((key) => html.includes(`data-i18n="${key}"`)) &&
      ["lgBindist", "lgLicense", "lgMeta"]
        .every((key) => html.includes(`data-i18n-html="${key}"`)));

check("图例中的代码标记按富文本渲染",
      ["lgBindist", "lgLicense", "lgMeta"].every((key) =>
        html.includes(`data-i18n-html="${key}"`)));

check("图例链接到 FAQ 的状态说明",
      html.includes('href="/faq#package-status"') &&
      html.includes('data-i18n="lgMore"'));

check("FAQ 说明 bindist 的常见原因与判定边界",
      faq.includes("源码包和上游预编译包都可能设置这项限制") &&
      faq.includes('包名含 <code>-bin</code> 本身不是判定依据') &&
      faq.includes('distfiles 是否镜像仍按 <code>RESTRICT</code>'));

check("FAQ 说明频道排除与待移除的关系",
      faq.includes('data-i18n-html="stChannelExcluded"') &&
      faq.includes('data-i18n-html="sdChannelExcluded"') &&
      faq.includes('另一个频道仍可能发布该包'));

check("distfiles 破折号区分无文件与未完整镜像",
      matrix.includes('title="distNone"') &&
      matrix.includes('title="distUnavailable"'),
      matrix.slice(0, 1800));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  包列表搜索与状态：全部通过");
process.exit(failed ? 1 : 0);
