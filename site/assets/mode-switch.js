(function () {
  var picks = document.querySelectorAll('.mode-pick');
  if (!picks.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  function show(pane) {
    each(document.querySelectorAll('.mode-pick .mode'), function (btn) {
      var on = btn.getAttribute('data-pane') === pane;
      btn.classList.toggle('on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    each(document.querySelectorAll('[data-pane]'), function (el) {
      if (el.classList.contains('mode')) return;
      el.hidden = el.getAttribute('data-pane') !== pane;
    });
  }

  each(document.querySelectorAll('.mode-pick .mode'), function (btn) {
    btn.addEventListener('click', function () {
      show(btn.getAttribute('data-pane'));
    });
  });

  show('manual');
})();
