/* 在 <head> 里同步执行，只做一件事：决定要不要先把正文挡住。
 *
 * 页面的简体原文就写在 HTML 里，i18n.js 在 body 末尾才把它换成英文或繁体。
 * 浏览器不保证等到那一步才开始画，于是英文访客会先看到一屏简体再跳成英文。
 *
 * 这里在任何一次绘制之前判断访客要的是哪一门语言：是简体就什么都不做，
 * 页面本来就是对的，一帧都不必等；不是简体才给 <html> 加个类，由 CSS 把正文
 * 藏到 i18n.js 换完为止。
 *
 * 判断规则要和 i18n.js 的 detectLang 一致。真正的语言仍由 i18n.js 决定——
 * 那边知道每页支持哪几门语言，这里不知道。这里判断错了，代价也只是白挡一下。
 */
(function () {
  'use strict';
  var root = document.documentElement;

  function pref() {
    try {
      var s = localStorage.getItem('mirror-lang');
      if (s) return s;
    } catch (e) {}
    var n = (navigator && navigator.language) || '';
    if (/^en/i.test(n)) return 'en';
    if (/(^|-)(tw|hk|mo|hant)/i.test(n)) return 'zh-tw';
    return 'zh-cn';
  }

  // 页面自己也用得到，不必两边各判一次
  window.MIRROR_LANG_PREF = pref();

  if (window.MIRROR_LANG_PREF === 'zh-cn') return;
  root.className += (root.className ? ' ' : '') + 'lang-swap';

  // i18n.js 没跑起来（网络断了、脚本 404、旧浏览器报错）时，页面不能一直空着。
  // 到点自己揭开，访客看到的是简体原文，好过一片空白。
  setTimeout(function () { root.classList.remove('lang-swap'); }, 1500);
})();
