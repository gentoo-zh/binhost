/* 镜像站共享 i18n 引擎 + 统一的语言/主题切换控件。
 *
 * 两页共用一份。加一门语言只改这里的 LANGS/LANG_NAME/THEME_* 数据 + 各页的翻译。
 *
 * 页面侧约定（引入本脚本前声明 window.MIRROR_I18N；共用串在 strings.js）：
 *   1) 逐串翻译：元素加 data-i18n="key"（纯文本）或 data-i18n-html="key"（含标签）。
 *      简体取自文档原文；其它语言由 window.MIRROR_I18N[lang][key] 提供，缺则回落简体。
 *   2) 整段翻译：同一段内容写多份 <div data-langblock="zh-cn"> / "zh-tw" / "en">，
 *      非当前语言的 hidden。行内同理用 data-langblock-inline。简体段直接写在 HTML。
 *   控件的标记在页面里，本脚本只做绑定；#copy-toast 存在时才挂点击复制。
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
  /* 链接地址也分语言：gentoozh.org 按语言分路径。 */
  document.querySelectorAll('[data-i18n-href]').forEach(function (el) { CN[el.dataset.i18nHref] = el.getAttribute('href'); });
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

  /* 控件的标记写在页面里，这里只做绑定。原来是脚本创建再插进去，所以顶栏会
     晚一拍才变样，当前项和图标也跟着晚。 */
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

  /* 图标与当前项由 <html> 上的 data-theme-mode 决定，CSS 自己挑，这里只管文案。 */
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
  /* early.js 为了不让访客看见换语言前那一屏，先把正文挡住了。换完揭开。
     它自己也有个 1.5 秒的兜底，那是留给本脚本没跑起来的情形。 */
  document.documentElement.classList.remove('lang-swap');

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
