/* 配置块的两种写法：文件本身，和写出这个文件的命令。
 *
 * 两种都摆出来是一坨，读的人还得自己判断该抄哪一份，所以就地切换。
 *
 * 一页上几个块问的是同一件事：这个人是想照着改文件，还是想贴一段命令。所以
 * 点任何一个块的分页，整页一起换。
 *
 *   <div class="code">
 *     <div class="code-head">
 *       <div class="tabs" role="tablist">
 *         <button class="tab on" data-pane="manual">/etc/portage/make.conf</button>
 *         <button class="tab" data-pane="quick">快速配置</button>
 *       </div>
 *     </div>
 *     <pre data-pane="manual">...</pre>
 *     <pre data-pane="quick" hidden>...</pre>
 *   </div>
 */
(function () {
  var lists = document.querySelectorAll('.code .tabs');
  if (!lists.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  function show(pane) {
    each(document.querySelectorAll('.code .tabs .tab'), function (tab) {
      var on = tab.getAttribute('data-pane') === pane;
      tab.classList.toggle('on', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    each(document.querySelectorAll('.code pre[data-pane]'), function (pre) {
      pre.hidden = pre.getAttribute('data-pane') !== pane;
    });
  }

  each(document.querySelectorAll('.code .tabs .tab'), function (tab) {
    tab.addEventListener('click', function () {
      show(tab.getAttribute('data-pane'));
    });
  });
})();
