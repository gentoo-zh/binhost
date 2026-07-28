/* 镜像站共享 i18n 引擎 + 统一的语言/主题切换控件。
 *
 * 两页共用一份。加一门语言只改这里的 LANGS/LANG_NAME/THEME_* 数据 + 各页的翻译。
 *
 * 页面侧约定（引入本脚本前声明 window.MIRROR_I18N；共用串在 strings.js）：
 *   1) 逐串翻译：元素加 data-i18n="key"（纯文本）或 data-i18n-html="key"（含标签）。
 *      简体取自文档原文；其它语言由 window.MIRROR_I18N[lang][key] 提供，缺则回落简体。
 *   2) 整段翻译：同一段内容写多份 <div data-langblock="zh-cn"> / "zh-tw" / "en">，
 *      非当前语言的 hidden。行内同理用 data-langblock-inline。简体段直接写在 HTML。
 *   控件注入到 #controls；#copy-toast 存在时才挂「点击复制」。
 *   无脚本 / 文本浏览器下控件整段不存在，页面保持干净（简体原文可读）。
 */
(function () {
  'use strict';

  /* 站点统一的语言与主题文案（加语言只动这几行） */
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
  var ICONS = {
    light: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
    dark: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>',
    system: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>'
  };

  /* 翻译来源：共用串 + 页面自己的表，同名以页面为准 */
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
  var CN = {};                                  // 简体 = 文档原文
  document.querySelectorAll('[data-i18n]').forEach(function (el) { CN[el.dataset.i18n] = el.textContent; });
  document.querySelectorAll('[data-i18n-html]').forEach(function (el) { CN[el.dataset.i18nHtml] = el.innerHTML; });
  function val(l, key) {
    if (l === 'zh-cn') return CN[key];
    var tbl = T[l] || {};
    return (key in tbl) ? tbl[key] : CN[key];   // 缺翻译则回落简体，绝不显示 undefined
  }

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  /* 页面可用 window.MIRROR_LANGS 限定支持的语言（默认全部）。 */
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

  var controls = document.getElementById('controls');

  /* 语言按钮只在页面确实有翻译时才画。design.html 是单语文档，按钮画出来点了
     只会改 localStorage：本页一个字都不变，而别的页跟着换语言。 */
  var translatable = !!document.querySelector('[data-i18n],[data-i18n-html]');

  /* 语言按钮（数据驱动） */
  var langWrap = document.createElement('div'); langWrap.className = 'lang';
  var langBtns = {};
  LANG_LIST.forEach(function (p) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'lang-btn'; b.textContent = p[1]; b.dataset.lang = p[0];
    b.title = LANG_NAME[p[0]];
    b.addEventListener('click', function () { applyLang(p[0]); });
    langWrap.appendChild(b); langBtns[p[0]] = b;
  });

  /* 主题菜单 */
  var themeWrap = document.createElement('div'); themeWrap.className = 'menu-wrap';
  var themeBtn = document.createElement('button');
  themeBtn.type = 'button'; themeBtn.className = 'icon-btn';
  themeBtn.setAttribute('aria-haspopup', 'true'); themeBtn.setAttribute('aria-expanded', 'false');
  var menu = document.createElement('div'); menu.className = 'menu'; menu.setAttribute('role', 'menu'); menu.hidden = true;
  var items = {};
  ['light', 'dark', 'system'].forEach(function (m) {
    var it = document.createElement('button');
    it.type = 'button'; it.className = 'menu-item'; it.setAttribute('role', 'menuitemradio'); it.dataset.mode = m;
    it.innerHTML = ICONS[m] + '<span></span>';
    it.addEventListener('click', function () { applyTheme(m); closeMenu(); themeBtn.focus(); });
    menu.appendChild(it); items[m] = it;
  });
  themeBtn.addEventListener('click', function (e) { e.stopPropagation(); if (menu.hidden) openMenu(); else closeMenu(); });
  themeWrap.appendChild(themeBtn); themeWrap.appendChild(menu);

  /* 没有 #controls 的页面也要应用主题与语言。这两步原先排在提前 return 之后，
     一旦有页面不放控件，用户存的深色偏好就静默失效。 */
  if (controls) {
    if (translatable) controls.appendChild(langWrap);
    controls.appendChild(themeWrap);
  }

  function openMenu() { menu.hidden = false; themeBtn.setAttribute('aria-expanded', 'true'); }
  function closeMenu() { menu.hidden = true; themeBtn.setAttribute('aria-expanded', 'false'); }
  document.addEventListener('click', function (e) { if (!themeWrap.contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });

  function renderTheme() {
    themeBtn.innerHTML = ICONS[themeMode];
    var title = THEME_WORD[curLang] + THEME_SEP[curLang] + THEME_LABEL[curLang][themeMode];
    themeBtn.title = title; themeBtn.setAttribute('aria-label', title);
    ['light', 'dark', 'system'].forEach(function (m) {
      items[m].lastChild.textContent = THEME_LABEL[curLang][m];
      items[m].classList.toggle('active', m === themeMode);
    });
  }
  function applyTheme(mode) {
    themeMode = mode;
    if (mode === 'light' || mode === 'dark') document.documentElement.setAttribute('data-theme', mode);
    else document.documentElement.removeAttribute('data-theme');
    store('mirror-theme', mode);
    renderTheme();
  }
  function applyLang(l) {
    curLang = l;
    document.documentElement.lang = l;
    document.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = val(l, el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) { el.innerHTML = val(l, el.dataset.i18nHtml); });
    document.querySelectorAll('[data-langblock]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock') !== l); });
    document.querySelectorAll('[data-langblock-inline]').forEach(function (el) { el.hidden = (el.getAttribute('data-langblock-inline') !== l); });
    Object.keys(langBtns).forEach(function (k) { langBtns[k].classList.toggle('active', k === l); });
    /* 浏览器标签页的标题原来只有 HTML 里那一份，切语言之后仍是中文。
       每页的 i18n 表本来就有 title，取它拼上站名；没有 title 的页面
       （首页、文件浏览器）只用站名。 */
    var pageTitle = val(l, 'title');
    /* 没有 title 键的页面（设计语言页是单语的）保持 HTML 里那一份，
       否则切一次语言就把它抹成站名。 */
    if (pageTitle) document.title = pageTitle + ' — distfiles.gentoozh.org';
    renderTheme();
    store('mirror-lang', l);
    /* 页面里由脚本自绘的内容（首页那几个数字、包列表的表格）不带 data-i18n，
       applyLang 遍历不到。广播一次，让它们自己重画。 */
    document.dispatchEvent(new CustomEvent('langchange', { detail: l }));
  }

  applyTheme(themeMode);
  applyLang(curLang);

  /* 点击复制。提示条是可选的：整段逻辑原来包在 if (toast) 里，于是 faq 页
     加了一个复制按钮却没有那个 div，按钮按下去毫无反应也毫无报错。功能不该
     取决于一个装饰元素在不在。 */
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
    var copy = function (el) {
      var v = el.getAttribute('data-copy');
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(flash, flash);
      else {
        var t = document.createElement('textarea'); t.value = v; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(t); flash();
      }
    };
    document.addEventListener('click', function (e) {
      var chip = e.target.closest ? e.target.closest('.copy-chip[data-copy]') : null;
      if (chip) copy(chip);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var el = document.activeElement;
      if (el && el.classList && el.classList.contains('copy-chip')) { e.preventDefault(); copy(el); }
    });
  }
})();
