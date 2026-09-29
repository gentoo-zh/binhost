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
    attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); },
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return nodeList([]); },
  };
}

function crumbsFor(urlPath) {
  return load(urlPath, () => new Promise(() => {})).crumbs;
}

// Loads the page script at urlPath with the given fetch, and returns the elements it wrote and the
// timers it set, so a test can resolve the listing or let the wait run out.
function load(urlPath, fetchImpl) {
  const nodes = {};
  const timers = [];
  const events = [];
  const table = el("listing");
  global.document = {
    documentElement: { lang: "zh-cn" },
    getElementById(id) { return (nodes[id] = nodes[id] || el(id)); },
    querySelector: (sel) => (sel === "#out .listing" ? table : null),
    querySelectorAll() { return nodeList([]); },
    addEventListener() {},
    dispatchEvent(e) { events.push(e.type); },
  };
  global.window = {
    MIRROR_I18N: {}, addEventListener() {},
    MIRROR_T: (k) => ({ navFiles: "Files", title: "Files" }[k] || k),
  };
  global.location = { pathname: urlPath, replace() {} };
  global.fetch = fetchImpl;
  global.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  global.clearTimeout = (id) => { if (timers[id - 1]) timers[id - 1].cleared = true; };
  global.MutationObserver = class { observe() {} };
  (0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));

  const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1]);
  (0, eval)(blocks.sort((a, b) => b.length - a.length)[0] +
    "\nglobal.__rootDescriptions = ROOT_DESC;");
  const c = nodes.crumbs || el("crumbs");
  const full = nodes["where-path"] || el("where-path");
  return { nodes, table, timers, events,
           crumbs: { html: c.innerHTML, hidden: c.hidden,
                     title: (nodes.where || el("where")).textContent,
                     path: full.textContent, pathHidden: full.hidden } };
}

const settle = () => new Promise((r) => setImmediate(r));

function parse(s) {
  return [...s.matchAll(/<a href="([^"]*)">([^<]*)<\/a>/g)].map((m) => [m[2], m[1]]);
}

const root = crumbsFor("/files/");
check("根层不显示面包屑（标题已经写明位置）", root.hidden === true);
check("根层标题是页面名，不显示路径", root.title === "Files" && root.pathHidden === true,
      `${root.title} ${root.pathHidden}`);
check("根层说明区分默认 stable 与 unstable 频道",
      global.__rootDescriptions.binpkgs["zh-cn"] === "稳定频道 binpkg（默认）" &&
      global.__rootDescriptions.unstable["zh-cn"] === "测试频道 binpkg",
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
check("标题写的是当前目录名", deep.title === "app-editors", deep.title);
check("标题下写出完整路径", deep.path === "/binpkgs/x86-64/app-editors" && deep.pathHidden === false,
      `${deep.path} ${deep.pathHidden}`);
check("解码后的目录名作标题", crumbsFor("/distfiles/a%20b/").title === "a b");

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

(async function () {
  // The root listing: rows drawn, the loading line hidden, the wait cleared.
  const ROOT_LS = [{ name: "unstable", type: "directory", mtime: "Wed, 05 Aug 2026 16:12:02 GMT" },
                   { name: "binpkgs", type: "directory", mtime: "Mon, 10 Aug 2026 16:56:06 GMT" }];
  const asked = [];
  const ok = load("/files/", (url) => {
    asked.push(url);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(ROOT_LS) });
  });
  await settle();
  check("根层请求 /_ls/", asked.length === 1 && asked[0] === "/_ls/", JSON.stringify(asked));
  check("根层列出目录，并隐藏加载提示",
        ok.nodes.rows.innerHTML.includes('href="/binpkgs/"') &&
        ok.nodes.rows.innerHTML.includes('href="/unstable/"') &&
        ok.nodes.msg.hidden === true && ok.table.hidden === false, ok.nodes.rows.innerHTML);
  check("列表到达后不再标记为加载中", ok.nodes.out.attrs["aria-busy"] === "false",
        JSON.stringify(ok.nodes.out.attrs));
  check("根层不显示条目信息", ok.nodes.meta.hidden === true);
  check("列表到达后不再计时", ok.timers.length === 1 && ok.timers[0].cleared === true,
        JSON.stringify(ok.timers.map((x) => x.cleared)));

  // A listing that never arrives: after the wait the page says so instead of loading without end.
  const stalled = load("/binpkgs/x86-64/app-i18n/", () => new Promise(() => {}));
  await settle();
  // Loading is the markup's ProgressCircle row under a busy listing; no message line is added.
  check("子目录请求未返回时保留加载行，并先显示条目信息",
        !(stalled.nodes.msg && stalled.nodes.msg.textContent) && stalled.nodes.meta.hidden === false &&
        /id="out" class="dir-list" aria-busy="true"/.test(html) &&
        /<tbody id="rows">\s*<tr class="loading-row">[\s\S]*?role="progressbar"/.test(html),
        stalled.nodes.msg && stalled.nodes.msg.textContent);
  stalled.timers.forEach((x) => { if (!x.cleared) x.fn(); });
  check("等待超时后报告，不再停在加载中",
        stalled.nodes.msg.textContent === "timeout" && stalled.nodes.msg.hidden === false &&
        stalled.table.hidden === true && stalled.nodes.out.attrs["aria-busy"] === "false",
        stalled.nodes.msg.textContent);

  // Below the root a file link names its path for the mirror picker; a directory link does not, since
  // listings always come from the origin.
  const GIGOS_LS = [{ name: "2026 09", type: "directory", mtime: "Mon, 10 Aug 2026 16:56:06 GMT" },
                    { name: "gig os#1.iso", type: "file", size: 3, mtime: "Mon, 10 Aug 2026 16:56:06 GMT" }];
  const files = load("/gigos/%E4%B8%AD/", () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(GIGOS_LS) }));
  await settle();
  const rows = files.nodes.rows.innerHTML;
  check("文件链接写出其在镜像上的路径",
        rows.includes('href="gig%20os%231.iso" data-src-link="files" data-src-path="/gigos/%E4%B8%AD/gig%20os%231.iso"'),
        rows);
  check("目录链接不交给镜像选择器",
        /<a class="dir" href="2026%2009\/">/.test(rows) && (rows.match(/data-src-link/g) || []).length === 1, rows);
  check("列表画出后通知镜像选择器", files.events.includes("sourcechange"), JSON.stringify(files.events));

  // A directory named a&amp;b c%: the address bar keeps & and ; as they are, so the attribute must escape
  // them, or the parser turns &amp; back into & and the mirror link names another path.
  const amp = load("/distfiles/a&amp;b%20c%25/", () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([{ name: "x&y.iso", type: "file", size: 1 }]) }));
  await settle();
  check("文件的镜像路径经过属性转义，并保持地址栏的百分号编码",
        amp.nodes.rows.innerHTML.includes('data-src-path="/distfiles/a&amp;amp;b%20c%25/x%26y.iso"'),
        amp.nodes.rows.innerHTML);

  // An empty directory keeps the header and shows one message row in the body, as the package list's
  // no-match state does (reusing its .empty-row markup and CSS), instead of leaving the body blank.
  const empty = load("/distfiles/empty/", () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) }));
  await settle();
  check("空目录在表体显示一行提示，不是留白",
        /<tr class="empty-row"><td colspan="3">dirEmpty<\/td><\/tr>/.test(empty.nodes.rows.innerHTML) &&
        empty.table.hidden === false && empty.nodes.msg.hidden === true &&
        empty.nodes.out.attrs["aria-busy"] === "false",
        empty.nodes.rows.innerHTML);

  const emptyRoot = load("/files/", () =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) }));
  await settle();
  check("根层为空时提示行的列数与根层表头相同",
        /<tr class="empty-row"><td colspan="2">dirEmpty<\/td><\/tr>/.test(emptyRoot.nodes.rows.innerHTML),
        emptyRoot.nodes.rows.innerHTML);

  const gone = load("/distfiles/none/", () => Promise.resolve({ ok: false, status: 404 }));
  await settle();
  check("路径不存在时显示 notFound", gone.nodes.msg.textContent === "notFound",
        gone.nodes.msg.textContent);

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  文件浏览器：全部通过");
  process.exit(failed ? 1 : 0);
})();
