(function () {
  var groups = document.querySelectorAll('[data-src-switch]');
  if (!groups.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  var pickers = [];
  var picked = false;

  // A mirror picked on one page is the choice on every page: mirror-source holds its URI, set only by
  // a click. On load a stored URI that one of this page's mirrors still offers wins over the language
  // default; an unknown or missing value, or storage that cannot be read, leaves the language default.
  // A page restored from the back-forward cache reads it again, since another page may have changed it.
  var KEY = 'mirror-source';
  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function remember(uri) {
    try { localStorage.setItem(KEY, uri); } catch (e) {}
  }

  each(groups, function (group) {
    var name = group.getAttribute('data-src-switch');
    var kind = group.getAttribute('data-src-group') || 'mirror';
    var opts = group.querySelectorAll('.src-opt');
    if (!opts.length) return;

    function ordered(chosen) {
      var rest = Array.prototype.filter.call(opts, function (o) {
        return o !== chosen;
      });
      return [chosen].concat(rest).map(function (o) {
        return o.getAttribute('data-uri');
      }).join(' ');
    }

    function render(chosen) {
      var uri = chosen.getAttribute('data-uri');
      var groupList = group.getAttribute('data-src-list');

      each(opts, function (o) {
        o.classList.toggle('on', o === chosen);
        o.setAttribute('aria-pressed', o === chosen ? 'true' : 'false');
      });

      each(document.querySelectorAll('[data-src-slot="' + name + '"]'),
        function (slot) {
          var list = slot.getAttribute('data-src-list') || groupList;
          slot.textContent = list
            ? list.replace('%s', ordered(chosen))
            : uri + (slot.getAttribute('data-src-suffix') || '');
        });

      // A download link names its path on the mirror. The option marked data-src-here is the server that
      // serves this page, so its links stay on this host. A file that window.MIRROR_MISSING lists for the
      // chosen mirror (the page fills it from /mirror-status.json) also stays here, marked with a badge; true
      // in place of the list means the mirror was unreachable, so every file stays here. The list holds
      // decoded origin paths, so the encoded data-src-path is decoded to compare, and appended as is.
      var missing = (window.MIRROR_MISSING || {})[uri] || [];
      each(document.querySelectorAll('a[data-src-link="' + name + '"]'), function (a) {
        var p = a.getAttribute('data-src-path');
        var raw = p;
        try { raw = decodeURIComponent(p); } catch (e) {}
        var behind = !chosen.hasAttribute('data-src-here') && (missing === true || missing.indexOf(raw) >= 0);
        a.setAttribute('href', chosen.hasAttribute('data-src-here') || behind ? p : uri + p);
        var note = a.nextElementSibling;
        if (note && note.hasAttribute('data-src-note')) note.parentNode.removeChild(note);
        if (!behind || !window.MIRROR_T) return;
        note = document.createElement('span');
        note.className = 'badge';
        note.setAttribute('data-variant', 'neutral');
        note.setAttribute('data-src-note', '');
        note.textContent = window.MIRROR_T('srcBehind');
        note.title = window.MIRROR_T('srcBehindLong');
        a.parentNode.insertBefore(note, a.nextSibling);
      });

      each(document.querySelectorAll('.copy-chip[data-src-copy="' + name + '"]'),
        function (chip) {
          chip.setAttribute('data-copy', groupList
            ? groupList.replace('%s', ordered(chosen))
            : uri + (chip.getAttribute('data-src-suffix') || ''));
        });
    }

    pickers.push({ kind: kind, opts: opts, render: render });

    each(opts, function (btn) {
      btn.addEventListener('click', function () {
        var uri = btn.getAttribute('data-uri');
        picked = true;
        if (kind === 'mirror') remember(uri);
        each(pickers, function (p) {
          if (p.kind !== kind) return;
          var match = Array.prototype.filter.call(p.opts, function (o) {
            return o.getAttribute('data-uri') === uri;
          })[0];
          if (match) p.render(match);
        });
      });
    });
  });

  function defaultOpt(opts) {
    var lang = document.documentElement.getAttribute('data-lang');
    return Array.prototype.filter.call(opts, function (o) {
      var langs = (o.getAttribute('data-src-default') || '').split(' ');
      return langs.indexOf(lang) >= 0;
    })[0] || Array.prototype.filter.call(opts, function (o) {
      return o.classList.contains('on');
    })[0] || opts[0];
  }

  function renderDefaults() {
    each(pickers, function (p) { p.render(defaultOpt(p.opts)); });
  }

  function restore() {
    var uri = stored();
    each(pickers, function (p) {
      if (p.kind !== 'mirror' || !uri) return;
      var match = Array.prototype.filter.call(p.opts, function (o) {
        return o.getAttribute('data-uri') === uri;
      })[0];
      if (match) { p.render(match); picked = true; }
    });
  }

  renderDefaults();
  restore();

  window.addEventListener('pageshow', function (e) {
    if (e.persisted) restore();
  });

  document.addEventListener('sourcechange', function () {
    each(pickers, function (p) {
      var chosen = Array.prototype.filter.call(p.opts, function (o) {
        return o.classList.contains('on');
      })[0];
      if (chosen) p.render(chosen);
    });
  });

  document.addEventListener('langchange', function () {
    if (!picked) renderDefaults();
  });
})();
