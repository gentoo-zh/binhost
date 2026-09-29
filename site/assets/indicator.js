// The sliding selection indicator of S2 SegmentedControl and Tabs (@react-spectrum/s2 1.7.1
// SegmentedControl.tsx:113-145, Tabs.tsx:373-378). Each segmented track (.seg) and tab row (.mode-pick)
// gets one indicator element that the stylesheet moves to the selected item: the outlined pill of a
// segmented control, the 2px bar under a tab. Selection stays where the picker scripts put it (the item's
// "on" class); this script only follows it, so any script that changes the selection, a translated label,
// a late count, a font swap or a resize moves the indicator with it. Without scripts the selected item
// paints itself, and the stylesheet draws no indicator until the first position is known.
(function () {
  'use strict';

  var KINDS = [
    { track: '.seg', item: 'button', cls: 'seg-ind' },
    { track: '.mode-pick', item: '.mode', cls: 'tab-ind' },
  ];

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  function selected(track, item) {
    return Array.prototype.filter.call(track.querySelectorAll(item), function (el) {
      return el.parentNode === track && el.classList.contains('on');
    })[0] || null;
  }

  // Offsets are relative to the track, which is the indicator's containing block. The hidden attribute is
  // written only when it changes: setting it to the value it holds still queues a mutation, and a track in a
  // hidden pane would then schedule another frame on every frame.
  function place(track, item, ind) {
    var on = selected(track, item);
    if (!on || !on.offsetWidth) {
      if (!ind.hidden) ind.hidden = true;
      return;
    }
    if (ind.hidden) ind.hidden = false;
    ind.style.setProperty('--ind-x', on.offsetLeft + 'px');
    ind.style.setProperty('--ind-y', on.offsetTop + 'px');
    ind.style.setProperty('--ind-w', on.offsetWidth + 'px');
    ind.style.setProperty('--ind-h', on.offsetHeight + 'px');
  }

  function attach(track, kind) {
    if (track.hasAttribute('data-ind')) return;
    var ind = document.createElement('span');
    ind.className = kind.cls;
    ind.setAttribute('aria-hidden', 'true');
    ind.hidden = true;
    track.insertBefore(ind, track.firstChild);
    track.setAttribute('data-ind', '');

    var queued = false;
    function update() {
      queued = false;
      place(track, kind.item, ind);
    }
    function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(update);
    }

    update();
    // The first position is placed without motion; only later moves slide.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { track.setAttribute('data-ind-ready', ''); });
    });

    // The indicator's own attributes never move it, so their mutations are ignored.
    function mutated(records) {
      if (!records || Array.prototype.some.call(records, function (r) { return r.target !== ind; })) schedule();
    }
    if (typeof MutationObserver === 'function') {
      new MutationObserver(mutated).observe(track, {
        subtree: true, childList: true, characterData: true, attributes: true,
        attributeFilter: ['class', 'aria-pressed', 'hidden'],
      });
    }
    if (typeof ResizeObserver === 'function') {
      var ro = new ResizeObserver(schedule);
      ro.observe(track);
      each(track.children, function (c) { ro.observe(c); });
    }
    window.addEventListener('resize', schedule);
    document.addEventListener('langchange', schedule);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
    return { update: update, indicator: ind };
  }

  function init(root) {
    var out = [];
    KINDS.forEach(function (kind) {
      each((root || document).querySelectorAll(kind.track), function (track) {
        var a = attach(track, kind);
        if (a) out.push(a);
      });
    });
    return out;
  }

  if (typeof window !== 'undefined') window.SelectionIndicator = { init: init, place: place };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); });
  else init();
})();
