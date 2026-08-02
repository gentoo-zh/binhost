/* 在 <head> 里同步执行，在第一次绘制之前把语言和主题定下来。
 *
 * 这两样原来都在 body 末尾才生效，各留下一次闪烁：主题存的是浅色而系统是深色
 * 时，页面先按系统画成深色再跳成浅色；语言不是简体时，先看到一屏简体再换掉。
 */
(function () {
  'use strict';
  var root = document.documentElement;

  function read(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; }
  }

  /* --- 主题 --- */
  /* data-theme 决定配色，只有明确选过浅色或深色时才写。
     data-theme-mode 三种都写，控件靠它决定显示哪个图标、哪一项是当前项。 */
  var mode = read('mirror-theme') || 'system';
  if (mode !== 'light' && mode !== 'dark' && mode !== 'system') mode = 'system';
  root.setAttribute('data-theme-mode', mode);
  if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
  /* 样式表还没到之前，画布色由 color-scheme 决定。head 里的 meta 先声明两种都
     支持，这里按选定的模式收窄——否则深色使用者会先看到一下白。 */
  root.style.colorScheme = mode === 'system' ? 'light dark' : mode;

  /* --- 语言 --- */
  /* 判断规则要和 i18n.js 的 detectLang 一致。真正的语言仍由 i18n.js 决定，
     那边知道每页支持哪几门语言。这里判断错了，代价只是白挡一下。 */
  var lang = read('mirror-lang');
  if (!lang) {
    var n = (navigator && navigator.language) || '';
    lang = /^en/i.test(n) ? 'en'
         : /(^|-)(tw|hk|mo|hant)/i.test(n) ? 'zh-tw'
         : 'zh-cn';
  }
  window.MIRROR_LANG_PREF = lang;
  root.setAttribute('data-lang', lang);

  if (lang === 'zh-cn') return;
  root.className += (root.className ? ' ' : '') + 'lang-swap';

  /* i18n.js 没启动（网络断了、脚本 404、旧浏览器报错）时，页面不能一直空着。
     到点自己揭开，访客看到的是简体原文，好过一片空白。 */
  setTimeout(function () { root.classList.remove('lang-swap'); }, 1500);
})();
