// The docs shell: the "On this page" outline, its section picker in the top bar below 1024px, and the
// phone page menu. The outline and the picker are built from the h2s in main; without the script the
// page content is complete and the sidebar still lists every page. Sections are listed only there, never
// in the sidebar, as on the React Spectrum docs.
(function () {
  'use strict';
  var root = document.documentElement;

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    var main = document.querySelector('main');
    var side = document.querySelector('.sidebar');
    var toc = document.querySelector('.toc');
    var list = toc && toc.querySelector('.toc-list');
    var toggle = document.querySelector('.nav-toggle');
    if (!main || !side) return;

    var heads = Array.prototype.slice.call(main.querySelectorAll('h2'));
    // Two headings can mint the same id (the same data-i18n key, or the same fallback text), and a
    // duplicate id breaks both the anchor and whichever link finds the element first, so every
    // minted id is checked against the ones already on the page and suffixed until it is unique.
    var usedIds = {};
    heads.forEach(function (h) { if (h.id) usedIds[h.id] = true; });
    heads.forEach(function (h, i) {
      if (h.id) return;
      var base = (h.dataset && h.dataset.i18n) || ('section-' + (i + 1));
      var id = base, n = 2;
      while (usedIds[id]) { id = base + '-' + n; n += 1; }
      usedIds[id] = true;
      h.id = id;
    });

    var links = [];
    function item(ul, cls, h) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.className = cls;
      a.textContent = h.textContent.trim();
      li.appendChild(a);
      ul.appendChild(li);
      links.push({ a: a, h: h });
      return a;
    }
    // render-chrome.py marks the pages that have an outline, and the layout reserves its column only there.
    var outline = toc && list && toc.hasAttribute('data-outline') && heads.length > 1;
    if (outline) {
      heads.forEach(function (h) { item(list, 'toc-link', h); });
      toc.hidden = false;
    }

    // Below 1024px the outline column goes and the top bar carries the docs' section picker instead
    // (measured on react-spectrum.adobe.com at 1023, 768 and 390, 2026-09-29): a quiet 40px button naming the
    // section being read, the page title above the first section, centred in the bar, opening a popover that
    // lists the title and every section. site.css shows it only at those widths and fades it in with scrolling.
    var pick = null, pickBtn = null, pickLabel = null, pickMenu = null, title = main.querySelector('h1');
    var nav = document.querySelector('.nav');
    if (outline && nav) {
      if (title && !title.id) title.id = 'top';
      pick = document.createElement('div');
      pick.className = 'toc-pick';
      pickBtn = document.createElement('button');
      pickBtn.type = 'button';
      pickBtn.className = 'toc-pick-btn';
      pickBtn.id = 'toc-pick-btn';
      pickBtn.setAttribute('aria-expanded', 'false');
      pickBtn.setAttribute('aria-controls', 'toc-menu');
      pickBtn.setAttribute('aria-labelledby', 'toc-title toc-pick-label');
      pickLabel = document.createElement('span');
      pickLabel.className = 'toc-pick-label';
      pickLabel.id = 'toc-pick-label';
      pickBtn.appendChild(pickLabel);
      // The S2 UI icon Chevron, turned to point down, as the docs draw the picker's chevron.
      pickBtn.insertAdjacentHTML('beforeend', '<svg class="toc-pick-chevron" viewBox="0 0 10 10" aria-hidden="true"><path fill="currentColor" d="M7.965 5.178C7.978 5.118 8 5.061 8 5s-.021-.118-.034-.178c-.01-.05-.01-.102-.03-.15-.023-.058-.068-.107-.104-.16-.03-.042-.047-.09-.084-.127l-.004-.003-.003-.004L3.615.303a.875.875 0 1 0-1.23 1.244L5.88 5 2.385 8.453a.875.875 0 1 0 1.23 1.244L7.74 5.622l.003-.004.004-.003c.037-.038.055-.085.084-.127.036-.053.08-.102.104-.16.02-.048.02-.1.03-.15"/></svg>');
      pickMenu = document.createElement('ul');
      pickMenu.className = 'menu toc-menu';
      pickMenu.id = 'toc-menu';
      pickMenu.setAttribute('aria-labelledby', 'toc-title');
      pickMenu.hidden = true;
      if (title) item(pickMenu, 'menu-item', title);
      heads.forEach(function (h) { item(pickMenu, 'menu-item', h); });
      pick.appendChild(pickBtn);
      pick.appendChild(pickMenu);
      nav.appendChild(pick);
    }

    // A heading inside a hidden tab pane (mode-switch.js) has no box: its entries are hidden until the pane
    // is shown, so the outline lists only the sections on screen.
    function rendered(h) { return h.getClientRects().length > 0; }
    function sync() {
      links.forEach(function (l) { l.a.parentNode.hidden = !rendered(l.h); });
      schedule();
    }

    function relabel() {
      links.forEach(function (l) { l.a.textContent = l.h.textContent.trim(); });
      schedule();
    }
    document.addEventListener('langchange', relabel);

    // The section being read is the last h2 above the top bar's edge, or at the page end the last visible one.
    var scheduled = false;
    function mark() {
      scheduled = false;
      var edge = (parseFloat(getComputedStyle(root).getPropertyValue('--nav-h')) || 56) + 24;
      var bottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      var here = null;
      heads.forEach(function (h) {
        if (!rendered(h)) return;
        var top = h.getBoundingClientRect().top;
        if (top <= edge || (bottom && top < window.innerHeight)) here = h;
      });
      // Above the first section the picker names the page, as the docs' picker does at the top.
      var at = here || (pick ? title : null);
      links.forEach(function (l) {
        if (l.h === at) l.a.setAttribute('aria-current', 'location');
        else l.a.removeAttribute('aria-current');
      });
      if (pickLabel) pickLabel.textContent = at ? at.textContent.trim() : '';
    }
    function schedule() {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(mark);
    }
    if (links.length) {
      window.addEventListener('scroll', schedule, { passive: true });
      window.addEventListener('resize', schedule);
      document.addEventListener('panechange', sync);
      sync();
      mark();
    }

    // The picker's popover: a click or Enter opens it with focus on the section being read; arrows, Home and
    // End move; Escape closes it and returns focus to the button; Tab, a link or a click outside closes it.
    // Focus moves without scrolling: the bar sits inside html's scroll-padding, so Chrome would scroll the page.
    if (pick) {
      var shown = function () {
        return Array.prototype.filter.call(pickMenu.querySelectorAll('a'), function (a) { return !a.parentNode.hidden; });
      };
      var focusAt = function (i) {
        var all = shown();
        if (all.length) all[((i % all.length) + all.length) % all.length].focus({ preventScroll: true });
      };
      var setPick = function (open) {
        pickMenu.hidden = !open;
        pickBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      pickBtn.addEventListener('click', function () {
        if (!pickMenu.hidden) { setPick(false); return; }
        setPick(true);
        var all = shown();
        var cur = pickMenu.querySelector('a[aria-current]');
        focusAt(Math.max(0, all.indexOf(cur)));
      });
      pickMenu.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('a')) setPick(false);
      });
      pickMenu.addEventListener('keydown', function (e) {
        var here = shown().indexOf(document.activeElement);
        if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(here + 1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(here - 1); }
        else if (e.key === 'Home') { e.preventDefault(); focusAt(0); }
        else if (e.key === 'End') { e.preventDefault(); focusAt(-1); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setPick(false); pickBtn.focus({ preventScroll: true }); }
        else if (e.key === 'Tab') setPick(false);
      });
      document.addEventListener('click', function (e) {
        if (!pickMenu.hidden && !pick.contains(e.target)) setPick(false);
      });
    }

    // Below 1024px the sidebar opens from the top bar's menu button; Escape, a link, an outside click or
    // focus moving past it closes it. The top bar stays visible above the menu, so focus may pass through it.
    if (!toggle) return;
    toggle.hidden = false;
    function setOpen(open) {
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) root.setAttribute('data-nav-open', '');
      else root.removeAttribute('data-nav-open');
    }
    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!root.hasAttribute('data-nav-open'));
    });
    side.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a')) setOpen(false);
    });
    document.addEventListener('click', function (e) {
      if (root.hasAttribute('data-nav-open') && !side.contains(e.target)) setOpen(false);
    });
    var bar = toggle.closest('.nav') || toggle;
    document.addEventListener('focusin', function (e) {
      if (root.hasAttribute('data-nav-open') && !side.contains(e.target) && !bar.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !root.hasAttribute('data-nav-open')) return;
      setOpen(false);
      toggle.focus();
    });
  });
})();
