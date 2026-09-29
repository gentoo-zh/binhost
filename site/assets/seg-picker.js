// A SegmentedControl stays one row. S2 keeps SegmentedControl to a few short options and offers Picker for
// the rest, so when a .seg track's options do not fit on one row in the space its container gives it, the
// track is shown as an S2 Picker (@react-spectrum/s2 1.7.1 Picker.tsx): a field button naming the selected
// option, opening a ListBox of the same options with a checkmark on the selected one. The two views are one
// control. The segment buttons stay the source of truth: the Picker reads their labels and "on" class, and
// choosing an option clicks the matching segment, so every picker script (mirrors, channel, filters) keeps
// its state, storage and events. The choice is measured, not set by breakpoints: a ResizeObserver on the
// container compares the options' single-row width with the room, and the track only comes back once the
// room exceeds that width by HYST px, so a width at the boundary does not flicker. Without scripts the
// track stays and may wrap.
(function () {
  'use strict';

  var HYST = 16;
  // The site's Checkmark (the top-bar menus) and the S2 UI Chevron turned down (the docs' section picker).
  var CHECK = '<svg class="icon icon-sm menu-check" viewBox="0 0 20 20" aria-hidden="true"><path fill="currentColor" d="M7.864 15.734c-.222 0-.433-.098-.576-.27l-3.747-4.497c-.266-.319-.222-.792.096-1.057.317-.265.79-.223 1.056.096l3.154 3.786 7.44-9.469c.255-.326.728-.382 1.052-.127.326.256.383.728.127 1.053L8.454 15.447c-.14.179-.352.284-.579.287z"/></svg>';
  var CHEVRON = '<svg class="seg-pick-chevron" viewBox="0 0 10 10" aria-hidden="true"><path fill="currentColor" d="M7.965 5.178C7.978 5.118 8 5.061 8 5s-.021-.118-.034-.178c-.01-.05-.01-.102-.03-.15-.023-.058-.068-.107-.104-.16-.03-.042-.047-.09-.084-.127l-.004-.003-.003-.004L3.615.303a.875.875 0 1 0-1.23 1.244L5.88 5 2.385 8.453a.875.875 0 1 0 1.23 1.244L7.74 5.622l.003-.004.004-.003c.037-.038.055-.085.084-.127.036-.053.08-.102.104-.16.02-.048.02-.1.03-.15"/></svg>';
  // Kept 12px inside the window when deciding whether to flip, as the ContextualHelp popover (packages.html).
  var EDGE = 12;
  var count = 0;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  // Picker while the options need more than the room; back to segments only with HYST px to spare.
  function decide(picked, need, room) {
    if (!(room > 0)) return picked;
    return picked ? need > room - HYST : need > room;
  }

  function segButtons(seg) {
    return Array.prototype.filter.call(seg.children, function (c) { return c.tagName === 'BUTTON'; });
  }

  function text(el) { return (el.textContent || '').replace(/\s+/g, ' ').trim(); }

  // The options' width on one row: their own widths (they do not wrap inside) and the gaps between them.
  function need(seg) {
    var bs = segButtons(seg);
    var gap = parseFloat(getComputedStyle(seg).columnGap) || 0;
    var w = 0;
    bs.forEach(function (b) { w += b.offsetWidth; });
    return w + gap * Math.max(0, bs.length - 1);
  }

  // The container's content box: the most a track may take, on a row of its own if need be.
  function room(box) {
    var cs = getComputedStyle(box);
    return box.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
  }

  function attach(seg) {
    if (seg.hasAttribute('data-seg-picker') || !seg.parentNode) return null;
    seg.setAttribute('data-seg-picker', '');
    var box = seg.parentNode;
    var id = 'seg-pick-' + (++count);
    var group = seg.getAttribute('role') === 'group' ? seg : (seg.closest && seg.closest('[role="group"]'));
    var labelEl = group && group.querySelector ? group.querySelector('.src-label') : null;

    var wrap = document.createElement('span');
    wrap.className = 'seg-pick';
    wrap.classList.add('menu-wrap');
    wrap.hidden = true;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'seg-pick-btn';
    btn.setAttribute('aria-haspopup', 'listbox');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', id + '-list');
    var value = document.createElement('span');
    value.className = 'seg-pick-value';
    value.id = id + '-value';
    btn.appendChild(value);
    btn.insertAdjacentHTML('beforeend', CHEVRON);
    var list = document.createElement('div');
    list.className = 'seg-pick-menu';
    list.classList.add('menu');
    list.id = id + '-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.appendChild(btn);
    wrap.appendChild(list);
    box.insertBefore(wrap, seg.nextSibling);

    // The accessible name is the group's: its visible label when it has one, else its aria-label.
    if (labelEl) {
      if (!labelEl.id) labelEl.id = id + '-label';
      btn.setAttribute('aria-labelledby', labelEl.id + ' ' + value.id);
      list.setAttribute('aria-labelledby', labelEl.id);
    }

    var options = [];
    function sync() {
      var bs = segButtons(seg);
      if (!labelEl && group) {
        var name = group.getAttribute('aria-label') || '';
        btn.setAttribute('aria-label', name + (name ? ': ' : '') + text(bs.filter(function (b) { return b.classList.contains('on'); })[0] || bs[0] || seg));
        list.setAttribute('aria-label', name);
      }
      while (options.length > bs.length) list.removeChild(options.pop());
      bs.forEach(function (b, i) {
        var o = options[i];
        if (!o) {
          o = document.createElement('div');
          o.className = 'menu-item';
          o.setAttribute('role', 'option');
          o.setAttribute('tabindex', '-1');
          o.insertAdjacentHTML('beforeend', CHECK);
          var l = document.createElement('span');
          l.className = 'menu-label';
          o.appendChild(l);
          o.addEventListener('click', function () { choose(options.indexOf(o)); });
          list.appendChild(o);
          options.push(o);
        }
        var on = b.classList.contains('on');
        o.lastChild.textContent = text(b);
        // A segment's status mark (a mirror that is behind) and its tooltip carry over to the option.
        if (b.hasAttribute('data-behind')) o.setAttribute('data-behind', ''); else o.removeAttribute('data-behind');
        if (b.title) o.title = b.title; else o.removeAttribute('title');
        o.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) value.textContent = text(b);
      });
    }

    function isOpen() { return !list.hidden; }
    function setOpen(open) {
      list.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) return;
      // Below the field, or above it when the window has no room below and does above (Popover.tsx shouldFlip).
      var r = btn.getBoundingClientRect ? btn.getBoundingClientRect() : null;
      var h = list.offsetHeight || 0;
      var flip = r && h && r.bottom + h + EDGE > window.innerHeight && r.top - h - EDGE >= 0;
      if (flip) list.setAttribute('data-placement', 'top');
      else list.removeAttribute('data-placement');
    }
    function selectedIndex() {
      for (var i = 0; i < options.length; i++) if (options[i].getAttribute('aria-selected') === 'true') return i;
      return 0;
    }
    function focusAt(i) {
      if (!options.length) return;
      options[((i % options.length) + options.length) % options.length].focus({ preventScroll: true });
    }
    function open(at) {
      sync();
      setOpen(true);
      focusAt(at === undefined ? selectedIndex() : at);
    }
    function close(refocus) {
      setOpen(false);
      if (refocus) btn.focus({ preventScroll: true });
    }
    // Choosing an option is a click on its segment: the picker scripts do the rest.
    function choose(i) {
      var b = segButtons(seg)[i];
      if (b && !b.classList.contains('on')) b.click();
      sync();
      close(true);
    }

    btn.addEventListener('click', function () {
      if (isOpen()) close(false);
      else open();
    });
    btn.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        open();
      }
    });
    list.addEventListener('keydown', function (e) {
      var here = options.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(here + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(here - 1); }
      else if (e.key === 'Home') { e.preventDefault(); focusAt(0); }
      else if (e.key === 'End') { e.preventDefault(); focusAt(-1); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (here >= 0) choose(here); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
      else if (e.key === 'Tab') close(false);
      else if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // Type-ahead: the next option whose label starts with the key.
        var k = e.key.toLowerCase();
        for (var s = 1; s <= options.length; s++) {
          var j = (here + s) % options.length;
          if (text(options[j]).toLowerCase().indexOf(k) === 0) { focusAt(j); break; }
        }
      }
    });
    document.addEventListener('click', function (e) {
      if (isOpen() && !wrap.contains(e.target)) close(false);
    });

    var picked = false;
    function measure() {
      var next = decide(picked, need(seg), room(box));
      if (next === picked) return;
      picked = next;
      if (picked) {
        sync();
        seg.setAttribute('data-picked', '');
        wrap.hidden = false;
      } else {
        if (isOpen()) close(false);
        seg.removeAttribute('data-picked');
        wrap.hidden = true;
      }
    }

    var queued = false;
    function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; sync(); measure(); });
    }

    sync();
    measure();
    if (typeof MutationObserver === 'function') {
      new MutationObserver(schedule).observe(seg, {
        subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class'],
      });
    }
    if (typeof ResizeObserver === 'function') new ResizeObserver(schedule).observe(box);
    window.addEventListener('resize', schedule);
    document.addEventListener('langchange', schedule);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
    return { measure: measure, sync: sync, open: open, close: close, choose: choose,
      button: btn, list: list, wrap: wrap, isPicked: function () { return picked; } };
  }

  function init(root) {
    var out = [];
    each((root || document).querySelectorAll('.seg'), function (seg) {
      var a = attach(seg);
      if (a) out.push(a);
    });
    return out;
  }

  if (typeof window !== 'undefined') window.SegPicker = { init: init, decide: decide, HYST: HYST };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); });
  else init();
})();
