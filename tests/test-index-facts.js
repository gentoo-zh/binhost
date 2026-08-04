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

async function render(build) {
  const facts = { innerHTML: "" };
  const listeners = {};
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
  global.fetch = (url) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(
      url.includes("build-status") ? build :
      url.includes("distfiles-status") ? { files: 1158, generated: now } :
      { packages: 466, overlay: 213, deps: 253, generated: now }
    ),
  });
  (0, eval)(script);
  await new Promise((resolve) => setImmediate(resolve));
  return facts.innerHTML;
}

(async function () {
  check("首页包含状态渲染脚本", Boolean(script));
  if (!script) process.exit(1);

  const done = await render({
    state: "done", started: 100, finished: 5733, duration: 5633, generated: 5733,
  });
  check("完成的建置显示实际结束时间与用时",
        done.includes("最近建置") && done.includes("1 小時 33 分") && done.includes("完成於 "),
        done);

  const running = await render({
    state: "running", kind: "source", done: 7, total: 9,
    now: "app-misc/<unsafe>", generated: Math.floor(Date.now() / 1000),
  });
  check("进行中的建置仍显示进度且转义包名",
        running.includes("7/9") && running.includes("正在建置") &&
        running.includes("app-misc/&lt;unsafe&gt;") && !running.includes("最近建置"),
        running);

  const legacy = await render({ state: "done", generated: 5733 });
  check("旧状态数据不会伪造建置用时", !legacy.includes("最近建置"), legacy);

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  首页建置状态：全部通过");
  process.exit(failed ? 1 : 0);
})();
