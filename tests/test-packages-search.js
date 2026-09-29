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
    ver: "", size: 0, declaresDist: false, dist: false, policy: "", why: "nobuild" },
  { cp: "app-i18n/libkkc-data", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: true, dist: false, policy: "", why: "candidate" },
  { cp: "acct-group/aptly", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "nobuild" },
  { cp: "app-misc/license-published", binhost: true, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "license", why: "" },
  { cp: "app-misc/excluded-published", binhost: false, excluded: "manual exclusion", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "candidate" },
  { cp: "app-misc/removed", binhost: false, excluded: "", present: false,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "removed" },
  { cp: "app-misc/channel-only", binhost: false, excluded: "", present: true,
    ver: "1", size: 1, declaresDist: false, dist: false, policy: "", why: "",
    channelExcluded: true },
]);
const matrix = renderWith("");
check("公开索引已有 binpkg 的行不显示待移除",
      (matrix.match(/class="mark yes"/g) || []).length === 10 &&
      (matrix.match(/class="mark no"/g) || []).length === 10 &&
      !matrix.includes("why_retiring") &&
      !matrix.includes('href="https://github.com/gentoo-zh/overlay/tree/master/app-misc/removed"'),
      matrix.slice(0, 1800));

window.MIRROR_T = (key) => (key === "policyPublished" ? "{policy} / published" : key);
const licensePublished = renderWith("app-misc/license-published");
delete window.MIRROR_T;
check("已发布包的当前政策显示在包名旁，提示不沿用未发布时的说明",
      (licensePublished.match(/>policyTag_license<\/span>/g) || []).length === 1 &&
      !licensePublished.includes(">why_license<") &&
      licensePublished.includes('title="policyNow_license / published"') &&
      !licensePublished.includes("whyLong_license") &&
      /policyTag_license<\/span><\/td><td class="mark yes">/.test(licensePublished),
      licensePublished.slice(0, 600));

const removed = renderWith("app-misc/removed");
check("overlay 已移除但仍在索引中的包标明已移除",
      (removed.match(/>why_removed<\/span>/g) || []).length === 1 &&
      /why_removed<\/span><\/td><td class="mark yes">/.test(removed),
      removed.slice(0, 600));

const exclusionPublished = renderWith("app-misc/excluded-published") +
  renderWith("app-misc/channel-only");
check("排除清单与频道排除的包已有 binpkg 时只显示勾号，原因在勾号提示中",
      exclusionPublished.includes("app-misc/excluded-published") &&
      exclusionPublished.includes("app-misc/channel-only") &&
      !exclusionPublished.includes("why-tag") &&
      exclusionPublished.includes('<td class="mark yes" title="manual exclusion">') &&
      exclusionPublished.includes('<td class="mark yes" title="whyLong_channelExcluded">'),
      exclusionPublished.slice(0, 900));

const acct = renderWith("acct-group/aptly");
check("已发布的 acct 包按普通包显示",
      acct.includes("acct-group/aptly") &&
      !acct.includes("why-tag") &&
      /<\/a><\/td><td class="mark yes">/.test(acct),
      acct.slice(0, 600));

const virtualUnpublished = renderWith("virtual/neither");
check("未发布的 virtual 包按清单外显示",
      (virtualUnpublished.match(/>why_nobuild<\/span>/g) || []).length === 1 &&
      /why_nobuild<\/span><\/td><td class="mark no"/.test(virtualUnpublished),
      virtualUnpublished.slice(0, 600));

setRows([{ cp: "app-misc/conditional-bindist", binhost: true, excluded: "",
           present: true, ver: "1", size: 1, declaresDist: false, dist: false,
           policy: "bindist", why: "" }]);
const bindistPublished = renderWith("");
check("已发布包旁的 bindist 标签不写成不提供 binpkg",
      (bindistPublished.match(/>policyTag_bindist<\/span>/g) || []).length === 1 &&
      !bindistPublished.includes(">why_bindist<") &&
      /class="mark yes"[^>]*>\u2713/.test(bindistPublished),
      bindistPublished.slice(0, 600));

check("图例分别说明发布、清单与政策状态",
      ["lgBuilt", "lgPending", "lgExcluded", "lgChannelExcluded", "lgDashBin",
       "lgRemoved", "lgDashDist"]
        .every((key) => html.includes(`data-i18n="${key}"`)) &&
      ["lgBindist", "lgLicense"]
        .every((key) => html.includes(`data-i18n-html="${key}"`)));

check("图例中的代码标记按富文本渲染",
      ["lgBindist", "lgLicense"].every((key) =>
        html.includes(`data-i18n-html="${key}"`)));

check("图例链接到 FAQ 的状态说明",
      html.includes('href="/faq#package-status"') &&
      html.includes('data-i18n="lgMore"'));

check("FAQ 说明 bindist 的常见原因与判定边界",
      faq.includes("源码包和上游预编译包都可能设置这项限制") &&
      faq.includes('包名含 <code>-bin</code> 本身不是判定依据') &&
      faq.includes('distfiles 是否镜像仍按 <code>RESTRICT</code>'));

check("FAQ 说明频道排除只影响本频道",
      faq.includes('data-i18n-html="stChannelExcluded"') &&
      faq.includes('data-i18n-html="sdChannelExcluded"') &&
      faq.includes('另一个频道仍可能发布该包'));

check("FAQ 状态表说明已移除与频道排除时的勾号",
      faq.includes('data-i18n-html="stRemoved"') &&
      faq.includes('data-i18n-html="sdRemoved"') &&
      faq.includes("排除原因在勾号的提示中"));

check("distfiles 破折号区分无文件与未完整镜像",
      matrix.includes('title="distNone"') &&
      matrix.includes('title="distUnavailable"'),
      matrix.slice(0, 1800));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  包列表搜索与状态：全部通过");
process.exit(failed ? 1 : 0);
