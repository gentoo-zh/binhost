/* Helpers shared by the pages that build rows in JavaScript.
 *
 * These lived in packages.html and _app.html as two copies. esc() was identical,
 * human() was not: one guarded a zero and stopped at G, the other did neither and
 * went to T. Two byte formatters on one site is the kind of difference nobody
 * notices until the numbers disagree. */

/* Names come from the ebuild's Manifest and from paths in the URL, neither of
   which we control, so anything going into innerHTML goes through here. */
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

/* Zero reads as an empty cell rather than "0 B": a package with no size is one
   we have no figure for, not one that is empty. Up to T because the distfiles
   tree is already tens of gigabytes. */
function human(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  var unit = ["K", "M", "G", "T"];
  var i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < unit.length - 1);
  return n.toFixed(n < 10 ? 1 : 0) + " " + unit[i];
}

/* 顶栏是 sticky 的，表头也是。表头的 top 得正好等于顶栏的高度，否则要么滚到
   顶栏底下、要么和它之间露出一条缝。顶栏在窄屏会折成两行，高度不是一个常数，
   所以量出来写进 --nav-h，交给 CSS 用。 */
(function () {
  var nav = document.querySelector('.nav');
  if (!nav) return;
  function measure() {
    /* 向上取整。顶栏高度常带小数（96.98），截断会让表头压在顶栏底下一像素。 */
    var h = Math.ceil(nav.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--nav-h', h + 'px');
  }
  measure();
  /* 顶栏高度在首次测量之后还会变：i18n.js 把导航文字换成另一门语言，窄屏下
     可能因此多折一行；网页字体载入完也会变。实测过一次 90 与 97 的差——量早了
     七个像素，表头就有七个像素压在顶栏底下。
     ResizeObserver 默认看 content-box，顶栏的内边距变化它报不出来，要指明
     border-box。langchange 与 load 各自再补一次，不指望单一信号。 */
  if (window.ResizeObserver) {
    new ResizeObserver(measure).observe(nav, { box: 'border-box' });
  } else {
    window.addEventListener('resize', measure);
  }
  document.addEventListener('langchange', measure);
  window.addEventListener('load', measure);
})();
