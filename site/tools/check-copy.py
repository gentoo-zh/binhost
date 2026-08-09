#!/usr/bin/env python3

import json
import pathlib
import re
import sys

VOCAB = json.loads((pathlib.Path(__file__).with_name("copy-words.json")).read_text())

PHRASES = [tuple(x) for x in VOCAB["phrases"]]
WORDS = VOCAB["words"]
FILLER = [tuple(x) for x in VOCAB["filler"]]


from html.parser import HTMLParser                        # noqa: E402

VISIBLE_ATTRS = {"title", "aria-label", "placeholder", "alt", "content", "value"}
SKIP_TAGS = {"script", "style"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
SPECIMEN = "data-specimen"


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.specimen = []

    def visible_attrs(self, attrs):
        for name, value in attrs:
            if name in VISIBLE_ATTRS and value:
                self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        names = {n for n, _ in attrs}
        if tag in VOID_TAGS:
            if not self.skip and SPECIMEN not in names:
                self.visible_attrs(attrs)
            return
        if tag in SKIP_TAGS or SPECIMEN in names:
            self.skip += 1
            self.specimen.append(tag)
            return
        if self.skip:
            self.specimen.append(tag)
            return
        self.visible_attrs(attrs)

    def handle_startendtag(self, tag, attrs):
        names = {n for n, _ in attrs}
        if not self.skip and tag not in SKIP_TAGS and SPECIMEN not in names:
            self.visible_attrs(attrs)

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
    """Every run of text a reader can see: body, attributes, i18n tables.

    An earlier version stripped title, pre, table.spec and rule-dont with a
    regex and never looked at attributes, so none of those were ever checked.
    """
    v = Visible()
    v.feed(html)
    tables = "\n".join(re.findall(r"window\.MIRROR_I18N = \{[\s\S]*?\n\};", html))
    tables = re.sub(r"<[^>]+>", " ", tables)
    return "\n".join(v.parts) + "\n" + tables


COLLOQUIAL = VOCAB["colloquial"]
COLLOQUIAL_EMIT = COLLOQUIAL + VOCAB["colloquial_emit_extra"]

BARE_RUN = re.compile(VOCAB["bare_run"])

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


DATA = {"copy-words.json", "copy-fixtures.json"}

EMIT_SUFFIX = (".sh", ".py", ".js", ".yml", ".yaml", ".html", ".css", ".txt",
                ".service", ".timer")
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


UNIT_TEXT = re.compile(r"^(?:Description|Documentation)=(.*)$", re.M)


def emitted_chunks(text, suffix):
    out = []
    if suffix in (".service", ".timer"):
        return [(text[:m.start()].count("\n") + 1, m.group(1))
                for m in UNIT_TEXT.finditer(text) if CJK.search(m.group(1))]
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
        if not f.is_file() or f.suffix not in EMIT_SUFFIX or f.name in DATA:
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
                    hits.append(f"{line}: 口语词 `{w}`  {chunk.strip()[:60]}")
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
    """Blank out string contents. A comment marker inside a string is not one:

    ${#paths[@]} and print(f"  # {kind}") both match a per-line #(.*)$.
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


FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)[^\n]*\n([\s\S]*?)^```", re.M)
FENCE_COMMENT = {
    "bash": r"#(.*)$", "sh": r"#(.*)$", "shell": r"#(.*)$", "console": r"#(.*)$",
    "python": r"#(.*)$", "py": r"#(.*)$", "yaml": r"#(.*)$", "yml": r"#(.*)$",
    "ini": r"#(.*)$", "conf": r"#(.*)$", "js": r"//(.*)$",
}


def fenced_comments(text):
    """Comments inside Markdown code fences.

    A fence carries commands a reader may paste, so its comments are code
    comments and follow the same rule as the rest of the tree.
    """
    out = []
    for m in FENCE.finditer(text):
        pat = FENCE_COMMENT.get(m.group(1).lower())
        if pat is None:
            continue
        base = text[:m.start()].count("\n") + 1
        for i, line in enumerate(m.group(2).splitlines(), 1):
            hit = re.search(pat, mask_strings(line))
            if hit:
                out.append((base + i, next((g for g in hit.groups() if g), "")))
    return out


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
        if f.name in DATA:
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        hits = []
        chunks = comment_chunks(text, pat, f.suffix in BLOCK_LANGS)
        if f.suffix == ".py":
            chunks = chunks + docstrings(text)
        fenced = set()
        if f.suffix == ".md":
            fenced = {(n, c) for n, c in fenced_comments(text)}
            chunks = chunks + sorted(fenced)
        for line, chunk in chunks:
            if (pat is not None or (line, chunk) in fenced) and CJK.search(chunk):
                hits.append(f"{line}: 注释里有中文  {chunk.strip()[:60]}")
                continue
            for w in COLLOQUIAL:
                if w in chunk:
                    hits.append(f"{line}: 口语词 `{w}`  {chunk.strip()[:60]}")
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
                hits.append(f"禁止词： {w}")
        for pat, why in FILLER:
            for m in re.finditer(pat, text):
                hits.append(f"{why}: {m.group(0)[:20]}")
        for m in BARE_RUN.finditer(text):
            hits.append(f"应写成执行或运行，不用单字： {text[max(0, m.start() - 6):m.start() + 6]}")

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
        print("  代码注释与输出字符串： 无口语词")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
