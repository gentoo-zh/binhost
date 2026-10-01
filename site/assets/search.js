// Site search, after the React Spectrum docs' search as the doona docs copy it: a modal dialog opened from the
// top bar, Ctrl K (Command K) or /; a search field over category chips and a listbox of page cards, with
// overlay packages as compact rows. Focus stays in the field, which points at the active result with
// aria-activedescendant; the arrow keys, Home and End move it and Enter opens it. The page index
// (build-search-index.py) and /packages.json load on the first open.
(function () {
  'use strict';

  var LANGS = ['zh-cn', 'zh-tw', 'en'];
  var PKG_MIN = 2;
  var PKG_LIMIT = 30;

  function norm(s) {
    s = String(s == null ? '' : s);
    return (s.normalize ? s.normalize('NFKC') : s).toLowerCase();
  }

  // A query may hold the wildcards * (any run of characters) and ? (one character). find(s) is where the
  // query first matches in s, -1 for none, ignoring a leading or trailing *; whole(s) is whether it matches
  // all of s, as a shell glob does. q is normalized.
  function pattern(q) {
    function regex(g) {
      return g.split('').map(function (c) {
        return c === '*' ? '.*' : c === '?' ? '.' : c.replace(/[\\^$.|+()[\]{}\/-]/g, '\\$&');
      }).join('');
    }
    var core = q.replace(/^\*+|\*+$/g, '');
    var part = /[*?]/.test(core) ? new RegExp(regex(core)) : null;
    var all = /[*?]/.test(q) ? new RegExp('^(?:' + regex(q) + ')$') : null;
    return {
      find: function (s) {
        if (!part) return s.indexOf(core);
        var m = part.exec(s);
        return m ? m.index : -1;
      },
      whole: function (s) { return all ? all.test(s) : s === q; }
    };
  }

  // How many characters of a query are not wildcards.
  function literal(q) { return q.replace(/[*?]/g, '').length; }

  // Where an entry ranks in one language, best first: its title starts with the query, its title holds it,
  // its description (the page it sits in, or the page's lead) holds it, a keyword holds it; -1 is no match.
  function tier(entry, lang, q) {
    var p = typeof q === 'string' ? pattern(q) : q;
    var at = p.find(norm(entry.title[lang]));
    var tiers = [at === 0, at >= 0, p.find(norm(entry.desc[lang])) >= 0,
      (entry.keywords || []).some(function (k) { return p.find(norm(k)) >= 0; })];
    return tiers.indexOf(true);
  }

  // A match in the reader's language ranks above any match in another; within a tier a page ranks above a
  // section. q is normalized, or a pattern() of it. Infinity is no match.
  function rank(entry, lang, q) {
    if (typeof q === 'string') q = pattern(q);
    var t = tier(entry, lang, q);
    var other = 0;
    if (t < 0) {
      LANGS.forEach(function (l) {
        var u = l === lang ? -1 : tier(entry, l, q);
        if (u >= 0 && (t < 0 || u < t)) t = u;
      });
      other = 8;
    }
    return t < 0 ? Infinity : other + 2 * t + (entry.kind === 'section' ? 1 : 0);
  }

  // The page and section entries for a query in a category ('' is all; 'pkgs' holds no pages). An empty
  // query lists the category's pages in sidebar order; otherwise matches best first, index order within a rank.
  function search(index, lang, query, group) {
    var q = norm(String(query).trim());
    if (group === 'pkgs') return [];
    var inGroup = index.entries.filter(function (e) { return !group || e.group === group; });
    if (!literal(q)) return inGroup.filter(function (e) { return e.kind === 'page'; });
    var p = pattern(q);
    return inGroup
      .map(function (e, i) { return { e: e, r: rank(e, lang, p), i: i }; })
      .filter(function (x) { return x.r < Infinity; })
      .sort(function (a, b) { return a.r - b.r || a.i - b.i; })
      .map(function (x) { return x.e; });
  }

  // Overlay packages whose category/name holds the query, from PKG_MIN characters that are not wildcards: a
  // name starting with it first, then category/name starting with it, then either holding it; alphabetical
  // within a rank. A query with wildcards matches the whole name or the whole category/name instead, as
  // equery list does: fcitx* starts with fcitx, *-bin ends in -bin, app-i18n/* is the category.
  function packages(list, query, limit) {
    var q = norm(String(query).trim());
    if (literal(q) < PKG_MIN) return { hits: [], total: 0 };
    var p = pattern(q), glob = /[*?]/.test(q);
    var hits = [];
    list.forEach(function (cp) {
      var full = norm(cp);
      var name = full.slice(full.indexOf('/') + 1);
      var r = glob ? (p.whole(name) ? 0 : p.whole(full) ? 1 : -1)
        : p.find(name) === 0 ? 0 : p.find(full) === 0 ? 1 : p.find(full) >= 0 ? 2 : -1;
      if (r >= 0) hits.push({ cp: cp, r: r });
    });
    hits.sort(function (a, b) { return a.r - b.r || (a.cp < b.cp ? -1 : a.cp > b.cp ? 1 : 0); });
    return { hits: hits.slice(0, limit || PKG_LIMIT).map(function (h) { return h.cp; }), total: hits.length };
  }

  // The option a key moves to among count options from current (-1: none active); null leaves the key alone.
  function step(key, current, count) {
    if (!count) return null;
    if (key === 'ArrowDown') return current < 0 ? 0 : (current + 1) % count;
    if (key === 'ArrowUp') return current <= 0 ? count - 1 : current - 1;
    if (key === 'Home') return 0;
    if (key === 'End') return count - 1;
    return null;
  }

  // What a keydown outside the dialog does: 'toggle' for Ctrl K or Command K, 'open' for / typed outside a
  // text field, else null.
  function shortcut(e) {
    if (e.isComposing) return null;
    var k = String(e.key || '').toLowerCase();
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && k === 'k') return 'toggle';
    if (k !== '/' || e.ctrlKey || e.metaKey || e.altKey) return null;
    var t = e.target || {};
    var tag = String(t.tagName || '').toLowerCase();
    if (t.isContentEditable || tag === 'textarea' || tag === 'select' ||
        (tag === 'input' && !/^(button|checkbox|radio|range|reset|submit|color|file|image)$/i.test(t.type || ''))) {
      return null;
    }
    return 'open';
  }

  window.MIRROR_SEARCH = { rank: rank, search: search, packages: packages, step: step, shortcut: shortcut };

  var dialog = document.getElementById('site-search');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  var root = document.documentElement;
  var input = dialog.querySelector('.sd-input');
  var chips = dialog.querySelector('.sd-chips');
  var results = dialog.querySelector('.sd-results');
  var msg = dialog.querySelector('.sd-msg');
  var retry = dialog.querySelector('.sd-retry');
  var triggers = Array.prototype.slice.call(document.querySelectorAll('[aria-controls="site-search"]'));
  var reduce = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: true };
  var phone = window.matchMedia ? window.matchMedia('(max-width: 63.99rem)') : { matches: false };
  var SVG = 'http://www.w3.org/2000/svg';
  // The Spectrum LinkOut UI icon (S2_LinkOutSize200 in @react-spectrum/s2 1.7.1), geometry unchanged,
  // Apache-2.0 (NOTICE).
  var LINK_OUT = 'M10.089 1h-5.51a.911.911 0 0 0 0 1.822h3.31L1.355 9.355a.91.91 0 1 0 1.29 1.29L9.178 4.11v3.31a.911.911 0 0 0 1.822 0v-5.51A.91.91 0 0 0 10.089 1';

  var index = null, indexState = 'idle';   // idle, loading, ready, failed
  var pkgs = null, pkgState = 'idle';
  var group = null;                        // null until the index names the current page's group
  var opener = null;
  var active = -1;
  var leaving = false;

  function t(key) { return window.MIRROR_T ? window.MIRROR_T(key) || '' : ''; }
  function lang() { var l = root.getAttribute('data-lang'); return LANGS.indexOf(l) >= 0 ? l : 'zh-cn'; }
  function fill(text, vars) {
    // A function replacement, so a query holding $& or $' is shown as typed.
    return text.replace(/\{(\w+)\}/g, function (m, k) { return k in vars ? String(vars[k]) : m; });
  }
  function here() { return location.pathname.replace(/\.html$/, '').replace(/\/index$/, '/') || '/'; }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  var kbd = document.querySelector('.search-kbd');
  var nav = navigator.userAgentData && navigator.userAgentData.platform || navigator.platform || '';
  if (kbd && /mac|iphone|ipad/i.test(nav)) kbd.textContent = '⌘K';
  if (document.startViewTransition) root.setAttribute('data-sd-vt', '');

  function load() {
    if (indexState === 'idle' || indexState === 'failed') {
      indexState = 'loading';
      fetch(dialog.getAttribute('data-src')).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).then(function (data) {
        index = data;
        indexState = 'ready';
        if (group === null) {
          var mine = index.entries.filter(function (e) { return e.kind === 'page' && e.url === here(); })[0];
          group = mine ? mine.group : '';
        }
        render();
      }, function () { indexState = 'failed'; render(); });
    }
    if (pkgState === 'idle') loadPackages();
  }
  function loadPackages() {
    pkgState = 'loading';
    fetch('/packages.json').then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) {
      pkgs = (data.packages || []).map(function (p) { return p.cp; }).filter(Boolean);
      pkgState = 'ready';
      render();
    }, function () { pkgState = 'failed'; render(); });
  }

  function renderChips() {
    // A rebuild removes the focused chip; focus moves to its replacement (the community link has no group).
    var had = document.activeElement;
    had = had && had !== chips && chips.contains(had) ? had : null;
    var hadGroup = had ? had.getAttribute('data-group') : null;
    chips.textContent = '';
    if (!index) return;
    // All, a divider, the sidebar's groups and packages, a divider, then the community site as a link out,
    // as the docs' search ends its filters with a link to the sibling site.
    var list = [['', t('sdAll')], null].concat(index.groups.map(function (g) { return [g.id, g.label[lang()]]; }),
      [['pkgs', t('sdPkgs')], null]);
    list.forEach(function (c) {
      if (!c) {
        var d = el('span', 'sd-divider');
        d.setAttribute('aria-hidden', 'true');
        chips.appendChild(d);
        return;
      }
      var b = el('button', 'sd-chip', c[1]);
      b.type = 'button';
      b.setAttribute('data-group', c[0]);
      b.setAttribute('aria-pressed', String(c[0] === group));
      chips.appendChild(b);
    });
    var out = el('a', 'sd-chip', t('fCommunity'));
    out.href = t('fCommunityUrl') || 'https://gentoozh.org/';
    out.target = '_blank';
    out.rel = 'noopener';
    out.appendChild(glyph('sd-chip-out', '0 0 12 12', [LINK_OUT]));
    chips.appendChild(out);
    if (had) {
      var back = hadGroup === null ? out : chips.querySelector('[data-group="' + hadGroup + '"]');
      if (back) back.focus();
    }
    // On a phone the chips scroll sideways; the chosen one is kept in view.
    var on = chips.querySelector('[aria-pressed="true"]');
    if (on && on.scrollIntoView && dialog.open) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function glyph(cls, viewBox, paths) {
    var svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('class', cls);
    svg.setAttribute('viewBox', viewBox);
    svg.setAttribute('aria-hidden', 'true');
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG, 'path');
      p.setAttribute('fill', 'currentColor');
      p.setAttribute('d', d);
      svg.appendChild(p);
    });
    return svg;
  }
  function art(entry) {
    var span = el('span', 'sd-art');
    // A page with an icon of its own shows it; any other shows its group's.
    var g = index.groups.filter(function (x) { return x.id === entry.group; })[0];
    var icon = entry.icon || (g && g.icon);
    if (icon) {
      span.appendChild(glyph('sd-art-icon', icon.viewBox, icon.paths));
    } else {
      var img = el('img', 'sd-art-logo');
      img.src = '/assets/logo.webp';
      img.alt = '';
      span.appendChild(img);
    }
    return span;
  }

  var serial = 0;
  function option(tag, cls, href) {
    var o = el(tag, cls);
    o.id = 'sd-o-' + (serial++);
    o.href = href;
    o.setAttribute('role', 'option');
    o.setAttribute('tabindex', '-1');
    o.setAttribute('aria-selected', 'false');
    return o;
  }
  function section(id, title) {
    var s = el('div', 'sd-group');
    s.setAttribute('role', 'group');
    if (title) {
      var h = el('p', 'sd-head', title);
      h.id = id;
      s.setAttribute('aria-labelledby', id);
      s.appendChild(h);
    }
    results.appendChild(s);
    return s;
  }
  function status(text, canRetry) {
    msg.textContent = text || '';
    retry.hidden = !canRetry;
  }

  var shown = null;                        // the category and query the list was last built for
  function render() {
    var l = lang();
    var raw = input.value.trim();
    var q = norm(raw);
    // A rebuild for the same category and query (late data, a retry, a language switch) keeps the active
    // result, so Enter still opens the one the user chose; a new query or category starts at the first.
    var was = active >= 0 ? options()[active] : null;
    var keep = was && shown === group + '\n' + q ? was.href : null;
    shown = group + '\n' + q;
    input.setAttribute('placeholder', t('sdOpen'));
    renderChips();
    results.textContent = '';
    active = -1;
    input.removeAttribute('aria-activedescendant');
    if (!index) {
      status(indexState === 'failed' ? t('sdFailed') : t('sdLoading'), indexState === 'failed');
      return;
    }
    status('');
    var pages = search(index, l, raw, group);
    var wantPkgs = (group === '' || group === 'pkgs') && literal(q) >= PKG_MIN;
    if (pages.length) {
      var box = el('div', 'sd-cards');
      section('sd-h-pages', literal(q) ? t('aPages') : '').appendChild(box);
      var me = here();
      pages.forEach(function (e) {
        var card = option('a', 'sd-card', e.url);
        if (e.url === me) card.setAttribute('aria-current', 'page');
        var text = el('span', 'sd-text');
        text.appendChild(el('span', 'sd-title', e.title[l]));
        if (e.desc[l]) text.appendChild(el('span', 'sd-desc', e.desc[l]));
        card.appendChild(art(e));
        card.appendChild(text);
        box.appendChild(card);
      });
    }
    var pkgCount = 0;
    if (wantPkgs) {
      if (pkgState === 'ready') {
        var found = packages(pkgs, raw, PKG_LIMIT);
        pkgCount = found.hits.length;
        if (pkgCount) {
          var list = section('sd-h-pkgs', t('sdPkgs'));
          found.hits.forEach(function (cp) {
            var row = option('a', 'sd-pkg', 'https://github.com/gentoo-zh/overlay/tree/master/' + cp);
            var cut = cp.indexOf('/') + 1;
            row.appendChild(el('span', 'sd-pkg-cat', cp.slice(0, cut)));
            row.appendChild(el('span', 'sd-pkg-name', cp.slice(cut)));
            list.appendChild(row);
          });
          if (found.total > pkgCount) {
            list.appendChild(el('p', 'sd-more', fill(t('sdPkgMore'), { n: found.total, m: pkgCount })));
          }
        }
      } else if (group === 'pkgs' || !pages.length) {
        status(pkgState === 'failed' ? t('sdPkgFailed') : t('sdLoading'), pkgState === 'failed');
        return;
      }
    }
    if (group === 'pkgs' && literal(q) < PKG_MIN) status(t('sdPkgHint'));
    else if (q && !pages.length && !pkgCount) status(fill(t('sdNone'), { q: raw }));
    else if (wantPkgs && pkgState === 'failed') status(t('sdPkgFailed'), true);
    if (q) {
      var all = options(), at = 0;
      for (var i = 0; keep && i < all.length; i++) if (all[i].href === keep) { at = i; break; }
      activate(at);
    }
  }

  function options() { return results.querySelectorAll('[role="option"]'); }
  function activate(i) {
    var all = options();
    if (active >= 0 && all[active]) all[active].setAttribute('aria-selected', 'false');
    active = i < all.length ? i : -1;
    if (active < 0) { input.removeAttribute('aria-activedescendant'); return; }
    all[active].setAttribute('aria-selected', 'true');
    input.setAttribute('aria-activedescendant', all[active].id);
    all[active].scrollIntoView({ block: 'nearest' });
  }

  // Opening and closing morph between the top-bar trigger and the dialog through a View Transition, as the
  // React Spectrum docs' search does; on a phone, where the dialog is a full sheet, the page cross-fades.
  // Without View Transitions the dialog fades in (site.css); with reduced motion nothing moves.
  function swap(from, to, update) {
    if (!document.startViewTransition || reduce.matches) { update(); return; }
    var morph = !phone.matches && from && to && from.getClientRects().length && to.getClientRects;
    if (morph) from.setAttribute('data-sd-morph', '');
    var vt = document.startViewTransition(function () {
      if (morph) from.removeAttribute('data-sd-morph');
      update();
      if (morph) to.setAttribute('data-sd-morph', '');
    });
    vt.finished.then(done, done);
    function done() { if (morph) to.removeAttribute('data-sd-morph'); }
  }

  function visibleTrigger() {
    return triggers.filter(function (b) { return b.getClientRects().length; })[0] || null;
  }
  function open(from, seed) {
    if (dialog.open) return;
    opener = from || document.activeElement;
    leaving = false;
    // A character typed on the trigger starts the query, as typing into the docs' field does.
    if (seed) {
      input.value = seed;
      if (group !== 'pkgs') group = '';
    }
    var trigger = from && triggers.indexOf(from) >= 0 ? from : visibleTrigger();
    swap(trigger, dialog, function () {
      dialog.showModal();
      triggers.forEach(function (b) { b.setAttribute('aria-expanded', 'true'); });
      input.focus();
      if (seed) input.setSelectionRange(input.value.length, input.value.length); else input.select();
    });
    load();
    render();
  }
  function close(animate) {
    if (!dialog.open) return;
    var trigger = visibleTrigger();
    var finish = function () { dialog.close(); };
    if (animate) swap(dialog, trigger, finish); else finish();
  }
  dialog.addEventListener('close', function () {
    triggers.forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
    // Following a result leaves focus where the navigation puts it; otherwise it returns to the opener.
    if (!leaving && opener && opener.isConnected && opener.focus) opener.focus();
  });

  triggers.forEach(function (b) {
    b.addEventListener('click', function () { open(b); });
    // The trigger looks like a field, so typing on it searches: a printable character opens the dialog with
    // that character in the field. Space and Enter stay the button's own keys and / stays the shortcut. An
    // IME key has no character yet, so it only opens. Focus alone opens nothing, as on the docs: focus
    // returns here when the dialog closes, and opening on focus would open it again.
    b.addEventListener('keydown', function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      var k = String(e.key || '');
      if (k === 'Process') { open(b); return; }
      if (k.length !== 1 || k === ' ' || k === '/') return;
      e.preventDefault();
      open(b, k);
    });
  });
  dialog.querySelector('.sd-close').addEventListener('click', function () { close(true); });
  dialog.addEventListener('cancel', function (e) { e.preventDefault(); close(true); });
  // A modal dialog makes the page inert, but Tab from its last control would still leave for the browser's
  // own controls; it wraps to the first instead, and Shift Tab from the first to the last.
  dialog.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    var stops = Array.prototype.filter.call(dialog.querySelectorAll('a[href], input, button'), function (n) {
      return !n.disabled && n.tabIndex >= 0 && n.getClientRects().length;
    });
    if (!stops.length) return;
    var first = stops[0], last = stops[stops.length - 1];
    if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  });
  dialog.addEventListener('click', function (e) {
    if (e.target !== dialog) return;
    var r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) close(true);
  });
  chips.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button.sd-chip') : null;
    if (!b) return;
    group = b.getAttribute('data-group');
    render();
    var again = chips.querySelector('[data-group="' + group + '"]');
    if (again) again.focus();
  });
  retry.addEventListener('click', function () {
    // Everything that failed is fetched again: load() retries the index, not the packages.
    if (indexState === 'failed') load();
    if (pkgState === 'failed') loadPackages();
    render();
    input.focus();
  });
  results.addEventListener('click', function (e) {
    var o = e.target.closest ? e.target.closest('[role="option"]') : null;
    if (!o || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    leaving = true;
    close(false);
  });

  input.addEventListener('input', function () {
    // Typing searches every category, as the docs' search does; a chip picked afterwards narrows it.
    if (input.value.trim() && group !== 'pkgs') group = '';
    render();
  });
  input.addEventListener('keydown', function (e) {
    if (e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'Escape') { e.preventDefault(); close(true); return; }
    if (e.key === 'Enter') {
      var all = options();
      if (active >= 0 && all[active]) { e.preventDefault(); all[active].click(); }
      return;
    }
    if (e.shiftKey && (e.key === 'Home' || e.key === 'End')) return;
    var next = step(e.key, active, options().length);
    if (next === null) return;
    e.preventDefault();
    activate(next);
  });

  document.addEventListener('keydown', function (e) {
    var what = shortcut(e);
    if (!what) return;
    if (what === 'toggle') {
      e.preventDefault();
      if (dialog.open) close(true); else open(null);
    } else if (!dialog.open && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      open(null);
    }
  });
  document.addEventListener('langchange', function () { if (dialog.open) render(); });
})();
