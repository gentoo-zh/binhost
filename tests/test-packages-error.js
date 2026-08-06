#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/packages.html"), "utf8");
const nodes = {};

function list(items) {
  return { length: items.length, forEach(fn) { items.forEach(fn); } };
}

function element(id) {
  return {
    id, innerHTML: "", textContent: "", hidden: false, value: "",
    dataset: {}, style: {}, parentElement: { hidden: false },
    classList: { toggle() {} },
    addEventListener() {},
    setAttribute() {},
    querySelectorAll() { return list([]); },
  };
}

const tables = { pkgs: element("pkgs-table"), deps: element("deps-table") };
tables.pkgs.querySelector = function () { return null; };

global.document = {
  documentElement: { lang: "zh-cn" },
  getElementById(id) { return (nodes[id] = nodes[id] || element(id)); },
  querySelector(selector) {
    if (selector === ".pkgs") return tables.pkgs;
    if (selector === ".deps-table") return tables.deps;
    return null;
  },
  querySelectorAll() { return list([]); },
  addEventListener() {},
};
global.window = { MIRROR_I18N: {}, addEventListener() {} };
global.location = { pathname: "/packages", hash: "" };
global.fetch = () => Promise.reject(new Error("offline"));
global.MutationObserver = class { observe() {} };

(0, eval)(fs.readFileSync(path.join(ROOT, "site/assets/util.js"), "utf8"));
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((match) => match[1]);
(0, eval)(blocks.sort((left, right) => right.length - left.length)[0]);

setImmediate(() => {
  const overlay = document.getElementById("msg").textContent;
  const dependencies = document.getElementById("depsCount").textContent;
  const okay = overlay.includes("offline") && dependencies === overlay &&
    document.getElementById("depRows").innerHTML === "" &&
    document.getElementById("retry").hidden === false;
  console.log(`  ${okay ? "✓" : "✗"} packages.json 失败时两张表显示同一错误状态`);
  process.exit(okay ? 0 : 1);
});
