// Validate each page's i18n table: that it parses, and that it covers every key
// the page uses. One misplaced quote in the table takes language switching off
// the page entirely while the page itself still looks fine.
const fs = require('fs');
const path = require('path');

const dir = process.argv[2] || 'site';

// The engine merges the shared strings with the page table, so the check has to
// merge them the same way or every page reads as missing the nav and footer
// translations.
const COMMON = (() => {
  const f = path.join(dir, 'assets', 'strings.js');
  if (!fs.existsSync(f)) return {};
  const w = {};
  new Function('window', fs.readFileSync(f, 'utf8'))(w);
  return w.MIRROR_I18N_COMMON || {};
})();
// The set of languages is fixed. A missing one means the table was deleted or
// broken, which must not pass as having no table at all.
const LANGS = ['zh-tw', 'en'];
let bad = 0;

for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
  const s = fs.readFileSync(path.join(dir, f), 'utf8');
  // Underscores have to be included: keys like why_prebuilt used to fall
  // outside the character class entirely.
  const keysInPage = [...s.matchAll(/data-i18n(?:-html)?="([A-Za-z0-9_]+)"/g)];
  // Keys the script takes through t("...") have no data-i18n on the page, so
  // scanning attributes alone does not see them.
  const keysInScript = [...s.matchAll(/\bt\("([A-Za-z0-9_]+)"\)/g)];
    // t() on the page looks for keys only inside #strings. A data-i18n placed
    // in the body, as in the legend, is invisible to it -- the two serve
    // different purposes: one lets applyLang swap the text, the other supplies
    // strings to dynamically generated rows. Deleting the second as a duplicate
    // makes hundreds of rows show the key itself, in all three languages, which
    // is easy to miss when scanning the page.
    const strings = s.match(/<div id="strings"[\s\S]*?<\/div>/);
    if (strings) {
      const inStrings = new Set(
        [...strings[0].matchAll(/data-i18n="([A-Za-z0-9_]+)"/g)].map(x => x[1]));
      for (const [, key] of keysInScript) {
        if (!inStrings.has(key)) {
          console.error(`!!! ${f}: t("${key}") 取不到，#strings 里没有这个 key`);
          bad++;
        }
      }
      // For keys built up as t("why_" + r.why): every key with that prefix
      // appearing on the page has to be in there
      for (const [, pre] of s.matchAll(/\bt\("([A-Za-z0-9_]+_)"\s*\+/g)) {
        const all = new Set([...s.matchAll(
          new RegExp('data-i18n="(' + pre + '[A-Za-z0-9_]+)"', 'g'))].map(x => x[1]));
        for (const k of all) {
          if (!inStrings.has(k)) {
            console.error(`!!! ${f}: ${k} 只在正文里，t("${pre}...") 取不到它`);
            bad++;
          }
        }
      }
    }
  const m = s.match(/window\.MIRROR_I18N = (\{[\s\S]*?\n\};)/);
  if (!m) {
    // data-i18n on the page with no table means the whole block was deleted.
    // This used to continue, and CI stayed green.
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

  // The page table overrides the shared strings, as the engine does
  for (const lang of Object.keys(COMMON)) {
    T[lang] = Object.assign({}, COMMON[lang], T[lang] || {});
  }

  const keys = new Set([...keysInPage, ...keysInScript].map(x => x[1]));

  // Keys built up as t("why_" + r.why) cannot be listed by static scanning. Once

  // a prefix appears in the table, every language must carry it; one missing
  // shows the untranslated text when the language is switched.

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
