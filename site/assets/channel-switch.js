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
        detail: { channel: channel, path: path, status: status },
      }));
    }

    each(opts, function (option) {
      option.addEventListener('click', function () { render(option); });
    });

    var initial = Array.prototype.filter.call(opts, function (option) {
      return option.classList.contains('on');
    })[0] || opts[0];
    render(initial);
  });
})();
