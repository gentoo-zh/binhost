#!/usr/bin/env node
// The mirror status (site/assets/status-data.js) as the overview's statistics strip and the status
// page show it: two channels' counts, each channel's build, the server figures, and one fetch per URL.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SITE = path.join(ROOT, "site");
const css = fs.readFileSync(path.join(SITE, "assets/site.css"), "utf8");
const moduleSource = fs.readFileSync(path.join(SITE, "assets/status-data.js"), "utf8");

let failed = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log("  ✓ " + name);
    return;
  }
  console.log("  ✗ " + name + (detail ? "\n      " + detail : ""));
  failed++;
}

const now = Math.floor(Date.now() / 1000);
const INDEX = {
  stable: { packages: 255, overlay: 188, deps: 67, generated: now - 7200 },
  unstable: { packages: 432, overlay: 196, deps: 236, generated: now - 3600 },
};

// Loads the module afresh with the given build files and language, and returns its API with the
// URLs it fetched.
function load(builds, locale = "zh-tw") {
  const calls = [];
  global.document = {
    documentElement: { lang: locale, getAttribute: () => locale },
    getElementById: () => null,
    querySelector: () => null,
    addEventListener() {},
  };
  global.window = {};
  global.fetch = (url) => {
    calls.push(url);
    const body =
      url === "/build-status.json" ? builds.stable :
      url === "/build-status-unstable.json" ? builds.unstable :
      url.includes("server-status") ? { uptime: 93784, tx: 5138022, generated: now } :
      url.includes("distfiles-status") ? { files: 1158, generated: now } :
      url.startsWith("/unstable/") ? INDEX.unstable : INDEX.stable;
    return Promise.resolve({ ok: body !== undefined, json: () => Promise.resolve(body) });
  };
  (0, eval)(moduleSource);
  return { api: global.window.MirrorStatus, calls };
}

async function render(builds, locale) {
  const { api, calls } = load(builds, locale);
  const data = await api.load();
  return { api, data, calls, html: api.facts(data), server: api.server(data), sum: api.summary(data) };
}

const DONE = { state: "done", started: 100, finished: now - 5 * 3600, duration: 5633, generated: now };

(async function () {
  const done = await render({ stable: DONE, unstable: { ...DONE, finished: now - 9 * 3600 } });
  check("两个频道的 binpkg 统计都显示",
        done.html.includes("stable binpkg") && done.html.includes("unstable binpkg") &&
        ["188", "67", "196", "236", "1158"].every((n) => done.html.includes(n)), done.html);
  check("完成的构建写明频道、用时与完成时间",
        (done.server.match(/最近建置/g) || []).length === 2 &&
        done.server.includes('<span class="sub">stable</span>') &&
        done.server.includes('<span class="sub">unstable</span>') &&
        done.server.includes("1 小時 33 分") && done.server.includes("完成於 ") &&
        !done.html.includes("最近建置"), done.server);
  check("运行时间和出站流量合并成一行，共用一个时间戳",
        done.server.includes("運作時間") && done.server.includes("出站流量") &&
        done.server.includes("4.9 MiB") && (done.server.match(/更新於 /g) || []).length === 1,
        done.server);
  check("每个地址只请求一次，两个频道的构建状态都读取",
        new Set(done.calls).size === done.calls.length &&
        ["/binpkgs/x86-64/status.json", "/unstable/binpkgs/x86-64/status.json",
         "/build-status.json", "/build-status-unstable.json", "/distfiles-status.json",
         "/server-status.json"].every((u) => done.calls.includes(u)), JSON.stringify(done.calls));
  await done.api.json("/binpkgs/x86-64/status.json");
  check("频道切换脚本经 json() 复用已取得的索引，不再请求",
        done.calls.filter((u) => u === "/binpkgs/x86-64/status.json").length === 1,
        JSON.stringify(done.calls));
  check("概览取最近完成的一次构建并写明频道",
        done.sum.build && done.sum.build.channel === "stable" &&
        done.sum.stable === 188 && done.sum.unstableDeps === 236 && done.sum.dist === 1158 &&
        !("index" in done.sum), JSON.stringify(done.sum));
  const listed = done.api.summary({ ...done.data, packages: { packages: [{ cp: "a/b" }, { cp: "c/d" }, { cp: "e/f" }] } });
  check("overlay 的包数是包列表的行数，没有列表时留空",
        listed.overlay === 3 && done.sum.overlay === null, JSON.stringify([listed.overlay, done.sum.overlay]));
  check("共用的状态请求不含包列表，状态页不下载 packages.json",
        !done.calls.includes("/packages.json"), JSON.stringify(done.calls));
  check("构建时间按最大单位显示为多久以前",
        done.api.age(now - 5 * 3600 - 60) === "5 小時前", done.api.age(now - 5 * 3600 - 60));

  const running = await render({
    stable: DONE,
    unstable: { state: "running", kind: "source", done: 7, total: 9, now: "app-misc/<unsafe>",
                generated: now },
  });
  check("进行中的构建显示频道、进度并转义包名",
        running.html.includes('<span class="sub">unstable</span>') &&
        running.html.includes("7/9") && running.html.includes("正在建置") &&
        running.html.includes("app-misc/&lt;unsafe&gt;"), running.html);
  check("进行中的频道不显示上一次构建，另一个频道照常显示",
        (running.server.match(/最近建置/g) || []).length === 1 &&
        running.server.includes('<span class="sub">stable</span>'), running.server);
  check("概览在有构建进行时显示进行中的频道",
        running.sum.running && running.sum.running.channel === "unstable", JSON.stringify(running.sum));

  // strip() writes the overview's four counts into their tiles, found inside the strip passed as
  // box, and the latest build into its own element, found on the page rather than scoped to box:
  // the header line sits outside the strip and carries no channel or duration.
  {
    const tiles = { overlay: { innerHTML: "—" }, stable: { innerHTML: "—" },
                     unstable: { innerHTML: "—" }, dist: { innerHTML: "—" } };
    const box = { querySelector: (sel) => {
      const m = /^\[data-stat="(\w+)"\] \.stat-value$/.exec(sel);
      return m ? tiles[m[1]] : null;
    } };
    const buildEl = { innerHTML: "—" };
    global.document.querySelector = (sel) => (sel === '[data-stat="build"]' ? buildEl : null);
    const withPkgs = { ...done.data,
                        packages: { packages: [{ cp: "a/b" }, { cp: "c/d" }, { cp: "e/f" }] } };
    done.api.strip(withPkgs, box);
    check("strip 把四项数字写进各自的格子",
          tiles.overlay.innerHTML === 3 && tiles.stable.innerHTML === 188 &&
          tiles.unstable.innerHTML === 196 && tiles.dist.innerHTML === 1158,
          JSON.stringify(tiles));
    check("strip 把最近构建写进标题下方那一行，不带频道和用时",
          buildEl.innerHTML === done.api.age(done.sum.build.finished) &&
          !String(buildEl.innerHTML).includes("stable") &&
          !String(buildEl.innerHTML).includes("用時"), String(buildEl.innerHTML));

    const runningBuildEl = { innerHTML: "—" };
    global.document.querySelector = (sel) => (sel === '[data-stat="build"]' ? runningBuildEl : null);
    running.api.strip(running.data, { querySelector: () => null });
    check("进行中的构建写进标题下方那一行，只有进度与阶段，没有频道",
          String(runningBuildEl.innerHTML).includes("7/9") &&
          String(runningBuildEl.innerHTML).includes("正在建置") &&
          !String(runningBuildEl.innerHTML).includes("unstable"), String(runningBuildEl.innerHTML));
  }

  const merging = await render({
    stable: { state: "running", kind: "binary", done: 33, total: 720, now: "sys-libs/zlib",
              generated: now },
  });
  check("取用现成 binpkg 时报的是这个状态而不是构建中",
        merging.html.includes("33/720") && merging.html.includes("正在安裝 binpkg") &&
        !merging.html.includes("正在建置"), merging.html);
  const fetching = ["zh-cn", "zh-tw", "en"].map((l) => merging.api.WORDS[l].fetching);
  check("三种语言都说安装现成的 binpkg，不说取",
        fetching.every((v) => /安裝|安装|installing/.test(v)) &&
        !fetching.some((v) => /正在取|fetching/.test(v)), fetching.join(" | "));

  const stale = await render({
    stable: { state: "running", kind: "source", done: 1, total: 9, generated: now - 4 * 3600 },
  });
  check("三小时未更新的进行中状态不再显示", !stale.html.includes("1/9") && !stale.sum.running,
        stale.html);

  const failedBuild = await render({ stable: { ...DONE, state: "failed" } });
  check("失败的构建写明未完成与结束时间，概览不把它当作最近构建",
        failedBuild.server.includes("未完成") && failedBuild.server.includes("結束於 ") &&
        !failedBuild.sum.build, failedBuild.server);

  const legacy = await render({ stable: { state: "done", generated: 5733 } });
  check("旧状态数据不会伪造构建用时", !legacy.server.includes("最近建置") && !legacy.sum.build,
        legacy.server);

  const simplified = await render({ stable: DONE }, "zh-cn");
  check("简体中文显示两个频道的明确标签",
        simplified.html.includes("stable binpkg") && simplified.html.includes("unstable binpkg"),
        simplified.html);
  const english = await render({ stable: DONE }, "en");
  check("英文用英文单位", english.server.includes("Latest build") &&
        english.api.age(now - 7200) === "2 h ago", english.server);

  {
    // A request that stalls forever (no response, no error) must not block the others: json()
    // aborts it once it runs past the timeout, and load() still resolves with everything else that
    // arrived, leaving only the stalled slot empty.
    global.document = {
      documentElement: { lang: "zh-tw", getAttribute: () => "zh-tw" },
      getElementById: () => null, querySelector: () => null, addEventListener() {},
    };
    global.window = {};
    global.setTimeout = (fn) => { fn(); return 0; };
    global.clearTimeout = () => {};
    global.fetch = (url, opts) => {
      if (url === "/build-status-unstable.json") {
        return new Promise((resolve, reject) => {
          const abort = () => { const e = new Error("aborted"); e.name = "AbortError"; reject(e); };
          if (opts && opts.signal) { opts.signal.aborted ? abort() : opts.signal.addEventListener("abort", abort); }
        });
      }
      const body =
        url === "/build-status.json" ? DONE :
        url.includes("server-status") ? { uptime: 93784, tx: 5138022, generated: now } :
        url.includes("distfiles-status") ? { files: 1158, generated: now } :
        url.startsWith("/unstable/") ? INDEX.unstable : INDEX.stable;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
    };
    (0, eval)(moduleSource);
    const data = await global.window.MirrorStatus.load();
    check("卡住的请求不拖住其它请求：其余数据照常到达，卡住的那项留空",
          data.builds.stable && data.builds.stable.state === "done" && data.builds.unstable === null &&
          data.dist && data.dist.files === 1158, JSON.stringify(data));
  }

  // The reservation must hold the rows the script draws, each at least one row's rendered
  // height: padding, one line (two on phones, where the value wraps under the label) and the rule.
  const tokens = fs.readFileSync(path.join(SITE, "assets/tokens.css"), "utf8");
  const px = (name) => {
    const m = tokens.match(new RegExp("--" + name + ": ([0-9.]+)(rem|px)?;"));
    return m ? parseFloat(m[1]) * (m[2] === "rem" ? 16 : 1) : NaN;
  };
  const rem = (text) => (text ? parseFloat(text) * 16 : NaN);
  const baseRow = rem((tokens.match(/--fact-row: ([0-9.]+)rem;/) || [])[1]);
  const phone = tokens.match(/@media \(max-width: 34rem\) \{[^@]*/);
  const phoneRow = rem(((phone ? phone[0] : "").match(/--fact-row: ([0-9.]+)rem;/) || [])[1]);
  const line = px("fs-ui") * parseFloat((tokens.match(/--lh-code: ([0-9.]+);/) || [])[1]);
  const chrome = 2 * px("sp-2") + 1;
  const reserved = (sel) => {
    const m = css.match(new RegExp(sel + " \\{[^}]*min-height: calc\\((\\d+) \\* var\\(--fact-row\\)\\)"));
    return m ? Number(m[1]) : 0;
  };
  const rows = (text) => (text.match(/class="(row|job)"/g) || []).length;
  check("预留的行数不少于脚本画出的行数",
        reserved("\\.facts") >= rows(done.html) && reserved("#server-facts") >= rows(done.server),
        `facts ${reserved("\\.facts")}/${rows(done.html)} server ${reserved("#server-facts")}/${rows(done.server)}`);
  check("每行预留的高度容得下一行内容，手机上容得下两行",
        baseRow >= chrome + line && phoneRow >= chrome + 2 * line,
        `base ${baseRow}px phone ${phoneRow}px line ${line}px`);

  // Every page showing status loads the module; the strip holds a tile for each of the four counts,
  // and the latest build sits below the heading as its own line, not a fifth figure in the strip.
  const pages = fs.readdirSync(SITE).filter((f) => f.endsWith(".html"));
  const shows = pages.filter((f) => /id="(server-)?facts"|data-stats/.test(
    fs.readFileSync(path.join(SITE, f), "utf8")));
  check("显示状态的页面都载入 status-data.js", shows.length > 0 && shows.every((f) =>
    /<script src="\/assets\/status-data\.js[^"]*"><\/script>/.test(
      fs.readFileSync(path.join(SITE, f), "utf8"))), shows.join(", "));
  for (const f of shows) {
    const html = fs.readFileSync(path.join(SITE, f), "utf8");
    if (!html.includes("data-stats")) continue;
    const strip = (html.match(/<ul class="stats"[^>]*data-stats[^>]*>[\s\S]*?<\/ul>/) || [""])[0];
    const tiles = [...strip.matchAll(/data-stat="(\w+)"/g)].map((m) => m[1]).sort().join(",");
    check(`${f} 的统计条只有四项数字，不含最近构建`, tiles === "dist,overlay,stable,unstable", tiles);
    check(`${f} 的统计条不含备注行`, strip !== "" && !strip.includes("stat-note"),
          strip.slice(0, 200));
    // The link to the status page sits in the section heading, not in the strip as a fifth figure.
    const rest = html.replace(strip, "");
    check(`${f} 的统计条里只有数字，详细状态的链接在统计条之外`,
          strip !== "" && !/<a\b/.test(strip) && /<a class="section-more" href="\/status"/.test(rest),
          strip.slice(0, 120));
    const head = (html.match(
      /<div class="section-head">[\s\S]*?<\/div>\s*<p class="status-build"[^>]*>[\s\S]*?<\/p>/) ||
      [""])[0];
    check(`${f} 的最近构建移到标题下方，独立成行`,
          head.includes('data-stat="build"') && !strip.includes('data-stat="build"'),
          head || "(未找到 .status-build)");
  }

  console.log(failed ? `\n  ${failed} 项不通过` : "\n  镜像状态：全部通过");
  process.exit(failed ? 1 : 0);
})();
