// Tabs that switch whole panes: each .mode button names a pane in data-pane, and every other element with
// that data-pane is shown only while its tab is selected. The tab marked .on in the markup is the initial
// one. A link to an anchor inside a pane (#desktop, a heading in it) opens that pane first. Without the
// script every pane the markup does not hide stays visible.
(function () {
  var picks = document.querySelectorAll('.mode-pick');
  if (!picks.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  function show(pane) {
    each(document.querySelectorAll('.mode-pick .mode'), function (btn) {
      var on = btn.getAttribute('data-pane') === pane;
      btn.classList.toggle('on', on);
      // A tab in a tablist states its selection with aria-selected and is the one stop in the tab order;
      // the arrow keys move between the tabs. Older markup marks the choice as a pressed button.
      if (btn.getAttribute('role') === 'tab') {
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
      } else {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    });
    each(document.querySelectorAll('[data-pane]'), function (el) {
      if (el.classList.contains('mode')) return;
      el.hidden = el.getAttribute('data-pane') !== pane;
    });
    document.dispatchEvent(new CustomEvent('panechange', { detail: pane }));
  }

  // The pane holding the element the URL fragment names, or null.
  function paneOfHash() {
    var id = (window.location && window.location.hash || '').slice(1);
    if (!id) return null;
    try { id = decodeURIComponent(id); } catch (e) { return null; }
    var el = document.getElementById(id);
    var pane = el && el.closest ? el.closest('[data-pane]:not(.mode)') : null;
    return pane ? { pane: pane.getAttribute('data-pane'), el: el } : null;
  }

  function follow() {
    var hit = paneOfHash();
    if (!hit) return false;
    show(hit.pane);
    if (hit.el.scrollIntoView) hit.el.scrollIntoView();
    return true;
  }

  each(document.querySelectorAll('.mode-pick .mode'), function (btn) {
    btn.addEventListener('click', function () {
      show(btn.getAttribute('data-pane'));
    });
  });
  each(document.querySelectorAll('.mode-pick[role="tablist"]'), function (list) {
    list.addEventListener('keydown', function (e) {
      var tabs = Array.prototype.slice.call(list.querySelectorAll('.mode'));
      var i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      var rtl = getComputedStyle(list).direction === 'rtl';
      var step = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[e.key];
      var j = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1
        : step ? (i + step + tabs.length) % tabs.length : -1;
      if (j < 0) return;
      e.preventDefault();
      tabs[j].focus();
      show(tabs[j].getAttribute('data-pane'));
    });
  });
  window.addEventListener('hashchange', follow);

  if (!follow()) {
    var first = document.querySelector('.mode-pick .mode.on') || document.querySelector('.mode-pick .mode');
    if (first) show(first.getAttribute('data-pane'));
  }
})();
