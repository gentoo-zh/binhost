(function () {
  'use strict';

  var LANGS = [['zh-cn', '简'], ['zh-tw', '繁'], ['en', 'EN']];
  var LANG_NAME = { 'zh-cn': '简体中文', 'zh-tw': '繁體中文', 'en': 'English' };
  var LANG_WORD = { 'zh-cn': '语言', 'zh-tw': '語言', 'en': 'Language' };
  var THEME_SEP = { 'zh-cn': '：', 'zh-tw': '：', 'en': ': ' };
  // The theme button's name: the mode in force (with the system's theme while following it), then what a
  // press does, as the React Spectrum docs name their toggle.
  var THEME_LABEL = {
    'zh-cn': {
      'system-light': '主题：跟随系统（浅色），按下改用深色', 'system-dark': '主题：跟随系统（深色），按下改用浅色',
      light: '主题：浅色，按下恢复跟随系统', dark: '主题：深色，按下恢复跟随系统'
    },
    'zh-tw': {
      'system-light': '主題：跟隨系統（淺色），按下改用深色', 'system-dark': '主題：跟隨系統（深色），按下改用淺色',
      light: '主題：淺色，按下恢復跟隨系統', dark: '主題：深色，按下恢復跟隨系統'
    },
    'en': {
      'system-light': 'Theme: system (light), press to use dark', 'system-dark': 'Theme: system (dark), press to use light',
      light: 'Theme: light, press to use system', dark: 'Theme: dark, press to use system'
    }
  };
  var THEME_MODES = ['light', 'dark', 'system'];
  var COPIED = { 'zh-cn': '已复制', 'zh-tw': '已複製', 'en': 'Copied' };
  var COPY_FAILED = {
    'zh-cn': '复制失败，请手动选择文本。',
    'zh-tw': '複製失敗，請手動選取文字。',
    'en': 'Copy failed; select the text manually.'
  };

  var T = {};
  (function () {
    var common = window.MIRROR_I18N_COMMON || {};
    var page = window.MIRROR_I18N || {};
    Object.keys(common).concat(Object.keys(page)).forEach(function (l) {
      T[l] = {};
      Object.keys(common[l] || {}).forEach(function (k) { T[l][k] = common[l][k]; });
      Object.keys(page[l] || {}).forEach(function (k) { T[l][k] = page[l][k]; });
    });
  })();
  var CN = {};
  Object.keys((window.MIRROR_I18N || {})['zh-cn'] || {}).forEach(function (k) {
    CN[k] = window.MIRROR_I18N['zh-cn'][k];
  });
  document.querySelectorAll('[data-i18n]').forEach(function (el) { CN[el.dataset.i18n] = el.textContent; });
  document.querySelectorAll('[data-i18n-html]').forEach(function (el) { CN[el.dataset.i18nHtml] = el.innerHTML; });
  document.querySelectorAll('[data-i18n-href]').forEach(function (el) { CN[el.dataset.i18nHref] = el.getAttribute('href'); });
  document.querySelectorAll('[data-i18n-label]').forEach(function (el) { CN[el.dataset.i18nLabel] = el.getAttribute('aria-label'); });
  function val(l, key) {
    if (l === 'zh-cn') return CN[key];
    var tbl = T[l] || {};
    return (key in tbl) ? tbl[key] : CN[key];
  }

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function forget(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function normaliseTheme(mode) {
    return THEME_MODES.indexOf(mode) >= 0 ? mode : 'system';
  }

  var enabled = window.MIRROR_LANGS || LANGS.map(function (p) { return p[0]; });
  var LANG_LIST = LANGS.filter(function (p) { return enabled.indexOf(p[0]) >= 0; });

  // A ?lang= link (the language links shown without scripts) picks the language and is remembered.
  function queryLang() {
    var loc = window.location;
    var m = loc && /[?&]lang=([\w-]+)/.exec(loc.search || '');
    return m && enabled.indexOf(m[1]) >= 0 ? m[1] : null;
  }

  function detectLang() {
    var q = queryLang();
    if (q) { store('mirror-lang', q); return q; }
    var s = read('mirror-lang');
    if (s && enabled.indexOf(s) >= 0) return s;
    var n = navigator.language || '';
    if (/^en/i.test(n) && enabled.indexOf('en') >= 0) return 'en';
    if (/(^|-)(tw|hk|mo|hant)/i.test(n) && enabled.indexOf('zh-tw') >= 0) return 'zh-tw';
    return 'zh-cn';
  }

  var curLang = detectLang();
  var themeMode = normaliseTheme(read('mirror-theme') || 'system');

  // Spectrum menu button (language): a quiet button opening a menu of menuitemradio items.
  // The trigger opens on click, Enter, Space or ArrowDown with focus on the checked item (ArrowUp: the
  // last); arrows, Home and End move; Enter or Space picks; Escape closes and returns focus to the
  // trigger; Tab, a click outside or opening another menu closes it.
  var menus = [];
  function menuButton(wrap, onPick) {
    var trigger = wrap.querySelector('.menu-trigger');
    var menu = wrap.querySelector('[role="menu"]');
    if (!trigger || !menu) return null;
    var items = [];
    menu.querySelectorAll('[role="menuitemradio"]').forEach(function (it) {
      if (it.hidden) return;
      items.push(it);
      it.setAttribute('tabindex', '-1');
      it.addEventListener('click', function () {
        onPick(it.getAttribute('data-value'));
        close();
        trigger.focus();
      });
    });
    function checkedIndex() {
      for (var i = 0; i < items.length; i++) if (items[i].getAttribute('aria-checked') === 'true') return i;
      return 0;
    }
    function focusItem(i) {
      if (!items.length) return;
      var n = ((i % items.length) + items.length) % items.length;
      items.forEach(function (it, k) { it.setAttribute('tabindex', k === n ? '0' : '-1'); });
      items[n].focus();
    }
    function open(at) {
      menus.forEach(function (m) { if (m.wrap !== wrap) m.close(); });
      menu.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      focusItem(at === 'last' ? items.length - 1 : checkedIndex());
    }
    function close() {
      if (menu.hidden) return;
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.hidden) open(); else close();
    });
    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); open('last'); }
    });
    menu.addEventListener('keydown', function (e) {
      var here = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(here + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(here - 1); }
      else if (e.key === 'Home') { e.preventDefault(); focusItem(0); }
      else if (e.key === 'End') { e.preventDefault(); focusItem(items.length - 1); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); trigger.focus(); }
      else if (e.key === 'Tab') { close(); }
    });
    var api = { wrap: wrap, trigger: trigger, items: items, close: close };
    menus.push(api);
    return api;
  }
  document.addEventListener('click', function (e) {
    menus.forEach(function (m) { if (!m.wrap.contains(e.target)) m.close(); });
  });

  var langMenu = null;
  document.querySelectorAll('[data-menu="lang"]').forEach(function (wrap) {
    wrap.querySelectorAll('[role="menuitemradio"]').forEach(function (it) {
      if (enabled.indexOf(it.getAttribute('data-value')) < 0) it.hidden = true;
    });
    langMenu = menuButton(wrap, applyLang);
  });

  function renderLang() {
    if (!langMenu) return;
    var name = LANG_WORD[curLang] + THEME_SEP[curLang] + LANG_NAME[curLang];
    langMenu.trigger.setAttribute('aria-label', name);
    langMenu.items.forEach(function (it) {
      it.setAttribute('aria-checked', it.getAttribute('data-value') === curLang ? 'true' : 'false');
    });
  }

  // The theme toggle cycles as the React Spectrum docs' button does: following the system, a press forces
  // the other theme; with a theme forced, a press follows the system again. While following, a change of
  // the system setting renames the button (CSS turns the icon).
  var themeBtn = document.getElementById('theme-toggle');
  var darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function systemTheme() { return darkQuery && darkQuery.matches ? 'dark' : 'light'; }

  function renderTheme() {
    if (!themeBtn) return;
    var label = THEME_LABEL[curLang][themeMode === 'system' ? 'system-' + systemTheme() : themeMode];
    themeBtn.title = label;
    themeBtn.setAttribute('aria-label', label);
  }

  function applyTheme(mode) {
    mode = normaliseTheme(mode);
    themeMode = mode;
    var root = document.documentElement;
    if (mode === 'system') { root.removeAttribute('data-theme'); forget('mirror-theme'); }
    else { root.setAttribute('data-theme', mode); store('mirror-theme', mode); }
    root.style.colorScheme = mode === 'system' ? 'light dark' : mode;
    renderTheme();
  }

  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      applyTheme(themeMode !== 'system' ? 'system' : systemTheme() === 'dark' ? 'light' : 'dark');
    });
  }
  if (darkQuery) {
    if (darkQuery.addEventListener) darkQuery.addEventListener('change', renderTheme);
    else if (darkQuery.addListener) darkQuery.addListener(renderTheme);
  }
  function applyLang(l) {
    curLang = l;
    document.documentElement.lang = l;
    document.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = val(l, el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) { el.innerHTML = val(l, el.dataset.i18nHtml); });
    document.querySelectorAll('[data-i18n-href]').forEach(function (el) { el.setAttribute('href', val(l, el.dataset.i18nHref)); });
    document.querySelectorAll('[data-i18n-label]').forEach(function (el) { el.setAttribute('aria-label', val(l, el.dataset.i18nLabel)); });
    document.querySelectorAll('[data-langblock]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock') !== l); });
    document.querySelectorAll('[data-langblock-inline]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock-inline') !== l); });
    document.documentElement.setAttribute('data-lang', l);
    renderLang();
    var pageTitle = val(l, 'title');
    if (pageTitle) {
      var loc = window.location;
      // The overview page is the site itself, so its title is just the brand, not "Overview — brand".
      var atHome = loc && (loc.pathname === '/' || /\/index(\.html)?$/.test(loc.pathname || ''));
      document.title = atHome ? val(l, 'brand') : pageTitle + ' — ' + val(l, 'brand');
    }
    renderTheme();
    store('mirror-lang', l);
    document.dispatchEvent(new CustomEvent('langchange', { detail: l }));
  }

  window.MIRROR_T = function (key) { return val(curLang, key); };

  applyTheme(themeMode);
  applyLang(curLang);
  document.documentElement.classList.remove('lang-swap');

  {
    var toast = document.getElementById('copy-toast');
    var timer;
    // As the React Spectrum docs' CopyButton (s2-docs src/CopyButton.tsx:42-58): a copy turns the button's
    // icon to a checkmark for 2s; only a failure shows a toast. The toast is also the live region, so a
    // success is announced without being shown.
    var flash = function (okay, el) {
      if (okay && el) {
        el.setAttribute('data-copied', '');
        clearTimeout(el.copiedTimer);
        el.copiedTimer = setTimeout(function () { el.removeAttribute('data-copied'); }, 2000);
      }
      if (!toast) return;
      toast.textContent = okay ? COPIED[curLang] : COPY_FAILED[curLang];
      toast.classList.toggle('failed', !okay);
      toast.classList.toggle('show', !okay);
      clearTimeout(timer);
      timer = setTimeout(function () { toast.classList.remove('show'); toast.textContent = ''; }, okay ? 1200 : 2600);
    };
    var value = function (el) {
      var v = el.getAttribute('data-copy');
      if (v !== null) return v;
      var box = el.closest ? el.closest('.code') : null;
      if (!box) return '';
      var pre = box.querySelector('pre[data-pane]:not([hidden])') || box.querySelector('pre');
      if (!pre) return '';
      var clone = pre.cloneNode(true);
      Array.prototype.forEach.call(clone.querySelectorAll('[hidden]'), function (el) {
        el.parentNode.removeChild(el);
      });
      return clone.textContent.replace(/\s+$/, '');
    };
    var copy = function (el) {
      var v = value(el);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(v).then(
          function () { flash(true, el); },
          function () { flash(false, el); });
        return;
      }
      var t = document.createElement('textarea');
      t.value = v; document.body.appendChild(t); t.select();
      var okay = false;
      try { okay = document.execCommand('copy'); } catch (e) { okay = false; }
      document.body.removeChild(t);
      flash(!!okay, el);
    };
    document.addEventListener('click', function (e) {
      var chip = e.target.closest ? e.target.closest('.copy-chip') : null;
      if (chip) copy(chip);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var el = document.activeElement;
      if (el && el.classList && el.classList.contains('copy-chip')) { e.preventDefault(); copy(el); }
    });
  }
})();
