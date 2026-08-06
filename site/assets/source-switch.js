(function () {
  var groups = document.querySelectorAll('[data-src-switch]');
  if (!groups.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  var pickers = [];
  var picked = false;

  each(groups, function (group) {
    var name = group.getAttribute('data-src-switch');
    var kind = group.getAttribute('data-src-group') || 'mirror';
    var opts = group.querySelectorAll('.src-opt');
    if (!opts.length) return;

    function ordered(chosen) {
      var rest = Array.prototype.filter.call(opts, function (o) {
        return o !== chosen;
      });
      return [chosen].concat(rest).map(function (o) {
        return o.getAttribute('data-uri');
      }).join(' ');
    }

    function render(chosen) {
      var uri = chosen.getAttribute('data-uri');
      var groupList = group.getAttribute('data-src-list');

      each(opts, function (o) {
        o.classList.toggle('on', o === chosen);
        o.setAttribute('aria-pressed', o === chosen ? 'true' : 'false');
      });

      each(document.querySelectorAll('[data-src-slot="' + name + '"]'),
        function (slot) {
          var list = slot.getAttribute('data-src-list') || groupList;
          slot.textContent = list
            ? list.replace('%s', ordered(chosen))
            : uri + (slot.getAttribute('data-src-suffix') || '');
        });

      each(document.querySelectorAll('.copy-chip[data-src-copy="' + name + '"]'),
        function (chip) {
          chip.setAttribute('data-copy', groupList
            ? groupList.replace('%s', ordered(chosen))
            : uri + (chip.getAttribute('data-src-suffix') || ''));
        });
    }

    pickers.push({ kind: kind, opts: opts, render: render });

    each(opts, function (btn) {
      btn.addEventListener('click', function () {
        var uri = btn.getAttribute('data-uri');
        picked = true;
        each(pickers, function (p) {
          if (p.kind !== kind) return;
          var match = Array.prototype.filter.call(p.opts, function (o) {
            return o.getAttribute('data-uri') === uri;
          })[0];
          if (match) p.render(match);
        });
      });
    });
  });

  function defaultOpt(opts) {
    var lang = document.documentElement.getAttribute('data-lang');
    return Array.prototype.filter.call(opts, function (o) {
      var langs = (o.getAttribute('data-src-default') || '').split(' ');
      return langs.indexOf(lang) >= 0;
    })[0] || Array.prototype.filter.call(opts, function (o) {
      return o.classList.contains('on');
    })[0] || opts[0];
  }

  function renderDefaults() {
    each(pickers, function (p) { p.render(defaultOpt(p.opts)); });
  }

  renderDefaults();

  document.addEventListener('sourcechange', function () {
    each(pickers, function (p) {
      var chosen = Array.prototype.filter.call(p.opts, function (o) {
        return o.classList.contains('on');
      })[0];
      if (chosen) p.render(chosen);
    });
  });

  document.addEventListener('langchange', function () {
    if (!picked) renderDefaults();
  });
})();
