/* root 还是 sudo。
 *
 * 只有前缀这一个差别，因为写文件那几条用的是 tee 不是 cat：sudo cat > /etc/x
 * 的重导向是以你自己的身份做的，写不进去，而 sudo tee 可以。两种模式因此共用
 * 同一条命令，切换只是加不加 sudo。
 *
 * 提示符跟着换，# 是 root，$ 是普通用户。它是伪元素，不进 DOM 文本，所以复制
 * 不会把提示符带走；sudo 是命令的一部分，必须在文本里。
 *
 * 整页一起换：一个人有没有 sudo，对每一条命令都是同一个答案。
 */
(function () {
  var picks = document.querySelectorAll('.opt-pick');
  if (!picks.length) return;

  function each(list, f) { Array.prototype.forEach.call(list, f); }

  function show(mode) {
    document.documentElement.setAttribute('data-sudo', mode);
    each(document.querySelectorAll('.opt-pick .opt'), function (btn) {
      var on = btn.getAttribute('data-sudo') === mode;
      btn.classList.toggle('on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    /* 用 hidden 藏不行：hidden 的文本照样在 textContent 里，复制会把看不见的
       sudo 一起带走。所以是真的把那段文字加进去或者拿掉。 */
    each(document.querySelectorAll('.code .sudo'), function (el) {
      el.textContent = mode === 'on' ? 'sudo ' : '';
      el.hidden = mode !== 'on';
    });
  }

  each(document.querySelectorAll('.opt-pick .opt'), function (btn) {
    btn.addEventListener('click', function () {
      show(btn.getAttribute('data-sudo'));
    });
  });

  show('off');
})();
