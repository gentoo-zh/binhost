// Mirror health from the public status API, fetched once per page load. The API checks each mirror's binpkg
// trees (stable and unstable) from outside the origin; entries match a picker option by the host of its
// data-uri, since the site and the API name some mirrors differently (hernet here, ha there). The origin
// publishes each tree about once a day, so a lagging tree is judged by how long the first index it lacks has
// been out: the age of the origin's newest index plus each day of lag past the first. Up to GRACE seconds
// that is only pending, which marks nothing; a mirror with a tree past it, or down, gets data-behind and a
// tooltip on its option, and a down one also data-down, which keeps the file browser's links on the origin.
// Cells marked data-mirror-host (the mirrors page) show each mirror's worst state, and #mirror-facts (the
// status page) gets one row per mirror with each tree's state. A failed or slow request changes nothing, and
// neither does an answer whose mirror check is older than STALE seconds, since its marks may no longer hold;
// the status page then swaps its rows for #mirror-failed, which points to the status site. A mirror in RELAY
// answers with a redirect to another mirror and holds no files, so the lag the API measures through it is
// that mirror's: only whether it is reachable counts, and the status page gives it no row.
(function () {
  'use strict';
  var API = 'https://status.gentoozh.org/api/status';
  var GRACE = 30 * 3600;
  var DAY = 86400;
  var WAIT = 8000;
  var STALE = 2 * 3600;
  var TEXT = {
    'zh-cn': { behind: '落后约 {h} 小时', down: '上次检查时无法连接', ok: '已同步', gone: '无法连接',
               pending: '尚未同步最新版', relay: '重定向至其他镜像站',
               checked: '检查于 ' },
    'zh-tw': { behind: '落後約 {h} 小時', down: '上次檢查時無法連線', ok: '已同步', gone: '無法連線',
               pending: '尚未同步最新版', relay: '重新導向至其他鏡像站',
               checked: '檢查於 ' },
    en: { behind: 'About {h} hours behind', down: 'Unreachable at the last check', ok: 'In sync', gone: 'Unreachable',
          pending: 'Latest not synced yet', relay: 'Redirects to other mirrors',
          checked: 'Checked ' },
  };
  var RELAY = { 'mirrors.cernet.edu.cn': true };
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

  // How long the first index a tree lacks has been out, or null when it is in sync; age is how long ago the
  // origin published its newest index of that tree, and without it the lag stands in.
  function staleness(lag, age) {
    if (typeof lag !== 'number' || !(lag > 0)) return null;
    return typeof age === 'number' ? age + Math.max(0, lag - DAY) : lag;
  }

  var RANK = { ok: 0, pending: 1, behind: 2, down: 3 };
  function level(down, stale) {
    if (down) return 'down';
    if (stale === null) return 'ok';
    return stale > GRACE ? 'behind' : 'pending';
  }

  // One API entry as { down, level, stale, up, relay, trees }, given ages, the age of the origin's newest index
  // by tree: level the worst tree's (down, behind, pending or ok), down when that is down, stale the largest
  // staleness of a tree that is behind, up the mirror's own flag, relay whether it is in RELAY, and trees each
  // tree as { key, up, stale, level } with stale null when in sync or when the mirror is a relay.
  function state(m, ages) {
    var up = m.up !== false, worst = up ? 'ok' : 'down', stale = 0, trees = [];
    var relay = RELAY[String(m.host || '').toLowerCase()] === true;
    (m.trees || []).forEach(function (tr) {
      if (!tr) return;
      var key = String(tr.key || ''), s = relay ? null : staleness(tr.lagSec, ages && ages[key]);
      var t = { key: key, up: tr.up !== false, stale: s, level: level(!up || tr.up === false, s) };
      if (RANK[t.level] > RANK[worst]) worst = t.level;
      if (t.level === 'behind' && s > stale) stale = s;
      trees.push(t);
    });
    return { down: worst === 'down', level: worst, stale: stale, up: up, relay: relay, trees: trees };
  }

  // The answer as { at, hosts, list }: at when the check ran, hosts each mirror's state by lowercase host,
  // list the same states in the API's order, each with its host and whether it is the origin.
  function parse(j) {
    var list = j && j.mirrors && j.mirrors.list, hosts = {}, order = [];
    if (!Array.isArray(list)) return null;
    var at = j.mirrors.updated, ages = {}, pub = j.mirrors.published;
    if (typeof at !== 'number' || Date.now() / 1000 - at > STALE) return null;
    (Array.isArray(pub) ? pub : []).forEach(function (p) {
      if (p && typeof p.ageSec === 'number') ages[String(p.key)] = p.ageSec;
    });
    list.forEach(function (m) {
      if (!m || !m.host) return;
      var s = state(m, ages);
      s.host = String(m.host).toLowerCase();
      s.origin = m.origin === true;
      hosts[s.host] = s;
      order.push(s);
    });
    return { at: at, hosts: hosts, list: order };
  }

  // A state's wording: down, behind by about so many hours, pending, or in sync.
  function say(lv, stale) {
    var t = TEXT[lang()];
    if (lv === 'down') return t.gone;
    if (lv === 'behind') return t.behind.replace('{h}', Math.round(stale / 3600));
    return lv === 'pending' ? t.pending : t.ok;
  }

  // A mirror's tooltip, only when it is down or behind, and its cell text; a reachable relay says it redirects.
  function words(s) {
    var note = s.level === 'down' ? TEXT[lang()].down : s.level === 'behind' ? say(s.level, s.stale) : '';
    return { note: note, cell: s.relay && !s.down ? TEXT[lang()].relay : say(s.level, s.stale) };
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }


  // The status page's rows, in the markup of status-data.js's fact(): the mirror, each tree's state, and
  // when the check ran, in that script's relative wording when it is on the page. The origin and relays
  // have no sync state of their own and get no row.
  function rows(h) {
    var t = TEXT[lang()], age = window.MirrorStatus && window.MirrorStatus.age;
    return h.list.filter(function (m) { return !m.origin && !m.relay; }).map(function (m) {
      var key = NAMES[m.host];
      var name = key && typeof window.MIRROR_T === 'function' ? window.MIRROR_T(key) : '';
      var body = m.trees.map(function (tr) {
        return '<span class="part"><span class="sub">' + escape(tr.key) + '</span> <b class="num">' +
               say(tr.level, tr.stale) + '</b></span>';
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
      // The cell's own phone label (.channel-field) stays in front of the state.
      var label = c.querySelector('.channel-field');
      var w = s ? words(s) : { note: '', cell: '—' };
      c.textContent = w.cell;
      if (label) c.prepend(label);
      if (w.note) c.setAttribute('data-behind', ''); else c.removeAttribute('data-behind');
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
  window.MirrorHealth = { parse: parse, state: state, hostOf: hostOf, apply: apply, rows: rows,
                          GRACE: GRACE, STALE: STALE };
  load();
})();
