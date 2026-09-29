// Mirror health from the public status API, fetched once per page load. The API checks each mirror's binpkg
// trees (stable and unstable) from outside the origin; entries match a picker option by the host of its
// data-uri, since the site and the API name some mirrors differently (hernet here, ha there). A mirror that
// is down, or whose larger tree lag exceeds LAG seconds, gets data-behind and a tooltip on its option, and
// a down one also data-down, which keeps the file browser's links on the origin. Cells marked
// data-mirror-host (the mirrors page) show each mirror's state, and #mirror-facts (the status page) gets one
// row per mirror with each tree's state. A failed or slow request changes nothing, and neither does an answer
// whose mirror check is older than STALE seconds, since its marks may no longer hold; the status page then
// swaps its rows for #mirror-failed, which points to the status site.
(function () {
  'use strict';
  var API = 'https://status.gentoozh.org/api/status';
  var LAG = 6 * 3600;
  var WAIT = 8000;
  var STALE = 2 * 3600;
  var TEXT = {
    'zh-cn': { behind: '落后约 {h} 小时', down: '上次检查时无法连接', ok: '已同步', gone: '无法连接',
               checked: '检查于 ' },
    'zh-tw': { behind: '落後約 {h} 小時', down: '上次檢查時無法連線', ok: '已同步', gone: '無法連線',
               checked: '檢查於 ' },
    en: { behind: 'About {h} hours behind', down: 'Unreachable at the last check', ok: 'In sync', gone: 'Unreachable',
          checked: 'Checked ' },
  };
  // The status page names each mirror by the mirrors page's i18n keys; an unlisted host shows as itself.
  var NAMES = {
    'ftp2.osuosl.org': 'mOsuosl', 'mirrors.cernet.edu.cn': 'mCernet', 'mirror.nju.edu.cn': 'mNju',
    'mirror.nyist.edu.cn': 'mNyist', 'mirrors.ha.edu.cn': 'mHernet',
  };

  function lang() {
    var l = String(document.documentElement.lang || '').toLowerCase();
    if (l.indexOf('zh-tw') === 0 || l.indexOf('zh-hant') === 0) return 'zh-tw';
    return l.indexOf('zh') === 0 ? 'zh-cn' : 'en';
  }

  function hostOf(uri) {
    var m = /^[a-z][\w+.-]*:\/\/([^\/?#]+)/i.exec(uri || '');
    return m ? m[1].toLowerCase() : '';
  }

  // One API entry as { down, lag, up, trees }: down when the mirror or any tree is down, lag the larger tree
  // lag, up the mirror's own flag, and trees each tree as { key, up, lag } with lag null when unknown.
  function state(m) {
    var down = m.up === false, lag = 0, trees = [];
    (m.trees || []).forEach(function (tr) {
      if (!tr) return;
      if (tr.up === false) down = true;
      if (typeof tr.lagSec === 'number' && tr.lagSec > lag) lag = tr.lagSec;
      trees.push({ key: String(tr.key || ''), up: tr.up !== false,
                   lag: typeof tr.lagSec === 'number' ? tr.lagSec : null });
    });
    return { down: down, lag: lag, up: m.up !== false, trees: trees };
  }

  // The answer as { at, hosts, list }: at when the check ran, hosts each mirror's state by lowercase host,
  // list the same states in the API's order, each with its host and whether it is the origin.
  function parse(j) {
    var list = j && j.mirrors && j.mirrors.list, hosts = {}, order = [];
    if (!Array.isArray(list)) return null;
    var at = j.mirrors.updated;
    if (typeof at !== 'number' || Date.now() / 1000 - at > STALE) return null;
    list.forEach(function (m) {
      if (!m || !m.host) return;
      var s = state(m);
      s.host = String(m.host).toLowerCase();
      s.origin = m.origin === true;
      hosts[s.host] = s;
      order.push(s);
    });
    return { at: at, hosts: hosts, list: order };
  }

  function words(s) {
    var t = TEXT[lang()];
    if (s.down) return { note: t.down, cell: t.gone };
    if (s.lag > LAG) {
      var h = t.behind.replace('{h}', Math.round(s.lag / 3600));
      return { note: h, cell: h };
    }
    return { note: '', cell: t.ok };
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function tree(m, tr) {
    var t = TEXT[lang()];
    if (!m.up || !tr.up) return t.gone;
    return tr.lag !== null && tr.lag > LAG ? t.behind.replace('{h}', Math.round(tr.lag / 3600)) : t.ok;
  }

  // The status page's rows, in the markup of status-data.js's fact(): the mirror, each tree's state, and
  // when the check ran, in that script's relative wording when it is on the page.
  function rows(h) {
    var t = TEXT[lang()], age = window.MirrorStatus && window.MirrorStatus.age;
    return h.list.filter(function (m) { return !m.origin; }).map(function (m) {
      var key = NAMES[m.host];
      var name = key && typeof window.MIRROR_T === 'function' ? window.MIRROR_T(key) : '';
      var body = m.trees.map(function (tr) {
        return '<span class="part"><span class="sub">' + escape(tr.key) + '</span> <b class="num">' +
               tree(m, tr) + '</b></span>';
      }).join('<span class="sep">·</span>');
      return '<span class="row"><span class="who">' + escape(name || m.host) + '</span><span class="val">' +
             body + '</span><span class="when">' + (age ? t.checked + '<b>' + age(h.at) + '</b>' : '') +
             '</span></span>';
    }).join('');
  }

  // Once the request has settled: the rows and the note under them, or only the fallback line.
  function show() {
    var box = document.getElementById('mirror-facts');
    if (!box) return;
    var more = document.getElementById('mirror-more'), failed = document.getElementById('mirror-failed');
    box.innerHTML = health ? rows(health) : '';
    box.hidden = !health;
    box.setAttribute('aria-busy', 'false');
    if (more) more.hidden = !health;
    if (failed) failed.hidden = !!health;
  }

  var health = null, settled = false;
  function apply() {
    if (settled) show();
    if (!health) return;
    document.querySelectorAll('.src-opt[data-uri]').forEach(function (o) {
      var s = health.hosts[hostOf(o.getAttribute('data-uri'))];
      var w = s ? words(s) : { note: '' };
      if (w.note) { o.setAttribute('data-behind', ''); o.title = w.note; }
      else { o.removeAttribute('data-behind'); o.removeAttribute('title'); }
      if (s && s.down) o.setAttribute('data-down', ''); else o.removeAttribute('data-down');
    });
    document.querySelectorAll('[data-mirror-host]').forEach(function (c) {
      var s = health.hosts[c.getAttribute('data-mirror-host').toLowerCase()];
      c.textContent = s ? words(s).cell : '—';
      if (s && (s.down || s.lag > LAG)) c.setAttribute('data-behind', ''); else c.removeAttribute('data-behind');
    });
  }

  // The first outcome wins: an answer, a failure, or the timeout.
  function finish(h) {
    if (settled) return;
    settled = true;
    health = h;
    apply();
    // source-switch.js rewrites the file links, now that a down mirror's links stay on the origin.
    if (h) document.dispatchEvent(new CustomEvent('sourcechange'));
  }

  function load() {
    if (typeof fetch !== 'function') { finish(null); return; }
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); finish(null); }, WAIT);
    fetch(API, ctl ? { signal: ctl.signal } : {})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { clearTimeout(timer); finish(parse(j)); })
      .catch(function () { clearTimeout(timer); finish(null); });
  }

  document.addEventListener('langchange', apply);
  window.MirrorHealth = { parse: parse, state: state, hostOf: hostOf, apply: apply, rows: rows, LAG: LAG,
                          STALE: STALE };
  load();
})();
