(function () {
  var groups = document.querySelectorAll('[data-channel-switch]');
  if (!groups.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  each(groups, function (group) {
    var opts = group.querySelectorAll('[data-channel]');
    if (!opts.length) return;

    function render(chosen) {
      var channel = chosen.getAttribute('data-channel');
      var path = chosen.getAttribute('data-path');
      var status = chosen.getAttribute('data-status');
      var packages = chosen.getAttribute('data-packages');
      var packageText = chosen.getAttribute('data-package-text');
      var depsText = chosen.getAttribute('data-deps-text');

      each(opts, function (option) {
        var active = option === chosen;
        option.classList.toggle('on', active);
        option.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      each(document.querySelectorAll('[data-channel-suffix]'), function (target) {
        target.setAttribute('data-src-suffix', path);
      });
      each(document.querySelectorAll('[data-channel-panel]'), function (panel) {
        panel.hidden = panel.getAttribute('data-channel-panel') !== channel;
      });

      document.dispatchEvent(new CustomEvent('sourcechange'));
      document.dispatchEvent(new CustomEvent('channelchange', {
        detail: {
          channel: channel,
          path: path,
          status: status,
          packages: packages,
          packageText: packageText,
          depsText: depsText,
        },
      }));
    }

    each(opts, function (option) {
      option.addEventListener('click', function () { render(option); });
      var count = option.querySelector('[data-channel-total]');
      var path = option.getAttribute('data-path');
      if (!count || !path) return;
      fetch(path + '/status.json')
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (status) {
          var total = status && (typeof status.overlay === 'number'
            ? status.overlay : status.packages);
          if (typeof total === 'number') count.textContent = '(' + total + ')';
        })
        .catch(function () {});
    });

    var initial = Array.prototype.filter.call(opts, function (option) {
      return option.classList.contains('on');
    })[0] || opts[0];
    render(initial);
  });
})();
