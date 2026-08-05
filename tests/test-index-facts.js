#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "site/index.html"), "utf8");
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

async function render(build, channel) {
  const facts = { innerHTML: "" };
  const listeners = {};
  const calls = [];
  global.document = {
    documentElement: { lang: "zh-tw" },
    getElementById(id) { return id === "facts" ? facts : null; },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  global.window = {
    MIRROR_I18N: {
      "zh-tw": {
        factBinRow: "二進位套件", factDistRow: "distfiles", factBuildRow: "最近建置",
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
        { packages: 466, overlay: 213, deps: 253, generated: now }
      ),
    });
  };
  (0, eval)(script);
  await new Promise((resolve) => setImmediate(resolve));
  if (channel) {
    listeners.channelchange({ detail: channel });
    await new Promise((resolve) => setImmediate(resolve));
  }
  return { html: facts.innerHTML, calls: calls };
}

(async function () {
  check("首页包含状态渲染脚本", Boolean(script));
  if (!script) process.exit(1);

  const done = await render({
    state: "done", started: 100, finished: 5733, duration: 5633, generated: 5733,
  });
  check("完成的构建显示实际结束时间与用时",
        done.html.includes("最近建置") && done.html.includes("1 小時 33 分") &&
        done.html.includes("完成於 "), done.html);
  check("默认读取 stable 的索引和构建状态",
        done.calls.includes("/binpkgs/x86-64/status.json") &&
        done.calls.includes("/build-status.json"), JSON.stringify(done.calls));

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

  const legacy = await render({ state: "done", generated: 5733 });
  check("旧状态数据不会伪造构建用时",
        !legacy.html.includes("最近建置"), legacy.html);

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  首页构建状态：全部通过");
  process.exit(failed ? 1 : 0);
})();
