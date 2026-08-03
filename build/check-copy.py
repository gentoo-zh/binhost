#!/usr/bin/env python3

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
    "赋能", "抓手", "闭环", "底层逻辑", "认知升级", "长期主义", "颗粒度",
    "护城河", "组合拳", "打法", "破圈", "沉淀", "生态位",
    "不断深化", "持续推动", "有力支撑", "彰显", "诠释", "擘画",
    "注入新的活力", "迈上新台阶",
    "至关重要", "至關重要", "深入探讨", "深入探討", "版图", "版圖",
    "的话", "的話", "就行", "拉下来", "拉下來", "装上", "裝上", "搞定",
    "直接跑", "直接给", "直接給", "白跑", "一下就",
    "写不了", "寫不了", "不能省", "读不了", "讀不了", "认不出", "認不出",
    "多半", "看一眼", "东西", "東西", "一眼", "没劲", "沒勁", "不划算",
    "省得", "免得", "干脆", "乾脆", "好几", "好幾", "一大堆", "没啥", "沒啥",
]

FILLER = [
    (r"进行[了]?(构建|同步|下载|安装|验证|检查)", "「进行」多余"),
    (r"通过[^，。]{0,8}的方式", "「通过…的方式」空转"),
    (r"作为[^，。]{0,6}来说", "「作为…来说」空转"),
]


from html.parser import HTMLParser                        # noqa: E402

VISIBLE_ATTRS = {"title", "aria-label", "placeholder", "alt", "content", "value"}
SKIP_TAGS = {"script", "style"}
SPECIMEN = "data-specimen"


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.specimen = []

    def handle_starttag(self, tag, attrs):
        names = {n for n, _ in attrs}
        if tag in SKIP_TAGS or SPECIMEN in names:
            self.skip += 1
            self.specimen.append(tag)
            return
        if self.skip:
            self.specimen.append(tag)
            return
        for name, value in attrs:
            if name in VISIBLE_ATTRS and value:
                self.parts.append(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.specimen and self.specimen[-1] == tag:
            self.specimen.pop()
            if not self.specimen:
                self.skip = 0
            elif tag in SKIP_TAGS:
                self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html):
    """页面上人看得到的每一段文字：正文、属性、i18n 表里的串。

    此前用正则整段删掉 title、pre、table.spec、rule-dont，属性也完全不看，
    于是这些位置的用词从来没被检查过。
    """
    v = Visible()
    v.feed(html)
    tables = "\n".join(re.findall(r"window\.MIRROR_I18N = \{[\s\S]*?\n\};", html))
    tables = re.sub(r"<[^>]+>", " ", tables)
    return "\n".join(v.parts) + "\n" + tables


COLLOQUIAL = [
    "的话", "的話", "就行", "拉下来", "拉下來", "装上", "裝上", "搞定",
    "直接跑", "直接给", "直接給", "白跑", "白做", "一下就", "就这么", "就這麼",
    "写不了", "寫不了", "读不了", "讀不了", "认不出", "認不出",
    "一堆", "咋", "啥", "干活", "活干", "玩意", "省事", "靠谱", "靠譜",
    "拉倒", "压根", "壓根", "干脆", "乾脆", "老是", "半天",
    "多半", "看一眼", "东西", "東西", "没劲", "沒勁", "省得", "好几", "好幾",
    "一大堆", "没啥", "沒啥", "乱七八糟", "亂七八糟",
    "跑一次", "跑一遍", "重跑", "跑完", "跑起来", "跑起來", "跑不", "在跑",
    "没跑", "沒跑", "跑了", "跑过", "跑過", "装不上", "裝不上", "取不到",
    "读不出", "讀不出", "对不上", "對不上", "发不出", "發不出", "挡住", "擋住",
    "其实", "其實", "坦白讲", "坦白講",
]

COLLOQUIAL_EMIT = COLLOQUIAL + [
    "在跑", "没跑", "沒跑", "跑完", "跑起来", "跑起來", "没成", "沒成", "停了",
    "那一步", "这一步", "這一步", "弄", "搞", "整个儿",
    "没了", "沒了", "不可读", "不可讀", "直接删", "直接刪", "都还在", "都還在",
    "跟着换", "跟著換", "圈出来", "圈出來", "圈了出来", "圈了出來",
    "认得", "認得", "加进去", "加進去", "能读到", "能讀到", "失联", "失聯",
    "被删掉", "被刪掉", "才删", "才刪", "用完", "还没有", "還沒有",
    "报出来", "報出來", "留着", "留著", "拿到",
]

BARE_RUN = re.compile(r"跑(?![步道车馬马])")

COMMENT = {
    ".txt": r"#(.*)$",
    ".sh": r"#(.*)$",
    ".py": r"#(.*)$",
    ".js": r"//(.*)$",
    ".service": r"#(.*)$",
    ".timer": r"#(.*)$",
    ".conf": r"#(.*)$",
    ".inc": r"#(.*)$",
    ".md": None,
    ".yml": r"#(.*)$",
    ".yaml": r"#(.*)$",
    ".css": r"/\*(.*?)\*/",
    ".html": r"<!--(.*?)-->|/\*(.*?)\*/|(?<![:\w])//(.*)$",
}

NO_SUFFIX = {"cron.d-binhost", "logrotate-binhost", "rsyncd.conf",
             "nftables.conf", "robots.txt", "excluded.txt", "packages.txt"}


SELF = {"check-copy.py", "copy-fixtures.json", "test-check-copy.py"}

EMIT_SUFFIX = (".sh", ".py", ".js", ".yml", ".yaml", ".html", ".css", ".txt")
CJK = re.compile(r'[\u4e00-\u9fff]')

STRINGS = re.compile(
    r'"""([\s\S]*?)"""'
    r"|'''([\s\S]*?)'''"
    r"|`([^`]*)`"
    r'|"((?:[^"\\\n]|\\.)*)"'
    r"|'((?:[^'\\\n]|\\.)*)'",
)
HEREDOC = re.compile(
    r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[^\n]*\n([\s\S]*?)\n[ \t]*\1\b")


def emitted_chunks(text, suffix):
    out = []
    if suffix in (".sh", ".yml", ".yaml"):
        for m in HEREDOC.finditer(text):
            out.append((text[:m.start()].count("\n") + 1, m.group(2)))
    for m in STRINGS.finditer(text):
        s = next((g for g in m.groups() if g is not None), "")
        out.append((text[:m.start()].count("\n") + 1, s))
    return [(n, s) for n, s in out if CJK.search(s)]


def check_emitted(root):
    bad = 0
    for f in sorted(pathlib.Path(root).rglob("*")):
        if not f.is_file() or f.suffix not in EMIT_SUFFIX or f.name in SELF:
            continue
        if ".git" in f.parts:
            continue
        hits = []
        for line, chunk in emitted_chunks(f.read_text(errors="replace"), f.suffix):
            if BARE_RUN.search(chunk):
                hits.append(f"{line}: 应写成执行或运行，不用单字  {chunk.strip()[:60]}")
                continue
            for w in COLLOQUIAL_EMIT:
                if w in chunk:
                    hits.append(f"{line}: 口语词「{w}」  {chunk.strip()[:60]}")
                    break
        if hits:
            print(f"!!! {f}", file=sys.stderr)
            for h in hits:
                print(f"      {h}", file=sys.stderr)
            bad += 1
    return bad


BLOCK = re.compile(r"/\*([\s\S]*?)\*/|<!--([\s\S]*?)-->")
BLOCK_LANGS = {".css", ".html", ".js"}
QUOTED_SPAN = re.compile(
    r'"(?:[^"\\\n]|\\.)*"'
    r"|'(?:[^'\\\n]|\\.)*'")


def mask_strings(line):
    """把字串内容换成空格。注释符号出现在字串里时不是注释：

    ${#paths[@]} 与 print(f"  # {kind}") 都会被逐行的 #(.*)$ 当成注释。
    """
    line = re.sub(r"\$\{#", "$${", line)
    return QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), line)


def comment_chunks(text, pat, blocks=False):
    out = []
    if pat is None:
        return list(enumerate(text.splitlines(), 1))
    for m in (BLOCK.finditer(text) if blocks else ()):
        s = next((g for g in m.groups() if g is not None), "")
        out.append((text[:m.start()].count("\n") + 1, s))
    for i, line in enumerate(text.splitlines(), 1):
        m = re.search(pat, mask_strings(line))
        if m:
            out.append((i, next((g for g in m.groups() if g), "")))
    return out


DOCSTRING = re.compile(r'^\s*(?:[rubf]{0,2})("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
                       re.M)


def docstrings(text):
    return [(text[:m.start()].count("\n") + 1, m.group(1)) for m in DOCSTRING.finditer(text)]


def check_comments(root):
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
        if f.name in SELF:
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        hits = []
        chunks = comment_chunks(text, pat, f.suffix in BLOCK_LANGS)
        if f.suffix == ".py":
            chunks = chunks + docstrings(text)
        for line, chunk in chunks:
            if pat is not None and CJK.search(chunk):
                hits.append(f"{line}: 注释里有中文  {chunk.strip()[:60]}")
                continue
            for w in COLLOQUIAL:
                if w in chunk:
                    hits.append(f"{line}: 口语词「{w}」  {chunk.strip()[:60]}")
                    break
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
        for m in BARE_RUN.finditer(text):
            hits.append(f"应写成执行或运行，不用单字: {text[max(0, m.start() - 6):m.start() + 6]}")

        chars = len(re.sub(r"\s", "", text))
        dashes = text.count("——")
        if chars and dashes > max(1, chars // 1000):
            hits.append(f"破折号 {dashes} 处，{chars} 字，超过每千字 1 次")
        for line in text.split("\n"):
            line = line.replace(" — distfiles.gentoozh.org", "")
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
    bad += check_emitted(pathlib.Path(dirname).parent)
    if not bad:
        print("  代码注释与输出字符串: 无口语词")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
