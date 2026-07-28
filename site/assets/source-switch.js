/* Mirror pickers.
 *
 * Two of them, because portage reads the two settings differently:
 *
 *   binrepos.conf sync-uri takes exactly one address. portage runs it through
 *   _normalize_uri(), which strips a trailing slash and never splits on
 *   whitespace, so the reader has to choose. The picker writes the chosen one.
 *
 *   GENTOO_MIRRORS is a list portage splits and tries in the order given
 *   (random.shuffle applies to thirdpartymirrors, the mirror:// scheme in
 *   SRC_URI, not to this). Dropping the others would throw away the fallback,
 *   so every mirror stays listed and the picker only decides which goes first.
 *
 * A picker is <div class="src-pick" data-src-switch="NAME"> holding one button
 * per mirror with data-uri. It writes [data-src-slot="NAME"] and refreshes the
 * copy payloads. Adding a mirror is one button.
 */
(function () {
  var groups = document.querySelectorAll('[data-src-switch]');
  if (!groups.length) return;

  /* Copy payloads are read off the rendered block rather than kept in a
     data-copy of their own. Two copies of one config drift as soon as either is
     edited, and the copy nobody reads is the one users paste. Prompts are left
     out: they mark who runs the command and the page already makes them
     unselectable. */
  function payload(pre) {
    var clone = pre.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll('.prompt'), function (p) {
      p.parentNode.removeChild(p);
    });
    return clone.textContent.replace(/\s+$/, '');
  }

  function refreshCopy(group) {
    /* Only the block directly below this picker. Searching the parent for any
       .code reaches the wrong one when the picker sits in the page body rather
       than inside a step -- the heading's picker would have rewritten step 1's
       copy payload, which is a shell command, not a config. */
    var code = group.nextElementSibling;
    if (!code || !code.classList.contains('code')) return;
    var pre = code.querySelector('pre');
    var chip = code.querySelector('.copy-chip');
    if (pre && chip) chip.setAttribute('data-copy', payload(pre));
  }

  Array.prototype.forEach.call(groups, function (group) {
    var name = group.getAttribute('data-src-switch');
    var opts = group.querySelectorAll('.src-opt');
    if (!opts.length) return;

    function value(chosen) {
      if (group.hasAttribute('data-src-list')) {
        /* Chosen first, the rest after it in the order they are written. */
        var rest = Array.prototype.filter.call(opts, function (o) { return o !== chosen; });
        var all = [chosen].concat(rest).map(function (o) { return o.getAttribute('data-uri'); });
        return group.getAttribute('data-src-list').replace('%s', all.join(' '));
      }
      return chosen.getAttribute('data-uri');
    }

    function select(chosen) {
      var v = value(chosen);

      Array.prototype.forEach.call(opts, function (o) {
        o.classList.toggle('on', o === chosen);
        o.setAttribute('aria-pressed', o === chosen ? 'true' : 'false');
      });

      Array.prototype.forEach.call(
        document.querySelectorAll('[data-src-slot="' + name + '"]'),
        function (slot) { slot.textContent = v; });

      /* The bare address, for the heading that shows nothing else. */
      Array.prototype.forEach.call(
        document.querySelectorAll('.copy-chip[data-src-copy="' + name + '"]'),
        function (chip) { chip.setAttribute('data-copy', v); });

      refreshCopy(group);
    }

    Array.prototype.forEach.call(opts, function (btn) {
      btn.addEventListener('click', function () { select(btn); });
    });

    /* Fill the copy payloads once at load. Without this the chips carry no
       data-copy until something is clicked, and the copy handler would put the
       string "null" on the clipboard. */
    select(group.querySelector('.src-opt.on') || opts[0]);
  });
})();
