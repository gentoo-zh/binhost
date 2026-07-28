#!/usr/bin/env node
// 包列表的搜索：靠说明命中的行要自己说明白为什么被搜出来。
//
// 窄屏把说明那一列整列 display:none，而搜索照样比对说明，于是名字里没有这个词的
// 包出现在结果里、没有任何线索。这个测试执行 packages.html 里的 render()，
// 检查它给这类行补的那一句。
//
// 页面脚本是内联的，所以这里把 <script> 块抠出来在假 DOM 里执行。

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

// --- 假 DOM ------------------------------------------------------------------
// 只做这个测试用得到的部分。元素按 id 存，render() 要的就是 #out。
function el(id) {
  return {
    id, innerHTML: "", textContent: "", className: "", hidden: false,
    dataset: {}, style: {},
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return nodeList([]); },
  };
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
// 页面加载时就会去取数据。这里不测取数据，挂住即可。
global.fetch = () => new Promise(() => {});
global.MutationObserver = class { observe() {} };

// util.js 提供 esc / human，页面依赖它们
(0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));

// --- 抠出页面的内联脚本 --------------------------------------------------------
// 带 src 的不算，那些上面已经单独载入。取最长的一段，就是渲染那一块。
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1]);
if (!blocks.length) { console.log("  ✗ packages.html 里没有内联脚本"); process.exit(1); }
// 页面里 rows、filter 是顶层 let。eval 里的 let 落在这一次 eval 自己的词法
// 环境，外面够不着（函数声明才会落到 globalThis，所以 render 拿得到）。在同一段
// 文本末尾附一个取用点，它和被测代码共用那个环境。被测代码本身一个字没改。
const script = blocks.sort((a, b) => b.length - a.length)[0] +
  "\n;globalThis.__t = { setRows: function (v) { rows = v; } };";
(0, eval)(script);

// --- 数据 --------------------------------------------------------------------
const setRows = (data) => globalThis.__t.setRows(data);

function renderWith(query) {
  nodes.q = nodes.q || el("q");
  nodes.q.value = query;
  document.getElementById("out").innerHTML = "";
  render();
  return document.getElementById("out").innerHTML;
}

// 一个名字里带 firefox、说明里没有；一个反过来。搜 "browser" 只该命中后者的说明。
setRows([
  { cp: "www-client/firefox-zh", desc: "Firefox 中文版", binhost: true, excluded: "",
    ver: "1.0", size: 10, dist: true, why: "" },
  { cp: "app-misc/foobar", desc: "A fast web browser thing", binhost: true, excluded: "",
    ver: "2.0", size: 20, dist: true, why: "" },
]);

// --- 检查 --------------------------------------------------------------------
const byDesc = renderWith("browser");
check("靠说明命中的行补了一句 hit-desc",
      byDesc.includes('class="hit-desc"'), byDesc.slice(0, 400));
check("补的那一句里把命中的词圈了出来",
      /<mark>browser<\/mark>/i.test(byDesc), byDesc.slice(0, 400));
check("只有靠说明命中的那一行有",
      (byDesc.match(/class="hit-desc"/g) || []).length === 1);

const byName = renderWith("firefox");
check("名字命中的行不补（说明列本来就在，补了是重复）",
      !byName.includes('class="hit-desc"'));

const noQuery = renderWith("");
check("没有搜索词时一行都不补",
      !noQuery.includes('class="hit-desc"'));

// 说明是外部数据，进 innerHTML 前必须转义。<mark> 是我们自己拼的，不能因此把
// 说明里的尖括号一起当标签送出去。
setRows([{ cp: "app-misc/evil", desc: 'x <img src=q onerror=alert(1)> browser',
           binhost: true, excluded: "", ver: "1", size: 1, dist: true, why: "" }]);
const escaped = renderWith("browser");
check("说明里的标签被转义，没有原样进 DOM",
      !escaped.includes("<img src=q") && escaped.includes("&lt;img"),
      escaped.slice(0, 400));

// 命中的词本身也可能带尖括号
setRows([{ cp: "app-misc/e2", desc: "see <b>bold</b> here", binhost: true, excluded: "",
           ver: "1", size: 1, dist: true, why: "" }]);
const escaped2 = renderWith("<b>");
check("命中的词带标签时同样转义",
      escaped2.includes("<mark>&lt;b&gt;</mark>"), escaped2.slice(0, 400));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  搜索命中说明的提示：全部通过");
process.exit(failed ? 1 : 0);
