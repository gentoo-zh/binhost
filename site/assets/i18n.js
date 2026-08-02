(function () {
  'use strict';

  var LANGS = [['zh-cn', '简'], ['zh-tw', '繁'], ['en', 'EN']];
  var LANG_NAME = { 'zh-cn': '简体中文', 'zh-tw': '繁體中文', 'en': 'English' };
  var THEME_WORD = { 'zh-cn': '主题', 'zh-tw': '主題', 'en': 'Theme' };
  var THEME_SEP = { 'zh-cn': '：', 'zh-tw': '：', 'en': ': ' };
  var THEME_LABEL = {
    'zh-cn': { light: '浅色', dark: '深色', system: '跟随系统' },
    'zh-tw': { light: '淺色', dark: '深色', system: '跟隨系統' },
    'en': { light: 'Light', dark: 'Dark', system: 'System' }
  };
  var COPIED = { 'zh-cn': '已复制', 'zh-tw': '已複製', 'en': 'Copied' };

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
  function val(l, key) {
    if (l === 'zh-cn') return CN[key];
    var tbl = T[l] || {};
    return (key in tbl) ? tbl[key] : CN[key];
  }

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  var enabled = window.MIRROR_LANGS || LANGS.map(function (p) { return p[0]; });
  var LANG_LIST = LANGS.filter(function (p) { return enabled.indexOf(p[0]) >= 0; });

  function detectLang() {
    var s = read('mirror-lang');
    if (s && enabled.indexOf(s) >= 0) return s;
    var n = navigator.language || '';
    if (/^en/i.test(n) && enabled.indexOf('en') >= 0) return 'en';
    if (/(^|-)(tw|hk|mo|hant)/i.test(n) && enabled.indexOf('zh-tw') >= 0) return 'zh-tw';
    return 'zh-cn';
  }

  var curLang = detectLang();
  var themeMode = read('mirror-theme') || 'system';

  var langBtns = {};
  document.querySelectorAll('.lang-btn').forEach(function (b) {
    var code = b.dataset.lang;
    if (enabled.indexOf(code) < 0) { b.hidden = true; return; }
    langBtns[code] = b;
    b.addEventListener('click', function () { applyLang(code); });
  });

  var themeWrap = document.querySelector('.menu-wrap');
  var themeBtn = themeWrap && themeWrap.querySelector('.theme-btn');
  var menu = themeWrap && themeWrap.querySelector('.menu');
  var items = {};
  if (menu) {
    menu.querySelectorAll('.menu-item').forEach(function (it) {
      items[it.dataset.mode] = it;
      it.addEventListener('click', function () { applyTheme(it.dataset.mode); closeMenu(); themeBtn.focus(); });
    });
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function (e) {
      e.stopPropagation(); if (menu.hidden) openMenu(); else closeMenu();
    });
  }
  document.addEventListener('click', function (e) { if (themeWrap && !themeWrap.contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });

  function openMenu() {
    if (!menu) return;
    menu.hidden = false;
    themeBtn.setAttribute('aria-expanded', 'true');
  }
  function closeMenu() {
    if (!menu) return;
    menu.hidden = true;
    themeBtn.setAttribute('aria-expanded', 'false');
  }

  function renderTheme() {
    if (!themeBtn) return;
    var title = THEME_WORD[curLang] + THEME_SEP[curLang] + THEME_LABEL[curLang][themeMode];
    themeBtn.title = title; themeBtn.setAttribute('aria-label', title);
    ['light', 'dark', 'system'].forEach(function (m) {
      if (items[m]) items[m].lastChild.textContent = THEME_LABEL[curLang][m];
    });
  }
  function applyTheme(mode) {
    themeMode = mode;
    var root = document.documentElement;
    root.setAttribute('data-theme-mode', mode);
    if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
    else root.removeAttribute('data-theme');
    root.style.colorScheme = mode === 'system' ? 'light dark' : mode;
    store('mirror-theme', mode);
    renderTheme();
  }
  function applyLang(l) {
    curLang = l;
    document.documentElement.lang = l;
    document.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = val(l, el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) { el.innerHTML = val(l, el.dataset.i18nHtml); });
    document.querySelectorAll('[data-i18n-href]').forEach(function (el) { el.setAttribute('href', val(l, el.dataset.i18nHref)); });
    document.querySelectorAll('[data-langblock]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock') !== l); });
    document.querySelectorAll('[data-langblock-inline]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock-inline') !== l); });
    document.documentElement.setAttribute('data-lang', l);
    Object.keys(langBtns).forEach(function (k) { langBtns[k].title = LANG_NAME[k]; });
    var pageTitle = val(l, 'title');
    if (pageTitle) document.title = pageTitle + ' — distfiles.gentoozh.org';
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
    var flash = function () {
      if (!toast) return;
      toast.textContent = COPIED[curLang];
      toast.classList.add('show');
      clearTimeout(timer);
      timer = setTimeout(function () { toast.classList.remove('show'); }, 1200);
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
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(flash, flash);
      else {
        var t = document.createElement('textarea'); t.value = v; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(t); flash();
      }
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
