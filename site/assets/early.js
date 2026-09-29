(function () {
  'use strict';
  var root = document.documentElement;

  function read(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; }
  }

  // With scripts the phone sidebar folds into the menu button; without them it stays above main.
  root.setAttribute('data-js', '');

  // The page scripts set their saved choices (source, channel, tab) at the end of the body, possibly after
  // a first paint. data-settling holds transitions off until two frames after DOMContentLoaded, so that
  // setup lands at once and only the reader's own actions animate.
  root.setAttribute('data-settling', '');
  document.addEventListener('DOMContentLoaded', function () {
    var raf = window.requestAnimationFrame || function (f) { return setTimeout(f, 16); };
    raf(function () { raf(function () { root.removeAttribute('data-settling'); }); });
  });

  // A forced theme is stored; following the system stores nothing.
  var mode = read('mirror-theme');
  if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
  root.style.colorScheme = mode === 'light' || mode === 'dark' ? mode : 'light dark';

  // A ?lang= link picks the language before paint; i18n.js stores it.
  var q = /[?&]lang=(zh-cn|zh-tw|en)(?:&|$)/.exec((window.location && window.location.search) || '');
  var lang = q ? q[1] : read('mirror-lang');
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
