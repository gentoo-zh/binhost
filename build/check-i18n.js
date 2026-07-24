// 校验每个页面的 i18n 表：能否解析，以及是否覆盖了页面用到的全部 key。
// 表里一个引号写错，整个页面的语言切换就没了，而页面本身看起来正常。
const fs = require('fs');
const path = require('path');

const dir = process.argv[2] || 'site';

// 引擎把共用串和页面表合起来用，检查也得按同样的方式合，
// 否则每页都会被报成缺导航和页脚的翻译。
const COMMON = (() => {
  const f = path.join(dir, 'assets', 'strings.js');
  if (!fs.existsSync(f)) return {};
  const w = {};
  new Function('window', fs.readFileSync(f, 'utf8'))(w);
  return w.MIRROR_I18N_COMMON || {};
})();
// 页面用哪几种语言是固定的。少一种就是表被删了或写坏了，不能当成「没有表」放过。
const LANGS = ['zh-tw', 'en'];
let bad = 0;

for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
  const s = fs.readFileSync(path.join(dir, f), 'utf8');
  // 下划线要收进来：why_prebuilt 这类 key 原来整个漏在字符类之外。
  const keysInPage = [...s.matchAll(/data-i18n(?:-html)?="([A-Za-z0-9_]+)"/g)];
  // 脚本里 t("...") 拿的 key 页面上没有 data-i18n，静态扫属性看不见。
  const keysInScript = [...s.matchAll(/\bt\("([A-Za-z0-9_]+)"\)/g)];
  const m = s.match(/window\.MIRROR_I18N = (\{[\s\S]*?\n\};)/);
  if (!m) {
    // 页面有 data-i18n 却没有表，说明整段被删掉了。原来这里直接 continue，
    // CI 照样绿。
    if (keysInPage.length) {
      console.error(`!!! ${f}: 有 ${keysInPage.length} 个 data-i18n 但找不到 i18n 表`);
      bad++;
    }
    continue;
  }

  let T;
  try {
    T = eval('(' + m[1].replace(/;$/, '') + ')');
  } catch (e) {
    console.error(`!!! ${f}: i18n 表解析失败: ${e.message}`);
    bad++;
    continue;
  }

  // 页面的表覆盖共用串，和引擎一致
  for (const lang of Object.keys(COMMON)) {
    T[lang] = Object.assign({}, COMMON[lang], T[lang] || {});
  }

  const keys = new Set([...keysInPage, ...keysInScript].map(x => x[1]));

  // t("why_" + r.why) 这种拼出来的 key，静态扫描给不出完整清单。表里出现了

  // 一个前缀，就要求所有语言都齐——少一个就是切换语言时露出原文。

  const prefixes = new Set();

  for (const lang of Object.keys(T)) {

    for (const k of Object.keys(T[lang])) {

      const i = k.indexOf('_');

      if (i > 0) prefixes.add(k.slice(0, i + 1));

    }

  }

  for (const pre of prefixes) {

    for (const lang of Object.keys(T)) {

      Object.keys(T[lang]).filter(k => k.startsWith(pre)).forEach(k => keys.add(k));

    }

  }
  for (const lang of LANGS) {
    if (!T[lang]) {
      console.error(`!!! ${f}: 缺少 ${lang} 的表`);
      bad++;
      continue;
    }
  }
  for (const lang of Object.keys(T)) {
    const miss = [...keys].filter(k => !(k in T[lang]));
    if (miss.length) {
      console.error(`!!! ${f} [${lang}] 缺少翻译: ${miss.join(', ')}`);
      bad++;
    }
  }
  console.log(`  ${f}: ${keys.size} key × ${Object.keys(T).length} 种语言`);
}

process.exit(bad ? 1 : 0);
