#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/_app.html"), "utf8");

let failed = 0;
function check(name, cond, detail) {
  if (cond) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function nodeList(items) {
  return { length: items.length, forEach(f) { items.forEach(f); } };
}
function el(id) {
  return {
    id, innerHTML: "", textContent: "", className: "", hidden: false,
    dataset: {}, style: {},
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return nodeList([]); },
  };
}

function crumbsFor(urlPath) {
  const nodes = {};
  global.document = {
    documentElement: { lang: "zh-cn" },
    getElementById(id) { return (nodes[id] = nodes[id] || el(id)); },
    querySelector: () => null,
    querySelectorAll() { return nodeList([]); },
    addEventListener() {},
  };
  global.window = {
    MIRROR_I18N: {}, addEventListener() {},
    MIRROR_T: (k) => ({ navFiles: "Files", title: "Files" }[k] || k),
  };
  global.location = { pathname: urlPath, replace() {} };
  global.fetch = () => new Promise(() => {});
  global.MutationObserver = class { observe() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));

  const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1]);
  (0, eval)(blocks.sort((a, b) => b.length - a.length)[0]);
  const c = nodes.crumbs || el("crumbs");
  return { html: c.innerHTML, hidden: c.hidden,
           title: (nodes.where || el("where")).textContent };
}

function parse(s) {
  return [...s.matchAll(/<a href="([^"]*)">([^<]*)<\/a>/g)].map((m) => [m[2], m[1]]);
}

const root = crumbsFor("/files/");
check("根层不显示面包屑（标题已经写明位置）", root.hidden === true);

for (const [dir, label] of [["binpkgs", "binpkgs"], ["distfiles", "distfiles"]]) {
  const r = crumbsFor(`/${dir}/`);
  const segs = parse(r.html);
  check(`/${dir}/ 的节数`, segs.length === 2, JSON.stringify(segs));
  check(`/${dir}/ 第一节回文件浏览器根`,
        segs[0] && segs[0][0] === "Files" && segs[0][1] === "/files/", JSON.stringify(segs[0]));
  check(`/${dir}/ 第二节标签是 ${label}，不是被切剩的碎片`,
        segs[1] && segs[1][0] === label, JSON.stringify(segs[1]));
  check(`/${dir}/ 第二节地址是 /${dir}/`,
        segs[1] && segs[1][1] === `/${dir}/`, JSON.stringify(segs[1]));
}

const deep = crumbsFor("/binpkgs/x86-64/app-editors/");
const dsegs = parse(deep.html);
check("深层每一节都在", dsegs.length === 4, JSON.stringify(dsegs));
check("深层各节地址逐级累加",
      JSON.stringify(dsegs.map((s) => s[1])) ===
      JSON.stringify(["/files/", "/binpkgs/", "/binpkgs/x86-64/", "/binpkgs/x86-64/app-editors/"]),
      JSON.stringify(dsegs.map((s) => s[1])));
check("标题写的是当前路径", deep.title === "/binpkgs/x86-64/app-editors", deep.title);

const odd = crumbsFor("/distfiles/a b&c/");
const osegs = parse(odd.html);
check("名字里的 & 在标签上转义",
      odd.html.includes("a b&amp;c"), odd.html.slice(0, 200));
check("名字里的空格在地址上编码",
      osegs[2] && osegs[2][1] === "/distfiles/a%20b&c/", JSON.stringify(osegs[2]));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  文件浏览器面包屑：全部通过");
process.exit(failed ? 1 : 0);
