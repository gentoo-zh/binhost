/* Mirror pickers.
 *
 * A page carries several of them, but they all ask the same thing: which
 * mirror. Left independent they hand out two contradicting configs at once,
 * so clicking any one of them switches the whole page.
 *
 * The two settings differ in what they accept, which is why a choice renders
 * two ways:
 *
 *   binrepos.conf sync-uri takes exactly one address. portage runs it through
 *   _normalize_uri(), which strips a trailing slash and never splits on
 *   whitespace, so the reader has to choose. A slot writes the chosen one,
 *   plus data-src-suffix if the setting wants a path under it.
 *
 *   GENTOO_MIRRORS is a list portage splits and tries in the order given
 *   (random.shuffle applies to thirdpartymirrors, the mirror:// scheme in
 *   SRC_URI, not to this). Dropping the others would throw away the fallback,
 *   so a slot carrying data-src-list keeps every mirror and only moves the
 *   chosen one to the front. %s is where the addresses go.
 *
 * A picker is <div class="src-pick" data-src-switch="NAME"> holding one button
 * per mirror with data-uri. It writes [data-src-slot="NAME"].
 * Adding a mirror is one button per picker.
 *
 * data-src-default 列出该镜像适合当默认的语言。教育网联合镜像站在中国大陆境内
 * 快，繁体与英文界面的读者多在境外，所以默认跟着界面语言走。读者自己点过之后
 * 就不再跟了，那是明确的选择。
 */
(function () {
  var groups = document.querySelectorAll('[data-src-switch]');
  if (!groups.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  var pickers = [];
  var picked = false;

  each(groups, function (group) {
    var name = group.getAttribute('data-src-switch');
    /* 页面上不止一种选择器：选镜像的，和选下载工具的。同步只在同一类里做，
       否则点了 wget 会去别的选择器里找一个叫 wget 的镜像。 */
    var kind = group.getAttribute('data-src-group') || 'mirror';
    var opts = group.querySelectorAll('.src-opt');
    if (!opts.length) return;

    /* Chosen first, the rest after it in the order they are written. */
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

      /* The bare address, for the heading that shows nothing else. */
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

  /* 当前语言的默认镜像，没有标时用 markup 里写死的那个。 */
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

  /* 载入时先渲染一次：markup 里写死的是其中一个镜像，不渲染时另一个选择器
     的按钮不会被标上，槽位也停在写死的那份。 */
  renderDefaults();

  /* i18n.js 在本脚本之前跑，它开头那次 applyLang 广播的 langchange 收不到，
     所以初次渲染自己读 data-lang，这里只管后续切换。 */
  document.addEventListener('langchange', function () {
    if (!picked) renderDefaults();
  });
})();
