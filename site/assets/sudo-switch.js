// The sudo toggle of code blocks and install boxes. Commands are written with sudo, and that is also the markup
// without scripts; a reader who runs them as root turns it off. The choice holds on every page:
// mirror-sudo is "off" only after the reader turned it off and "on" after turning it back on; anything
// else, or storage that cannot be read, means on. "sudo " is a text node, so the copied command is the
// one on screen; the prompt is a pseudo-element and is never copied.
(function () {
  var btns = document.querySelectorAll('.code .sudo-btn, .install .sudo-btn');
  if (!btns.length) return;

  var KEY = 'mirror-sudo';
  function each(list, f) { Array.prototype.forEach.call(list, f); }
  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function remember(on) {
    try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (e) {}
  }

  function show(on) {
    document.documentElement.setAttribute('data-sudo', on ? 'on' : 'off');
    each(btns, function (btn) {
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    each(document.querySelectorAll('.code .sudo'), function (el) {
      el.textContent = on ? 'sudo ' : '';
      el.hidden = !on;
    });
  }

  each(btns, function (btn) {
    btn.addEventListener('click', function () {
      var on = btn.getAttribute('aria-pressed') !== 'true';
      remember(on);
      show(on);
    });
  });

  show(stored() !== 'off');
  // A page restored from the back-forward cache reads the choice again; another page may have changed it.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) show(stored() !== 'off');
  });
})();
