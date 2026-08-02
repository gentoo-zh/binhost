(function () {
  'use strict';
  var root = document.documentElement;

  function read(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; }
  }

  var mode = read('mirror-theme') || 'system';
  if (mode !== 'light' && mode !== 'dark' && mode !== 'system') mode = 'system';
  root.setAttribute('data-theme-mode', mode);
  if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
  root.style.colorScheme = mode === 'system' ? 'light dark' : mode;

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

  setTimeout(function () { root.classList.remove('lang-swap'); }, 1500);
})();
