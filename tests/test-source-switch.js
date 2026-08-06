#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/index.html"), "utf8");
const faq = fs.readFileSync(path.join(ROOT, "site/faq.html"), "utf8");

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
    setAttribute(name, value) { attrs[name] = String(value); },
    addEventListener(name, listener) { listeners[name] = listener; },
    click() { listeners.click(); },
  };
}

const groups = [...html.matchAll(
  /<div class="src-pick"([^>]*)data-src-switch="([^"]+)"([^>]*)>([\s\S]*?)<\/div>/g
)].map(function (match) {
  const groupAttrs = match[1] + match[3];
  const opts = [...match[4].matchAll(/<button\b([^>]*)>[\s\S]*?<\/button>/g)]
    .filter(function (button) { return /\bsrc-opt\b/.test(attr(button[1], "class") || ""); })
    .map(function (button) {
      const attrs = button[1];
      return element({
        "data-uri": attr(attrs, "data-uri"),
        "data-src-default": attr(attrs, "data-src-default") || "",
      }, attr(attrs, "class"));
    });
  const group = element({
    "data-src-switch": match[2],
    "data-src-group": attr(groupAttrs, "data-src-group") || "",
    "data-src-list": attr(groupAttrs, "data-src-list"),
  });
  group.opts = opts;
  group.querySelectorAll = function (selector) {
    return selector === ".src-opt" ? opts : [];
  };
  return group;
});

const root = element({ "data-lang": "zh-cn" });
const listeners = {};
const topValue = element({ "data-src-suffix": "/binpkgs/x86-64" });
const topCopy = element({ "data-src-suffix": "/binpkgs/x86-64" });
global.document = {
  documentElement: root,
  querySelectorAll(selector) {
    if (selector === "[data-src-switch]") return groups;
    if (selector === '[data-src-slot="top"]') return [topValue];
    if (selector === '.copy-chip[data-src-copy="top"]') return [topCopy];
    return [];
  },
  addEventListener(name, listener) { listeners[name] = listener; },
};

(0, eval)(fs.readFileSync(
  path.join(ROOT, "site/assets/source-switch.js"), "utf8"));

function selected() {
  return groups.map(function (group) {
    const option = group.opts.find(function (item) {
      return item.classList.contains("on");
    });
    return option && option.getAttribute("data-uri");
  });
}

const cernet = "https://mirrors.cernet.edu.cn/gentoo-zh";
const origin = "https://distfiles.gentoozh.org";
const nju = "https://mirror.nju.edu.cn/gentoo-zh";

check("首页包含三组镜像选择器", groups.length === 3, String(groups.length));
const mirrorUris = [...new Set(groups[0].opts.map(function (option) {
  return option.getAttribute("data-uri");
}))];
check("FAQ 列出设置页的全部镜像",
      mirrorUris.length === 5 && mirrorUris.every(function (uri) {
        return faq.includes('href="' + uri + '"') || uri === origin;
      }), JSON.stringify(mirrorUris));
check("简体中文默认选择教育网联合镜像站",
      selected().every(function (uri) { return uri === cernet; }),
      JSON.stringify(selected()));
check("镜像选择器会写出完整 binpkg 地址",
      topValue.textContent === cernet + "/binpkgs/x86-64" &&
      topCopy.getAttribute("data-copy") === cernet + "/binpkgs/x86-64");

topValue.setAttribute("data-src-suffix", "/unstable/binpkgs/x86-64");
topCopy.setAttribute("data-src-suffix", "/unstable/binpkgs/x86-64");
listeners.sourcechange();
check("频道改变后镜像选择器会重算地址",
      topValue.textContent === cernet + "/unstable/binpkgs/x86-64" &&
      topCopy.getAttribute("data-copy") === cernet + "/unstable/binpkgs/x86-64");

root.setAttribute("data-lang", "zh-tw");
listeners.langchange();
check("繁体中文默认选择源站",
      selected().every(function (uri) { return uri === origin; }),
      JSON.stringify(selected()));

root.setAttribute("data-lang", "en");
listeners.langchange();
check("英文默认选择源站",
      selected().every(function (uri) { return uri === origin; }),
      JSON.stringify(selected()));

groups[0].opts.find(function (option) {
  return option.getAttribute("data-uri") === nju;
}).click();
root.setAttribute("data-lang", "zh-cn");
listeners.langchange();
check("手动选择在语言切换后保持不变",
      selected().every(function (uri) { return uri === nju; }),
      JSON.stringify(selected()));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  镜像默认值与语言切换：全部通过");
process.exit(failed ? 1 : 0);
