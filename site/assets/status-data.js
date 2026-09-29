// Mirror status shared by the overview's statistics strip and the status page: one loader for the
// channel indexes, the distfiles count, both channels' build state and the server figures, and one
// set of formatters. It knows the channels itself, so neither page needs channel buttons, and every
// URL is fetched once per page load; channel-switch.js reads the same responses through json().
// The status wording lives here, in all three languages, so the pages that show it share one table.
(function () {
  'use strict';

  var CHANNELS = [
    { name: 'stable', path: '/binpkgs/x86-64', build: '/build-status.json', row: 'stableRow' },
    { name: 'unstable', path: '/unstable/binpkgs/x86-64', build: '/build-status-unstable.json',
      row: 'unstableRow' }
  ];

  var WORDS = {
    'zh-cn': {
      stableRow: 'stable binary package', unstableRow: 'unstable binary package', distRow: 'distfiles',
      buildRow: '最近构建', pkgs: ' 个 gentoo-zh 软件包', deps: ' 个 ::gentoo 依赖', dist: ' 个文件',
      time: '更新于 ', finished: '完成于 ', ended: '结束于 ', failed: '未完成',
      preparing: ' 正在准备构建', building: ' 正在构建', fetching: ' 正在安装 binary package',
      uptime: '运行时间', traffic: '出站流量', ago: '前', took: '用时 ',
      day: ' 天', hour: ' 小时', minute: ' 分钟', second: ' 秒'
    },
    'zh-tw': {
      stableRow: 'stable binary package', unstableRow: 'unstable binary package', distRow: 'distfiles',
      buildRow: '最近建置', pkgs: ' 個 gentoo-zh 套件', deps: ' 個 ::gentoo 依賴', dist: ' 個檔案',
      time: '更新於 ', finished: '完成於 ', ended: '結束於 ', failed: '未完成',
      preparing: ' 正在準備建置', building: ' 正在建置', fetching: ' 正在安裝 binary package',
      uptime: '運作時間', traffic: '出站流量', ago: '前', took: '耗時 ',
      day: ' 天', hour: ' 小時', minute: ' 分鐘', second: ' 秒'
    },
    'en': {
      stableRow: 'stable binary packages', unstableRow: 'unstable binary packages',
      distRow: 'distfiles', buildRow: 'Latest build', pkgs: ' packages from gentoo-zh',
      deps: ' ::gentoo dependencies', dist: ' files', time: 'updated ', finished: 'finished ',
      ended: 'ended ', failed: 'did not finish', preparing: ' preparing build', building: ' building',
      fetching: ' installing binary packages', uptime: 'Uptime', traffic: 'Outbound traffic', ago: ' ago',
      took: 'took ', day: ' d', hour: ' h', minute: ' min', second: ' s'
    }
  };

  // A running job whose file has not been refreshed for this long is treated as gone.
  var STALE = 3 * 3600;

  function lang() {
    var l = (document.documentElement.getAttribute('data-lang') ||
             document.documentElement.lang || 'zh-cn').toLowerCase();
    return WORDS[l] ? l : 'zh-cn';
  }
  function t(key) { return WORDS[lang()][key]; }

  // A request that neither succeeds nor fails within this long is aborted, so one stalled endpoint
  // cannot hold up the others: the abort becomes a rejection, which the catch below turns into the
  // same null a 404 or a network error already produces.
  var FETCH_TIMEOUT = 10000;

  var cache = {};
  function json(url) {
    if (!cache[url]) {
      var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timer = ctrl && setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT);
      cache[url] = fetch(url, ctrl ? { signal: ctrl.signal } : undefined)
        .then(function (r) { clearTimeout(timer); return r.ok ? r.json() : null; })
        .catch(function () { clearTimeout(timer); return null; });
    }
    return cache[url];
  }

  function load() {
    var urls = [];
    CHANNELS.forEach(function (c) { urls.push(c.path + '/status.json', c.build); });
    urls.push('/distfiles-status.json', '/server-status.json');
    // allSettled, not all: json() above never rejects, but settling explicitly means a future
    // rejection still renders whatever else arrived instead of leaving the page loading forever.
    return Promise.allSettled(urls.map(json)).then(function (results) {
      var v = results.map(function (r) { return r.status === 'fulfilled' ? r.value : null; });
      var data = { channels: {}, builds: {}, dist: v[urls.length - 2], server: v[urls.length - 1] };
      CHANNELS.forEach(function (c, i) {
        data.channels[c.name] = v[2 * i];
        data.builds[c.name] = v[2 * i + 1];
      });
      return data;
    });
  }

  function now() { return Date.now() / 1000; }
  function escape(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function stamp(unix) {
    var n = Number(unix);
    if (!n) return '';
    var s = new Date((n + 8 * 3600) * 1000).toISOString().slice(0, 16).replace('T', ' ');
    return '<span class="wide-only">' + s.slice(0, 5) + '</span>' + s.slice(5) +
           '<span class="wide-only"> UTC+8</span>';
  }

  function duration(seconds) {
    var value = Math.max(0, Number(seconds) || 0);
    var days = Math.floor(value / 86400);
    var hours = Math.floor(value % 86400 / 3600);
    var minutes = Math.floor(value % 3600 / 60);
    var rest = Math.floor(value % 60);
    if (days) return days + t('day') + (hours ? ' ' + hours + t('hour') : '');
    if (hours) return hours + t('hour') + (minutes ? ' ' + minutes + t('minute') : '');
    if (minutes) return minutes + t('minute') + (rest ? ' ' + rest + t('second') : '');
    return rest + t('second');
  }

  // Coarse age: the largest unit only, as in "5 hours ago".
  function age(unix) {
    var s = Math.max(0, now() - Number(unix));
    var d = Math.floor(s / 86400), h = Math.floor(s / 3600), m = Math.floor(s / 60);
    var text = d ? d + t('day') : h ? h + t('hour') : m ? m + t('minute') : Math.floor(s) + t('second');
    return text.trim() + t('ago');
  }

  function bytes(value) {
    var n = Number(value) || 0, units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'], i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return (i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)) + ' ' + units[i];
  }

  function own(bin) {
    if (!bin) return null;
    return typeof bin.overlay === 'number' ? bin.overlay
         : typeof bin.packages === 'number' ? bin.packages : null;
  }

  // What each channel's build file says: a finished build (done or failed), a job still reporting
  // progress, or nothing usable (missing, or a running file that has gone stale).
  function build(job) {
    if (!job) return null;
    if (job.state === 'running') {
      return job.generated && now() - job.generated < STALE ? { running: job } : null;
    }
    if ((job.state === 'done' || job.state === 'failed') && Number(job.finished) > 0 &&
        Number.isFinite(job.duration) && job.duration >= 0) {
      return { state: job.state, finished: Number(job.finished), duration: job.duration };
    }
    return null;
  }

  // One labelled value per row: the label, the values (a value may carry its own sub-label), the time.
  function fact(label, parts, generated, timeLabel) {
    var body = parts.map(function (p) {
      return '<span class="part">' + (p[2] ? '<span class="sub">' + p[2] + '</span> ' : '') +
             '<b class="num">' + p[0] + '</b>' + p[1] + '</span>';
    }).join('<span class="sep">·</span>');
    return '<span class="row"><span class="who">' + label + '</span><span class="val">' + body +
           '</span><span class="when">' +
           (generated ? (timeLabel || t('time')) + '<b>' + stamp(generated) + '</b>' : '') +
           '</span></span>';
  }

  function job(channel, j) {
    var what = j.kind === 'prepare' ? 'preparing' : j.kind === 'source' ? 'building' : 'fetching';
    return '<span class="job"><span class="sub">' + channel + '</span> ' +
           (j.total ? '<b class="num">' + Number(j.done) + '/' + Number(j.total) + '</b>' : '') +
           t(what) + (j.now ? ' <code>' + escape(j.now) + '</code>' : '') + '</span>';
  }

  // Package, dependency and file counts, then any build in progress.
  function facts(data) {
    var html = '';
    CHANNELS.forEach(function (c) {
      var bin = data.channels[c.name], parts = [], n = own(bin);
      if (n !== null) parts.push([n, t('pkgs')]);
      if (bin && typeof bin.deps === 'number') parts.push([bin.deps, t('deps')]);
      if (parts.length) html += fact(t(c.row), parts, bin.generated);
    });
    if (data.dist && data.dist.files) {
      html += fact(t('distRow'), [[data.dist.files, t('dist')]], data.dist.generated);
    }
    CHANNELS.forEach(function (c) {
      var b = build(data.builds[c.name]);
      if (b && b.running) html += job(c.name, b.running);
    });
    return html;
  }

  // Server uptime and egress on one row, then each channel's last finished build.
  function server(data) {
    var s = data.server, html = '', vitals = [];
    if (s && Number(s.uptime) > 0) vitals.push([duration(s.uptime), '', t('uptime')]);
    if (s && Number(s.tx) > 0) vitals.push([bytes(s.tx), '', t('traffic')]);
    if (vitals.length) {
      html += fact(vitals[0][2], [[vitals[0][0], vitals[0][1]]].concat(vitals.slice(1)), s.generated);
    }
    CHANNELS.forEach(function (c) {
      var b = build(data.builds[c.name]);
      if (!b || b.running) return;
      html += b.state === 'done'
        ? fact(t('buildRow'), [[duration(b.duration), '', c.name]], b.finished, t('finished'))
        : fact(t('buildRow'), [[t('failed'), '', c.name]], b.finished, t('ended'));
    });
    return html;
  }

  // The overview's figures. Each is null when its source is missing, and the tile then keeps its dash.
  // The overlay's package count is the row count of the package list, from the same packages.json.
  function summary(data) {
    var list = data.packages && data.packages.packages;
    var out = { dist: data.dist && data.dist.files ? data.dist.files : null,
                overlay: Array.isArray(list) ? list.length : null, build: null, running: null };
    CHANNELS.forEach(function (c) {
      var bin = data.channels[c.name];
      out[c.name] = own(bin);
      out[c.name + 'Deps'] = bin && typeof bin.deps === 'number' ? bin.deps : null;
      var b = build(data.builds[c.name]);
      if (b && b.running && !out.running) out.running = { channel: c.name, job: b.running };
      if (b && b.state === 'done' && (!out.build || b.finished > out.build.finished)) {
        out.build = { channel: c.name, finished: b.finished, duration: b.duration };
      }
    });
    return out;
  }

  // The four figures, each a tile inside box; the latest build sits outside the strip, under the
  // heading, so it is looked up on the page rather than scoped to box. Its line stays quiet: no
  // channel, no duration, the detail the status page already gives.
  function strip(data, box) {
    var s = summary(data);
    function put(name, value) {
      var tile = box.querySelector('[data-stat="' + name + '"] .stat-value');
      if (tile && value !== null && value !== undefined) tile.innerHTML = value;
    }
    put('overlay', s.overlay);
    put('stable', s.stable);
    put('unstable', s.unstable);
    put('dist', s.dist);
    var build = document.querySelector('[data-stat="build"]');
    if (!build) return;
    if (s.running) {
      var phase = t(s.running.job.kind === 'prepare' ? 'preparing'
        : s.running.job.kind === 'source' ? 'building' : 'fetching').replace(/^\s+/, '');
      build.innerHTML = (s.running.job.total
        ? Number(s.running.job.done) + '/' + Number(s.running.job.total) + ' ' : '') + phase;
    } else if (s.build) {
      build.innerHTML = age(s.build.finished);
    }
  }

  function mount() {
    var el = document.getElementById('facts');
    var srv = document.getElementById('server-facts');
    var box = document.querySelector('[data-stats]');
    if (!el && !srv && !box) return;
    var data = null;
    function render() {
      if (!data) return;
      if (el) el.innerHTML = facts(data);
      if (srv) srv.innerHTML = server(data);
      if (box) strip(data, box);
      // The skeletons in the markup held each region's final size; the regions are no longer busy.
      [el, srv, box && box.closest ? box.closest('[aria-busy]') : null].forEach(function (n) {
        if (n) n.setAttribute('aria-busy', 'false');
      });
    }
    document.addEventListener('langchange', render);
    // Only the overview counts the overlay's packages; the status page does not fetch the list.
    Promise.all([load(), box ? json('/packages.json') : null]).then(function (v) {
      data = v[0];
      data.packages = v[1];
      render();
    });
  }

  window.MirrorStatus = {
    CHANNELS: CHANNELS, WORDS: WORDS, json: json, load: load, facts: facts, server: server,
    summary: summary, strip: strip, duration: duration, age: age
  };
  mount();
})();
