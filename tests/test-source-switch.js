#!/usr/bin/env node
// Mirror pickers on the two setup pages and in the file browser: the language default, the addresses
// and download links they write, and the mirror choice carried from one page to the next through
// localStorage.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const read = (name) => fs.readFileSync(path.join(ROOT, "site", name), "utf8");
const script = fs.readFileSync(path.join(ROOT, "site/assets/source-switch.js"), "utf8");
const mirrorsPage = read("mirrors.html");

let failed = 0;
function check(name, condition, detail) {
  if (condition) { console.log("  ✓ " + name); return; }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

function attr(text, name) {
  const match = new RegExp(name + '="([^"]*)"').exec(text);
  return match ? match[1] : null;
}

function element(attributes, className) {
  const attrs = Object.assign({}, attributes);
  const classes = new Set((className || "").split(/\s+/).filter(Boolean));
  const listeners = {};
  return {
    textContent: "",
    classList: {
      contains(name) { return classes.has(name); },
      toggle(name, enabled) {
        if (enabled) classes.add(name);
        else classes.delete(name);
      },
    },
    getAttribute(name) { return attrs[name] === undefined ? null : attrs[name]; },
    hasAttribute(name) { return attrs[name] !== undefined && attrs[name] !== null; },
    setAttribute(name, value) { attrs[name] = String(value); },
    addEventListener(name, listener) { listeners[name] = listener; },
    click() { listeners.click(); },
  };
}

function storage(initial, broken) {
  const data = Object.assign({}, initial);
  return {
    data,
    getItem(key) { if (broken) throw new Error("denied"); return key in data ? data[key] : null; },
    setItem(key, value) { if (broken) throw new Error("denied"); data[key] = String(value); },
  };
}

// Loads one page's pickers into a stub document and runs source-switch.js over them.
function load(page, lang, store, links) {
  const html = read(page);
  const groups = [...html.matchAll(
    /<div class="src-pick"([^>]*)data-src-switch="([^"]+)"([^>]*)>([\s\S]*?)<\/div>/g
  )].map(function (match) {
    const groupAttrs = match[1] + match[3];
    const opts = [...match[4].matchAll(/<button\b([^>]*)>[\s\S]*?<\/button>/g)]
      .filter((button) => /\bsrc-opt\b/.test(attr(button[1], "class") || ""))
      .map((button) => element({
        "data-uri": attr(button[1], "data-uri"),
        "data-src-default": attr(button[1], "data-src-default") || "",
        "data-src-here": /\sdata-src-here\b/.test(button[1]) ? "" : null,
      }, attr(button[1], "class")));
    const group = element({
      "data-src-switch": match[2],
      "data-src-group": attr(groupAttrs, "data-src-group") || "",
      "data-src-list": (/data-src-list='([^']*)'/.exec(groupAttrs) || [])[1] || null,
    });
    group.opts = opts;
    group.querySelectorAll = (selector) => (selector === ".src-opt" ? opts : []);
    return group;
  });
  const slots = {};
  for (const m of html.matchAll(/data-src-slot="(\w+)"([^>]*)>/g)) {
    slots[m[1]] = slots[m[1]] || element({ "data-src-suffix": attr(m[2], "data-src-suffix") || "" });
  }
  const copies = {};
  for (const m of html.matchAll(/data-src-copy="(\w+)"([^>]*)>/g)) {
    copies[m[1]] = copies[m[1]] || element({ "data-src-suffix": attr(m[2], "data-src-suffix") || "" });
  }
  const root = element({ "data-lang": lang });
  const listeners = {};
  const winListeners = {};
  global.document = {
    documentElement: root,
    querySelectorAll(selector) {
      if (selector === "[data-src-switch]") return groups;
      let m = /^\[data-src-slot="(\w+)"\]$/.exec(selector);
      if (m) return slots[m[1]] ? [slots[m[1]]] : [];
      m = /^\.copy-chip\[data-src-copy="(\w+)"\]$/.exec(selector);
      if (m) return copies[m[1]] ? [copies[m[1]]] : [];
      m = /^a\[data-src-link="(\w+)"\]$/.exec(selector);
      if (m) return (links || []).filter((a) => a.getAttribute("data-src-link") === m[1]);
      return [];
    },
    addEventListener(name, listener) { listeners[name] = listener; },
  };
  global.window = { addEventListener(name, listener) { winListeners[name] = listener; } };
  global.localStorage = store;
  (0, eval)(script);
  const selected = () => groups
    .filter((g) => (g.getAttribute("data-src-group") || "mirror") === "mirror")
    .map((g) => { const o = g.opts.find((i) => i.classList.contains("on")); return o && o.getAttribute("data-uri"); });
  const choose = (uri) => groups[0].opts.find((o) => o.getAttribute("data-uri") === uri).click();
  return { groups, slots, copies, root, listeners, winListeners, selected, choose };
}

const cernet = "https://mirrors.cernet.edu.cn/gentoo-zh";
const origin = "https://distfiles.gentoozh.org";
const osuosl = "https://ftp2.osuosl.org/pub/gentoo-zh";
const nju = "https://mirror.nju.edu.cn/gentoo-zh";
const all = (list, uri) => list.length > 0 && list.every((u) => u === uri);

// Binary package setup: two pickers (top and step 2) moving together.
const bin = load("binpkg-setup.html", "zh-cn", storage());
check("binary package 配置页包含两组镜像选择器", bin.groups.length === 2, String(bin.groups.length));
const uris = bin.groups[0].opts.map((o) => o.getAttribute("data-uri"));
check("镜像页列出配置页的全部镜像",
      uris.length === 6 && uris.every((u) => mirrorsPage.includes('href="' + u + '"') || u === origin),
      JSON.stringify(uris));
check("简体中文默认选择教育网联合镜像站", all(bin.selected(), cernet), JSON.stringify(bin.selected()));
check("镜像选择器会写出完整 binary package 地址",
      bin.slots.top.textContent === cernet + "/binpkgs/x86-64" &&
      bin.copies.top.getAttribute("data-copy") === cernet + "/binpkgs/x86-64");
bin.slots.top.setAttribute("data-src-suffix", "/unstable/binpkgs/x86-64");
bin.listeners.sourcechange();
check("频道改变后镜像选择器会重算地址",
      bin.slots.top.textContent === cernet + "/unstable/binpkgs/x86-64");
bin.root.setAttribute("data-lang", "zh-tw");
bin.listeners.langchange();
check("繁体中文默认选择源站", all(bin.selected(), origin), JSON.stringify(bin.selected()));
bin.root.setAttribute("data-lang", "en");
bin.listeners.langchange();
check("英文默认选择 OSUOSL", all(bin.selected(), osuosl), JSON.stringify(bin.selected()));

// A choice is stored, survives a language change, and is the choice on the next page.
const shared = storage();
const first = load("binpkg-setup.html", "zh-cn", shared);
check("未选择时不写入存储", !("mirror-source" in shared.data), JSON.stringify(shared.data));
first.choose(nju);
first.root.setAttribute("data-lang", "en");
first.listeners.langchange();
check("手动选择在语言切换后保持不变", all(first.selected(), nju), JSON.stringify(first.selected()));
check("手动选择写入 mirror-source", shared.data["mirror-source"] === nju, JSON.stringify(shared.data));

const next = load("distfiles-setup.html", "en", shared);
check("distfiles 配置页沿用上一页选择的镜像，优先于语言默认值",
      all(next.selected(), nju), JSON.stringify(next.selected()));
check("GENTOO_MIRRORS 以所选镜像开头并保留其余回退镜像",
      next.slots.dist.textContent === '"${GENTOO_MIRRORS} ' +
        [nju].concat(uris.filter((u) => u !== nju)).join(" ") + '"', next.slots.dist.textContent);
next.root.setAttribute("data-lang", "zh-tw");
next.listeners.langchange();
check("沿用的选择在语言切换后保持不变", all(next.selected(), nju), JSON.stringify(next.selected()));

// Back to the first page from the back-forward cache after the second page changed the choice.
next.choose(osuosl);
const back = load("binpkg-setup.html", "zh-cn", shared);
shared.data["mirror-source"] = cernet;
back.winListeners.pageshow({ persisted: true });
check("从往返缓存返回时重新读取存储的选择", all(back.selected(), cernet), JSON.stringify(back.selected()));

const unknown = load("binpkg-setup.html", "zh-tw", storage({ "mirror-source": "https://gone.example/x" }));
check("存储的镜像已不在列表中时使用语言默认值", all(unknown.selected(), origin),
      JSON.stringify(unknown.selected()));
const blocked = load("distfiles-setup.html", "en", storage({}, true));
blocked.choose(nju);
check("存储不可用时使用语言默认值，选择仍然生效",
      all(blocked.selected(), nju), JSON.stringify(blocked.selected()));
const blockedFresh = load("binpkg-setup.html", "en", storage({}, true));
check("存储不可用的新页面使用语言默认值", all(blockedFresh.selected(), osuosl),
      JSON.stringify(blockedFresh.selected()));

// The file browser: the same mirror list, the origin by default in every language, and file links
// rewritten to the chosen mirror; the listing itself stays on this host.
const filePath = "/gigos/2026/gig%20os.iso";
const fileLink = () => element({ href: "gig%20os.iso", "data-src-link": "files", "data-src-path": filePath });
for (const lang of ["zh-cn", "zh-tw", "en"]) {
  const link = fileLink();
  const fresh = load("_app.html", lang, storage(), [link]);
  check(`文件浏览器（${lang}）默认使用源站，下载链接留在本站`,
        all(fresh.selected(), origin) && link.getAttribute("href") === filePath,
        JSON.stringify([fresh.selected(), link.getAttribute("href")]));
}
const appUris = load("_app.html", "zh-cn", storage()).groups[0].opts.map((o) => o.getAttribute("data-uri"));
check("文件浏览器的镜像清单与配置页一致", JSON.stringify(appUris) === JSON.stringify(uris),
      JSON.stringify(appUris));
const browse = storage();
const link = fileLink();
const app = load("_app.html", "zh-cn", browse, [link]);
for (const uri of uris.filter((u) => u !== origin)) {
  app.choose(uri);
  check(`选择 ${uri} 后下载链接指向该镜像`, link.getAttribute("href") === uri + filePath,
        link.getAttribute("href"));
}
app.choose(origin);
check("改回源站后下载链接回到本站", link.getAttribute("href") === filePath, link.getAttribute("href"));
app.choose(osuosl);
check("文件浏览器的选择写入 mirror-source", browse.data["mirror-source"] === osuosl,
      JSON.stringify(browse.data));
const again = fileLink();
load("_app.html", "zh-tw", browse, [again]);
check("再次打开文件浏览器时沿用存储的镜像", again.getAttribute("href") === osuosl + filePath,
      again.getAttribute("href"));
const setup = load("binpkg-setup.html", "zh-cn", browse);
check("配置页沿用文件浏览器选择的镜像", all(setup.selected(), osuosl), JSON.stringify(setup.selected()));
setup.choose(nju);
const fromSetup = fileLink();
load("_app.html", "en", browse, [fromSetup]);
check("文件浏览器沿用配置页选择的镜像", fromSetup.getAttribute("href") === nju + filePath,
      fromSetup.getAttribute("href"));
const lateLink = fileLink();
const lateApp = load("_app.html", "zh-cn", storage({ "mirror-source": cernet }), [lateLink]);
lateApp.listeners.sourcechange();
check("列表晚于选择器到达时，sourcechange 仍会改写新链接", lateLink.getAttribute("href") === cernet + filePath,
      lateLink.getAttribute("href"));


// The encoded data-src-path is appended to the mirror as is.
const oddPath = "/distfiles/a&b%20c%25/x%26y.iso";
const oddLink = () => element({ href: "x%26y.iso", "data-src-link": "files", "data-src-path": oddPath });
const fine = oddLink();
const fineApp = load("_app.html", "zh-cn", storage({ "mirror-source": nju }), [fine]);
fineApp.listeners.sourcechange();
check("镜像链接直接拼接编码后的路径，不二次解码", fine.getAttribute("href") === nju + oddPath,
      fine.getAttribute("href"));
// mirror-health.js marks a mirror the status API found down with data-down; its links stay on the origin.
const dead = oddLink();
const deadApp = load("_app.html", "zh-cn", storage({ "mirror-source": nju }), [dead]);
const njuOpt = deadApp.groups[0].opts.find((o) => o.getAttribute("data-uri") === nju);
njuOpt.setAttribute("data-down", "");
deadApp.listeners.sourcechange();
check("状态 API 判定无法连接的镜像：下载链接留在源站", dead.getAttribute("href") === oddPath, dead.getAttribute("href"));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  镜像默认值、语言切换、跨页选择与下载链接：全部通过");
process.exit(failed ? 1 : 0);
