#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/packages.html"), "utf8");

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function el(id) {
  const e = {
    id, innerHTML: "", textContent: "", className: "", hidden: false,
    dataset: {}, style: {},
    addEventListener() {},
    querySelectorAll() { return nodeList([]); },
  };
  e.querySelector = (sel) => (id === "out" && /listing/.test(sel) ? el("table") : null);
  return e;
}
function nodeList(items) {
  return { length: items.length, forEach(f) { items.forEach(f); } };
}
const nodes = {};
global.document = {
  documentElement: { lang: "zh-cn" },
  getElementById(id) { return (nodes[id] = nodes[id] || el(id)); },
  querySelector() { return null; },
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
  "\n;globalThis.__t = { setRows: function (v) { rows = v; } };";
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
    ver: "1.0", size: 10, dist: true, why: "" },
  { cp: "app-misc/foobar", desc: "A fast web browser thing", binhost: true, excluded: "",
    ver: "2.0", size: 20, dist: true, why: "" },
]);

const byDesc = renderWith("browser");
check("靠说明命中的行补了一句 hit-desc",
      byDesc.includes('class="hit-desc"'), byDesc.slice(0, 400));
check("补的那一句里把命中的词标记出来",
      /<mark>browser<\/mark>/i.test(byDesc), byDesc.slice(0, 400));
check("只有靠说明命中的那一行有",
      (byDesc.match(/class="hit-desc"/g) || []).length === 1);

const byName = renderWith("firefox");
check("名字命中的行不补（说明列本来就在，补了是重复）",
      !byName.includes('class="hit-desc"'));

const noQuery = renderWith("");
check("没有搜索词时一行都不补",
      !noQuery.includes('class="hit-desc"'));

setRows([{ cp: "app-misc/evil", desc: 'x <img src=q onerror=alert(1)> browser',
           binhost: true, excluded: "", ver: "1", size: 1, dist: true, why: "" }]);
const escaped = renderWith("browser");
check("说明里的标签被转义，没有原样进 DOM",
      !escaped.includes("<img src=q") && escaped.includes("&lt;img"),
      escaped.slice(0, 400));

setRows([{ cp: "app-misc/e2", desc: "see <b>bold</b> here", binhost: true, excluded: "",
           ver: "1", size: 1, dist: true, why: "" }]);
const escaped2 = renderWith("<b>");
check("命中的词带标签时同样转义",
      escaped2.includes("<mark>&lt;b&gt;</mark>"), escaped2.slice(0, 400));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  搜索命中说明的提示：全部通过");
process.exit(failed ? 1 : 0);
