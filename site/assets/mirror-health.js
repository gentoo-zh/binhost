// Mirror health from the public status API, fetched once per page load. The API checks each mirror's binpkg
// trees (stable and unstable) from outside the origin; entries match a picker option by the host of its
// data-uri, since the site and the API name some mirrors differently (hernet here, ha there). A mirror that
// is down, or whose larger tree lag exceeds LAG seconds, gets data-behind and a tooltip on its option, and
// a down one also data-down, which keeps the file browser's links on the origin. Cells marked
// data-mirror-host (the mirrors page) show each mirror's state. A failed or slow request changes nothing.
(function () {
  'use strict';
  var API = 'https://status.gentoozh.org/api/status';
  var LAG = 6 * 3600;
  var WAIT = 8000;
  var TEXT = {
    'zh-cn': { behind: '落后约 {h} 小时', down: '上次检查时无法连接', ok: '已同步', gone: '无法连接' },
    'zh-tw': { behind: '落後約 {h} 小時', down: '上次檢查時無法連線', ok: '已同步', gone: '無法連線' },
    en: { behind: 'About {h} hours behind', down: 'Unreachable at the last check', ok: 'In sync', gone: 'Unreachable' },
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

  // One API entry as { down, lag }: down when the mirror or any tree is down, lag the larger tree lag.
  function state(m) {
    var down = m.up === false, lag = 0;
    (m.trees || []).forEach(function (tr) {
      if (tr.up === false) down = true;
      if (typeof tr.lagSec === 'number' && tr.lagSec > lag) lag = tr.lagSec;
    });
    return { down: down, lag: lag };
  }

  function parse(j) {
    var list = j && j.mirrors && j.mirrors.list, out = {};
    if (!Array.isArray(list)) return null;
    list.forEach(function (m) { if (m && m.host) out[String(m.host).toLowerCase()] = state(m); });
    return out;
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

  var health = null;
  function apply() {
    if (!health) return;
    document.querySelectorAll('.src-opt[data-uri]').forEach(function (o) {
      var s = health[hostOf(o.getAttribute('data-uri'))];
      var w = s ? words(s) : { note: '' };
      if (w.note) { o.setAttribute('data-behind', ''); o.title = w.note; }
      else { o.removeAttribute('data-behind'); o.removeAttribute('title'); }
      if (s && s.down) o.setAttribute('data-down', ''); else o.removeAttribute('data-down');
    });
    document.querySelectorAll('[data-mirror-host]').forEach(function (c) {
      var s = health[c.getAttribute('data-mirror-host').toLowerCase()];
      c.textContent = s ? words(s).cell : '—';
      if (s && (s.down || s.lag > LAG)) c.setAttribute('data-behind', ''); else c.removeAttribute('data-behind');
    });
  }

  function load() {
    if (typeof fetch !== 'function') return;
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var late = false;
    var timer = setTimeout(function () { late = true; if (ctl) ctl.abort(); }, WAIT);
    fetch(API, ctl ? { signal: ctl.signal } : {})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        clearTimeout(timer);
        var h = late ? null : parse(j);
        if (!h) return;
        health = h;
        apply();
        // source-switch.js rewrites the file links, now that a down mirror's links stay on the origin.
        document.dispatchEvent(new CustomEvent('sourcechange'));
      })
      .catch(function () { clearTimeout(timer); });
  }

  document.addEventListener('langchange', apply);
  window.MirrorHealth = { parse: parse, state: state, hostOf: hostOf, apply: apply, LAG: LAG };
  load();
})();
