(function () {
  var btns = document.querySelectorAll('.code-head .sudo-btn');
  if (!btns.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

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
      show(btn.getAttribute('aria-pressed') !== 'true');
    });
  });

  show(false);
})();
