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
  (0, eval)(blocks.sort((a, b) => b.length - a.length)[0] +
    "\nglobal.__rootDescriptions = ROOT_DESC;");
  const c = nodes.crumbs || el("crumbs");
  return { html: c.innerHTML, hidden: c.hidden,
           title: (nodes.where || el("where")).textContent };
}

function parse(s) {
  return [...s.matchAll(/<a href="([^"]*)">([^<]*)<\/a>/g)].map((m) => [m[2], m[1]]);
}

const root = crumbsFor("/files/");
check("根层不显示面包屑（标题已经写明位置）", root.hidden === true);
check("根层说明区分默认 stable 与 unstable 频道",
      global.__rootDescriptions.binpkgs["zh-cn"] === "稳定频道二进制包（默认）" &&
      global.__rootDescriptions.unstable["zh-cn"] === "测试频道二进制包",
      JSON.stringify(global.__rootDescriptions));
check("频道说明提供三种语言",
      ["binpkgs", "unstable"].every((name) =>
        ["zh-cn", "zh-tw", "en"].every((locale) =>
          Boolean(global.__rootDescriptions[name][locale]))),
      JSON.stringify(global.__rootDescriptions));

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
check("名字里的空格与 & 在地址上编码",
      osegs[2] && osegs[2][1] === "/distfiles/a%20b%26c/", JSON.stringify(osegs[2]));

const q = parse(crumbsFor("/distfiles/a?b/").html);
check("名字里的 ? 在地址上编码",
      q[2] && q[2][1] === "/distfiles/a%3Fb/", JSON.stringify(q[2]));

const h = parse(crumbsFor("/distfiles/a#b/").html);
check("名字里的 # 在地址上编码",
      h[2] && h[2][1] === "/distfiles/a%23b/", JSON.stringify(h[2]));

const pct = parse(crumbsFor("/distfiles/100%25/").html);
check("名字里的 % 在地址上编码",
      pct[2] && pct[2][1] === "/distfiles/100%25/", JSON.stringify(pct[2]));

let survived = true;
try { crumbsFor("/distfiles/100%/"); } catch (e) { survived = false; }
check("地址里有非法的 % 时不抛异常", survived, "抛了异常");

const cjk = parse(crumbsFor("/distfiles/中文/").html);
check("中文目录名按相同规则编码",
      cjk[2] && cjk[2][1] === "/distfiles/" + encodeURIComponent("中文") + "/",
      JSON.stringify(cjk[2]));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  文件浏览器面包屑：全部通过");
process.exit(failed ? 1 : 0);
