
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function human(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  var unit = ["K", "M", "G", "T"];
  var i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < unit.length - 1);
  return n.toFixed(n < 10 ? 1 : 0) + " " + unit[i];
}

(function () {
  var nav = document.querySelector('.nav');
  if (!nav) return;
  function measure() {
    var h = Math.ceil(nav.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--nav-h', h + 'px');
  }
  measure();
  if (window.ResizeObserver) {
    new ResizeObserver(measure).observe(nav, { box: 'border-box' });
  } else {
    window.addEventListener('resize', measure);
  }
  document.addEventListener('langchange', measure);
  window.addEventListener('load', measure);
})();
