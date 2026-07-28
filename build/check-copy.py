#!/usr/bin/env python3
"""按站点的写作规范检查页面文案。

规范见 site/design.html 的「文字」一节。这里只查能机器判定的：禁止的句式、
禁止的词、标点。结构与因果那几条要人看。

检查两处，规则不同：

- 站点文案（正文加 i18n 表里的串）：全套规则，包括标点与排版
- 代码注释：只查口语词。注释里不该有「的话」「就行」这种说话腔，但破折号
  密度、省略号写法那几条是给正文定的，套到注释上只会制造噪音
"""

import pathlib
import re
import sys

PHRASES = [
    (r"不是[^。，]{1,20}而是", "否定式对比"),
    (r"與其說|与其说", "否定式对比"),
    (r"这不仅是|這不僅是", "伪广度"),
    (r"值得注意的是", "预告式套话"),
    (r"总的来说|總的來說|综上所述|綜上所述", "总结段"),
    (r"随着[^。]{0,12}的不断|隨著[^。]{0,12}的不斷", "套话开头"),
    (r"奠定了坚实|扮演着重要", "公文腔"),
    (r"[。！？]\s*(其实|說白了|说白了|坦白讲)", "口语开头"),
]

WORDS = [
    # startup jargon
    "赋能", "抓手", "闭环", "底层逻辑", "认知升级", "长期主义", "颗粒度",
    "护城河", "组合拳", "打法", "破圈", "沉淀", "生态位",
    # bureaucratic register
    "不断深化", "持续推动", "有力支撑", "彰显", "诠释", "擘画",
    "注入新的活力", "迈上新台阶",
    # additionally for the Traditional text
    "至关重要", "至關重要", "深入探讨", "深入探討", "版图", "版圖",
    # colloquial
    "的话", "的話", "就行", "拉下来", "拉下來", "装上", "裝上", "搞定",
    "直接跑", "直接给", "直接給", "白跑", "一下就",
    "写不了", "寫不了", "不能省", "读不了", "讀不了", "认不出", "認不出",
    "多半", "看一眼", "东西", "東西", "一眼", "没劲", "沒勁", "不划算",
    "省得", "免得", "干脆", "乾脆", "好几", "好幾", "一大堆", "没啥", "沒啥",
]

# Filler verbs have legitimate uses in technical writing, so report only where
# they are plainly redundant
FILLER = [
    (r"进行[了]?(构建|同步|下载|安装|验证|检查)", "「进行」多余"),
    (r"通过[^，。]{0,8}的方式", "「通过…的方式」空转"),
    (r"作为[^，。]{0,6}来说", "「作为…来说」空转"),
]


def visible_text(html):
    """Text a reader sees: the body plus the strings in the i18n tables.

    排除三处：<title> 里的分隔符是排版惯例；设计语言页的规则表本身要列出
    这些禁止项；代码块里是命令与配置，不是文案。
    """
    body = re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", html)
    body = re.sub(r"<title>[\s\S]*?</title>", "", body)
    body = re.sub(r'<table class="spec"[\s\S]*?</table>', "", body)
    # The design page lists disallowed phrasing as counter-examples; what sits
    # in rule-dont is those examples themselves
    body = re.sub(r'<[^>]*class="rule-dont"[^>]*>[\s\S]*?</[a-z]+>', "", body)
    body = re.sub(r"<pre[\s\S]*?</pre>", "", body)
    body = re.sub(r"<[^>]+>", " ", body)
    tables = "\n".join(re.findall(r"window\.MIRROR_I18N = \{[\s\S]*?\n\};", html))
    tables = re.sub(r"<[^>]+>", " ", tables)
    return body + "\n" + tables


# Only this set is checked in comments. Technical comments legitimately use
# words the full rules would flag, and applying all of them only trains people
# to ignore the warnings.
COLLOQUIAL = [
    "的话", "的話", "就行", "拉下来", "拉下來", "装上", "裝上", "搞定",
    "直接跑", "直接给", "直接給", "白跑", "白做", "一下就", "就这么", "就這麼",
    "写不了", "寫不了", "读不了", "讀不了", "认不出", "認不出",
    "一堆", "咋", "啥", "干活", "活干", "玩意", "省事", "靠谱", "靠譜",
    "拉倒", "压根", "壓根", "干脆", "乾脆", "老是", "半天",
    "多半", "看一眼", "东西", "東西", "没劲", "沒勁", "省得", "好几", "好幾",
    "一大堆", "没啥", "沒啥",
]

# How a comment starts, per file. The pattern is not anchored to the line start
# so a trailing comment counts too: `rm -f "${log}"  # 成功的不留` used to slip
# through, and that is where offhand wording collects.
COMMENT = {
    ".sh": r"#(.*)$",
    ".py": r"#(.*)$",
    ".js": r"//(.*)$",
    ".service": r"#(.*)$",
    ".timer": r"#(.*)$",
    ".conf": r"#(.*)$",
    ".inc": r"#(.*)$",
    ".md": None,          # prose, checked whole
}

# Files with no suffix that are still configuration with comments.
NO_SUFFIX = {"cron.d-binhost", "logrotate-binhost", "rsyncd.conf", "nftables.conf"}


def check_comments(root):
    """Colloquial words in code comments. The suffix decides how a comment
    starts."""
    bad = 0
    for f in sorted(pathlib.Path(root).rglob("*")):
        if not f.is_file() or ".git" in f.parts:
            continue
        if f.suffix in COMMENT:
            pat = COMMENT[f.suffix]
        elif f.name in NO_SUFFIX:
            pat = r"#(.*)$"
        else:
            continue
        # This script lists the words itself, so skip it
        if f.name == "check-copy.py":
            continue
        try:
            lines = f.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        hits = []
        for i, line in enumerate(lines, 1):
            if pat is None:                     # .md: the whole line is prose
                texts = [line]
            else:
                m = re.search(pat, line)
                # Beyond comments, Chinese strings printed for people are checked
                # too: alerts and logs are text a user reads. Both quote styles:
                # assets/strings.js writes every user-visible string in single
                # quotes, so a double-quote-only pattern covered none of it.
                texts = [m.group(1)] if m else (
                    re.findall(r'"([^"]*[\u4e00-\u9fff][^"]*)"', line)
                    + re.findall(r"'([^']*[\u4e00-\u9fff][^']*)'", line))
            for chunk in texts:
                for w in COLLOQUIAL:
                    if w in chunk:
                        hits.append(f"{i}: 口语词「{w}」  {line.strip()[:60]}")
        if hits:
            bad += 1
            print(f"!!! {f}")
            for h in hits:
                print(f"      {h}")
    return bad


def main(dirname):
    bad = 0
    for f in sorted(pathlib.Path(dirname).glob("*.html")):
        html = f.read_text()
        text = visible_text(html)
        hits = []

        for pat, why in PHRASES:
            for m in re.finditer(pat, text):
                hits.append(f"{why}: {m.group(0).strip()[:26]}")
        for w in WORDS:
            if w in text:
                hits.append(f"禁止词: {w}")
        for pat, why in FILLER:
            for m in re.finditer(pat, text):
                hits.append(f"{why}: {m.group(0)[:20]}")

        # At most one em dash per thousand characters
        chars = len(re.sub(r"\s", "", text))
        dashes = text.count("——")
        if chars and dashes > max(1, chars // 1000):
            hits.append(f"破折号 {dashes} 处，{chars} 字，超过每千字 1 次")
        # Chinese text only. In English an em dash with spaces is normal.
        for line in text.split("\n"):
            if re.search(r"[\u4e00-\u9fff]", line) and re.search(r"\S — \S", line):
                hits.append("中文里出现 em dash 加空格，改用全角——")
                break
        if "..." in text:
            hits.append("省略号写成了三个点，改用……")
        if re.search(r"[\U0001F300-\U0001FAFF✨❤]", text):
            hits.append("出现 emoji")

        if hits:
            bad += 1
            print(f"!!! {f.name}")
            for h in sorted(set(hits)):
                print(f"      {h}")
        else:
            print(f"  {f.name}: ok")

    bad += check_comments(pathlib.Path(dirname).parent)
    if not bad:
        print("  代码注释: 无口语词")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
