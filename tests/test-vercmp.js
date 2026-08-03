#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site", "packages.html"), "utf8");

const src = html.match(/const SUFFIX_RANK[\s\S]*?\n}\n(?=\nfunction parsePackages)/);
if (!src) {
  console.error("!!! packages.html 里找不到版本比较那一段");
  process.exit(1);
}
const cmpVer = new Function(src[0] + "\nreturn cmpVer;")();

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "vercmp-cases.json"), "utf8"));

let bad = 0;
for (const [a, b, want] of cases.pairs) {
  const got = Math.sign(cmpVer(a, b));
  if (got !== want) {
    if (bad < 15) console.log(`  ✗ ${a} vs ${b}: 得到 ${got}，portage 说 ${want}`);
    bad++;
  }
  const back = Math.sign(cmpVer(b, a));
  if (back !== -want) {
    if (bad < 15) console.log(`  ✗ ${b} vs ${a}: 反向不对称，得到 ${back}`);
    bad++;
  }
}

const sorted = cases.versions.slice().sort(cmpVer);
for (let i = 1; i < sorted.length; i++) {
  if (cmpVer(sorted[i - 1], sorted[i]) > 0) {
    console.log(`  ✗ 排序后仍逆序：${sorted[i - 1]} 在 ${sorted[i]} 之前`);
    bad++;
  }
}

if (bad) {
  console.log(`\n>>> ${cases.pairs.length} 组里 ${bad} 处与 portage 不一致`);
  process.exit(1);
}
console.log(`  ${cases.versions.length} 个版本，${cases.pairs.length} 组比较与 portage 一致`);
console.log("\n版本比较：全部通过");
