#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/index.html"), "utf8");

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

function element(attributes, className, hidden) {
  const attrs = Object.assign({}, attributes);
  const classes = new Set((className || "").split(/\s+/).filter(Boolean));
  const listeners = {};
  return {
    hidden: Boolean(hidden),
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

const groupMatch = /<div class="src-pick channel-pick"([^>]*)>([\s\S]*?)<\/div>/.exec(html);
const options = groupMatch ? [...groupMatch[2].matchAll(/<button\b([^>]*)>[\s\S]*?<\/button>/g)]
  .map(function (match) {
    const attrs = match[1];
    return element({
      "data-channel": attr(attrs, "data-channel"),
      "data-path": attr(attrs, "data-path"),
      "data-status": attr(attrs, "data-status"),
    }, attr(attrs, "class"));
  }) : [];
const group = element({});
group.querySelectorAll = function (selector) {
  return selector === "[data-channel]" ? options : [];
};

const suffixes = [...html.matchAll(/<[^>]+data-channel-suffix[^>]*>/g)].map(function (match) {
  return element({ "data-src-suffix": attr(match[0], "data-src-suffix") });
});
const panels = [...html.matchAll(/<[^>]+data-channel-panel="([^"]+)"[^>]*>/g)].map(function (match) {
  return element({ "data-channel-panel": match[1] }, "", /\shidden(?:\s|>)/.test(match[0]));
});
const events = [];

global.CustomEvent = class {
  constructor(type, options) {
    this.type = type;
    this.detail = options && options.detail;
  }
};
global.document = {
  querySelectorAll(selector) {
    if (selector === "[data-channel-switch]") return groupMatch ? [group] : [];
    if (selector === "[data-channel-suffix]") return suffixes;
    if (selector === "[data-channel-panel]") return panels;
    return [];
  },
  dispatchEvent(event) { events.push(event); },
};

(0, eval)(fs.readFileSync(
  path.join(ROOT, "site/assets/channel-switch.js"), "utf8"));

const stable = options.find(function (option) {
  return option.getAttribute("data-channel") === "stable";
});
const unstable = options.find(function (option) {
  return option.getAttribute("data-channel") === "unstable";
});

check("首页包含 stable 与 unstable 两个频道", options.length === 2 && stable && unstable,
      String(options.length));
check("stable 默认使用原有路径和默认状态文件",
      stable && stable.getAttribute("aria-pressed") === "true" &&
      suffixes.every(function (target) {
        return target.getAttribute("data-src-suffix") === "/binpkgs/x86-64";
      }) && events.some(function (event) {
        return event.type === "channelchange" && event.detail.channel === "stable" &&
          event.detail.status === "/build-status.json";
      }));

unstable.click();
check("切换 unstable 会同步更新全部 sync-uri",
      suffixes.length > 0 && suffixes.every(function (target) {
        return target.getAttribute("data-src-suffix") === "/unstable/binpkgs/x86-64";
      }), JSON.stringify(suffixes.map(function (target) {
        return target.getAttribute("data-src-suffix");
      })));
check("切换 unstable 会更新按钮和配置面板",
      unstable.getAttribute("aria-pressed") === "true" &&
      stable.getAttribute("aria-pressed") === "false" &&
      panels.every(function (panel) {
        return panel.hidden === (panel.getAttribute("data-channel-panel") !== "unstable");
      }));
check("切换 unstable 会请求独立状态文件",
      events.some(function (event) {
        return event.type === "channelchange" && event.detail.channel === "unstable" &&
          event.detail.path === "/unstable/binpkgs/x86-64" &&
          event.detail.status === "/build-status-unstable.json";
      }));
check("频道切换会要求镜像选择器重算完整地址",
      events.filter(function (event) { return event.type === "sourcechange"; }).length === 2);
check("两个频道分别提供所需的关键字设置",
      html.includes("*&#47;*::gentoo-zh") &&
      html.includes('ACCEPT_KEYWORDS</span>=<span class="val">"~amd64"'));

console.log(failed ? `\n  ${failed} 项不通过` : "\n  频道切换：全部通过");
process.exit(failed ? 1 : 0);
