/* 手动配置 / 快速配置。
 *
 * 同一件事两种写法：一步步改文件，或者贴一段命令做完。两种都摆出来是一坨，
 * 读的人还得先判断哪一份是自己要的，所以放在大标题下面就地切换。
 *
 * 整页一起换：一个人是想照着改文件，还是想贴一段命令，对每一段都是同一个
 * 答案，分段记就成了 Distfiles 那半在快速、二进制包那半在手动。
 *
 *   <div class="mode-pick">
 *     <button class="mode on" data-pane="manual">手动配置</button>
 *     <button class="mode" data-pane="quick">快速配置</button>
 *   </div>
 *   <div data-pane="manual">...</div>
 *   <div data-pane="quick" hidden>...</div>
 */
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

  /* 载入时也走一遍。原来只在点击时才跑，markup 里漏写 hidden 的那一个就一直
     露在外面，而它管的块是藏着的。 */
  show('manual');
})();
