const fs = require('fs');
const path = require('path');

const dir = process.argv[2] || 'site';

const COMMON = (() => {
  const f = path.join(dir, 'assets', 'strings.js');
  if (!fs.existsSync(f)) return {};
  const w = {};
  new Function('window', fs.readFileSync(f, 'utf8'))(w);
  return w.MIRROR_I18N_COMMON || {};
})();
const LANGS = ['zh-tw', 'en'];
let bad = 0;

for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
  const s = fs.readFileSync(path.join(dir, f), 'utf8');
  const keysInPage = [...s.matchAll(/data-i18n(?:-html|-href)?="([A-Za-z0-9_]+)"/g)];
  const keysInScript = [...s.matchAll(/\bt\(["']([A-Za-z0-9_]+)["']\)/g)];
  const strings = s.match(/<div id="strings"[\s\S]*?<\/div>/);
  if (strings) {
    const inStrings = new Set(
      [...strings[0].matchAll(/data-i18n="([A-Za-z0-9_]+)"/g)].map(x => x[1]));
    for (const [, key] of keysInScript) {
      if (!inStrings.has(key)) {
        console.error(`!!! ${f}: t("${key}") 无法获取，#strings 未包含这个 key`);
        bad++;
      }
    }
    for (const [, pre] of s.matchAll(/\bt\(["']([A-Za-z0-9_]+_)["']\s*\+/g)) {
      const all = new Set([...s.matchAll(
        new RegExp('data-i18n="(' + pre + '[A-Za-z0-9_]+)"', 'g'))].map(x => x[1]));
      for (const k of all) {
        if (!inStrings.has(k)) {
          console.error(`!!! ${f}: ${k} 只在正文里，t("${pre}...") 无法获取它`);
          bad++;
        }
      }
    }
  }
  const m = s.match(/window\.MIRROR_I18N = (\{[\s\S]*?\n\};)/);
  if (!m) {
    const own = [...keysInPage, ...keysInScript].map(x => x[1]);
    const missing = own.filter(k => !LANGS.every(l => COMMON[l] && k in COMMON[l]));
    if (missing.length) {
      console.error(`!!! ${f}: 用了 ${missing.join(', ')}，但页面没有 i18n 表，` +
                    `strings.js 里也没有`);
      bad++;
    } else if (own.length) {
      console.log(`  ${f}: ${own.length} key 全部来自 strings.js，无需页面表`);
    }
    continue;
  }

  let T;
  try {
    T = eval('(' + m[1].replace(/;$/, '') + ')');
  } catch (e) {
    console.error(`!!! ${f}: i18n 表解析失败： ${e.message}`);
    bad++;
    continue;
  }

  const hadOwn = Object.fromEntries(LANGS.map(l => [l, !!T[l]]));

  for (const lang of Object.keys(COMMON)) {
    T[lang] = Object.assign({}, COMMON[lang], T[lang] || {});
  }

  const keys = new Set([...keysInPage, ...keysInScript].map(x => x[1]));

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
    if (!hadOwn[lang]) {
      console.error(`!!! ${f}: 缺少 ${lang} 的表`);
      bad++;
      continue;
    }
  }
  {
    const cn = T['zh-cn'] || {};
    const miss = [...new Set(keysInScript.map(x => x[1]))]
      .filter(k => !(k in cn) && !(k in (COMMON['zh-cn'] || {})));
    if (miss.length) {
      console.error(`!!! ${f} [zh-cn] 脚本可取得但表中缺少： ${miss.join(', ')}`);
      bad++;
    }
  }
  for (const lang of Object.keys(T).filter(l => l !== 'zh-cn')) {
    const miss = [...keys].filter(k => !(k in T[lang]));
    if (miss.length) {
      console.error(`!!! ${f} [${lang}] 缺少翻译： ${miss.join(', ')}`);
      bad++;
    }
  }
  console.log(`  ${f}: ${keys.size} key × ${Object.keys(T).length} 种语言`);
}

process.exit(bad ? 1 : 0);
