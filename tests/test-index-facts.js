#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "site/assets/site.css"), "utf8");
const script = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((match) => match[1])
  .find((body) => body.includes("Promise.allSettled"));

let failed = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log("  ✓ " + name);
    return;
  }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

async function render(build, channel, locale = "zh-tw") {
  const facts = { innerHTML: "" };
  const serverFacts = { innerHTML: "" };
  const listeners = {};
  const calls = [];
  global.document = {
    documentElement: { lang: locale },
    getElementById(id) {
      if (id === "facts") return facts;
      if (id === "server-facts") return serverFacts;
      return null;
    },
    querySelectorAll(selector) {
      if (selector !== "[data-channel]") return [];
      return [
        {
          getAttribute(name) {
            return {
              "data-channel": "stable", "data-path": "/binpkgs/x86-64",
              "data-status": "/build-status.json", "data-fact-label": "factStableBinRow",
            }[name] || null;
          },
        },
        {
          getAttribute(name) {
            return {
              "data-channel": "unstable", "data-path": "/unstable/binpkgs/x86-64",
              "data-status": "/build-status-unstable.json",
              "data-fact-label": "factUnstableBinRow",
            }[name] || null;
          },
        },
      ];
    },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  global.window = {
    MIRROR_I18N: {
      "zh-tw": {
        factStableBinRow: "stable 二進位套件",
        factUnstableBinRow: "unstable 二進位套件",
        factDistRow: "distfiles", factBuildRow: "最近建置",
        factPkgs: " 個 gentoo-zh", factDeps: " 個 ::gentoo 依賴",
        factDist: " 個檔案", factTime: "更新於 ", factFinished: "完成於 ",
        hour: " 小時", minute: " 分", second: " 秒",
        factPreparing: " 建置準備中", factBuilding: " 正在建置",
        factFetching: " 正在取二進位套件",
      },
    },
  };
  global.esc = (value) => String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const now = Math.floor(Date.now() / 1000);
  global.fetch = (url) => {
    calls.push(url);
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(
        url.includes("build-status") ? build :
        url.includes("distfiles-status") ? { files: 1158, generated: now } :
        url.includes("unstable") ? { packages: 432, overlay: 196, deps: 236, generated: now } :
        { packages: 255, overlay: 188, deps: 67, generated: now }
      ),
    });
  };
  (0, eval)(script);
  await new Promise((resolve) => setImmediate(resolve));
  if (channel) {
    listeners.channelchange({ detail: Object.assign({ channel: "unstable" }, channel) });
    await new Promise((resolve) => setImmediate(resolve));
  }
  return { html: facts.innerHTML, server: serverFacts.innerHTML, calls: calls };
}

(async function () {
  check("首页包含状态渲染脚本", Boolean(script));
  if (!script) process.exit(1);
  check("两个事实区各为三行预留高度",
        css.includes("min-height: calc(3 * 1.75 * 0.95rem + 0.7rem)") &&
        css.includes("min-height: calc(6 * 1.75 * 0.95rem + 0.5rem)"));

  const done = await render({
    state: "done", started: 100, finished: 5733, duration: 5633, generated: 5733,
  });
  check("完成的构建显示在状态分组里",
        done.server.includes("最近建置") && done.server.includes("1 小時 33 分") &&
        done.server.includes("完成於 ") && !done.html.includes("最近建置"),
        done.server + " | " + done.html);
  check("默认读取 stable 的索引和构建状态",
        done.calls.includes("/binpkgs/x86-64/status.json") &&
        done.calls.includes("/unstable/binpkgs/x86-64/status.json") &&
        done.calls.includes("/build-status.json"), JSON.stringify(done.calls));
  check("默认同时显示两个频道的二进制包统计",
        done.html.includes("stable 二進位套件") &&
        done.html.includes("unstable 二進位套件") &&
        done.html.includes("188") && done.html.includes("67") &&
        done.html.includes("196") && done.html.includes("236"), done.html);

  const running = await render({
    state: "running", kind: "source", done: 7, total: 9,
    now: "app-misc/<unsafe>", generated: Math.floor(Date.now() / 1000),
  }, {
    path: "/unstable/binpkgs/x86-64",
    status: "/build-status-unstable.json",
  });
  check("进行中的构建仍显示进度且转义包名",
        running.html.includes("7/9") && running.html.includes("正在建置") &&
        running.html.includes("app-misc/&lt;unsafe&gt;") &&
        !running.html.includes("最近建置"), running.html);
  check("切换频道后读取 unstable 的索引和构建状态",
        running.calls.includes("/unstable/binpkgs/x86-64/status.json") &&
        running.calls.includes("/build-status-unstable.json"),
        JSON.stringify(running.calls));
  check("切换频道后仍保留两个频道的统计",
        running.html.includes("stable 二進位套件") &&
        running.html.includes("unstable 二進位套件") &&
        running.html.includes("188") && running.html.includes("196"), running.html);

  const legacy = await render({ state: "done", generated: 5733 });
  check("旧状态数据不会伪造构建用时",
        !legacy.html.includes("最近建置"), legacy.html);

  const simplified = await render({ state: "done", generated: 5733 }, null, "zh-cn");
  check("简体中文显示两个频道的明确标签",
        simplified.html.includes("stable 二进制包") &&
        simplified.html.includes("unstable 二进制包"), simplified.html);

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  首页构建状态：全部通过");
  process.exit(failed ? 1 : 0);
})();
