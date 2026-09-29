#!/usr/bin/env python3
"""Syntax colours for code blocks, written into the page when render-chrome.py runs.

A block opts in with <pre data-syntax="sh"> (shell commands) or <pre data-syntax="conf"> (Portage
make.conf, binrepos.conf and repos.conf). Each coloured run becomes <span class="t-X">, one class per
role of the React Spectrum docs (s2-docs src/Code.tsx:11-24):

    t-s string   t-k keyword   t-n number   t-p property   t-f function or tag   t-v variable   t-c comment

Punctuation, flags and plain words keep the body colour. Spans that scripts rewrite stay whole: the
mirror slot (data-src-slot, rewritten by source-switch.js), the sudo prefix (sudo-switch.js) and the
prompt. They take the colour class of the run they sit in, so the colour survives the rewrite. The
text of the block never changes, only the spans around it, so what copy puts on the clipboard is the
text on screen. Running it again gives the same output, which lets render-chrome.py --check see a
block whose colours are out of date.
"""
import html
import re

PRE = re.compile(r'(<pre\b[^>]*\bdata-syntax="(\w+)"[^>]*>)(.*?)(</pre>)', re.S)
TAG = re.compile(r"<span\b([^>]*)>([^<]*)</span>|<[^>]*>|[^<]+", re.S)
CLASS = re.compile(r'\bclass="([^"]*)"')
GENERATED = re.compile(r"^t-[a-z]$")
# Hand-written colour spans from before this tool; a bare one is unwrapped, one that carries data for a
# script keeps its element and loses the class.
LEGACY = {"key", "val", "sec", "flag"}

SH_KEYWORDS = {"sudo", "if", "then", "else", "elif", "fi", "for", "while", "do", "done", "case", "esac",
               "in", "function", "export"}
CONF_WORDS = {"true", "false", "yes", "no"}


def parse(inner):
    """Split a block into text pieces and whole elements; drop generated and legacy colour spans."""
    pieces = []
    for m in TAG.finditer(inner):
        if m.group(0).startswith("<span"):
            attrs, text = m.group(1), m.group(2)
            cm = CLASS.search(attrs)
            classes = cm.group(1).split() if cm else []
            kept = [c for c in classes if not GENERATED.match(c) and c not in LEGACY]
            rest = CLASS.sub("", attrs).strip()
            if not kept and not rest:
                pieces.append(("text", html.unescape(text)))
                continue
            attrs = (f'class="{" ".join(kept)}" ' if kept else "") + rest
            pieces.append(("elem", attrs.strip(), html.unescape(text)))
        elif m.group(0).startswith("<"):
            raise ValueError(f"代码块中只允许 span 元素：{m.group(0)[:60]}")
        else:
            pieces.append(("text", html.unescape(m.group(0))))
    return pieces


def expansion(line, i):
    """The end of a $VAR or ${...} starting at i, or i when there is none."""
    if line.startswith("${", i):
        j = line.find("}", i)
        return len(line) if j < 0 else j + 1
    m = re.compile(r"\$[A-Za-z_]\w*").match(line, i)
    return m.end() if m else i


def dquote(line, i, out, base):
    """A double-quoted string from i; expansions inside it are variables. Returns the end."""
    start, j = i, i + 1
    while j < len(line) and line[j] != '"':
        if line[j] == "\\":
            j += 2
            continue
        k = expansion(line, j) if line[j] == "$" else j
        if k > j:
            if j > start:
                out.append((base + start, base + j, "s"))
            out.append((base + j, base + k, "v"))
            start = j = k
            continue
        j += 1
    end = min(j + 1, len(line))
    if end > start:
        out.append((base + start, base + end, "s"))
    return end


def conf_line(line, base, out):
    s = line.lstrip()
    i = len(line) - len(s)
    if not s:
        return
    if s[0] in "#;":
        out.append((base + i, base + len(line), "c"))
        return
    m = re.match(r"\[([^\]]+)\]", s)
    if m:
        out.append((base + i + 1, base + i + 1 + len(m.group(1)), "f"))
        return
    m = re.match(r"([A-Za-z_][\w.-]*)(\s*)=(\s*)", s)
    if not m:
        return
    out.append((base + i, base + i + len(m.group(1)), "p"))
    v = i + m.end()
    value = line[v:].rstrip()
    if not value:
        return
    if value.startswith('"'):
        dquote(line, v, out, base)
    elif value.startswith("'"):
        out.append((base + v, base + v + len(value), "s"))
    elif re.fullmatch(r"-?\d+", value):
        out.append((base + v, base + v + len(value), "n"))
    elif value.lower() in CONF_WORDS:
        out.append((base + v, base + v + len(value), "k"))
    else:
        out.append((base + v, base + v + len(value), "s"))


WORD = re.compile(r"[^\s|&;<>()\"'`$]+")


def sh_line(line, base, out, continued):
    """One shell line. Returns (ends with a continuation, heredoc terminator or None)."""
    i, cmd, heredoc = 0, not continued, None
    n = len(line)
    while i < n:
        c = line[i]
        if c.isspace():
            i += 1
        elif c == "#" and (i == 0 or line[i - 1].isspace()):
            out.append((base + i, base + n, "c"))
            break
        elif c == "\\" and i == n - 1:
            return True, heredoc
        elif line.startswith("<<", i):
            j = i + 2 + (line[i + 2:i + 3] == "-")
            while j < n and line[j] == " ":
                j += 1
            m = re.compile(r"'[^']*'|\"[^\"]*\"|[\w.-]+").match(line, j)
            if m:
                out.append((base + m.start(), base + m.end(), "s"))
                heredoc = m.group(0).strip("'\"")
                i = m.end()
            else:
                i += 2
        elif line.startswith(("&&", "||"), i):
            i, cmd = i + 2, True
        elif c in "|;(":
            i, cmd = i + 1, True
        elif c in "<>)&":
            i += 1
        elif c == "'":
            j = line.find("'", i + 1)
            j = n if j < 0 else j + 1
            out.append((base + i, base + j, "s"))
            i = j
        elif c == '"':
            i = dquote(line, i, out, base)
        elif line.startswith("$(", i):
            i, cmd = i + 2, True
        elif c == "$":
            j = expansion(line, i)
            if j > i:
                out.append((base + i, base + j, "v"))
                i = j
            else:
                i += 1
        else:
            m = WORD.match(line, i)
            if not m:
                i += 1
                continue
            word = m.group(0)
            a = re.match(r"([A-Za-z_]\w*)=", word)
            if cmd and a:
                out.append((base + i, base + i + len(a.group(1)), "p"))
                i += len(a.group(0))
                continue
            if cmd and word in SH_KEYWORDS:
                out.append((base + i, base + m.end(), "k"))
            elif cmd:
                out.append((base + i, base + m.end(), "f"))
                cmd = False
            elif re.fullmatch(r"\d+", word):
                out.append((base + i, base + m.end(), "n"))
            i = m.end()
    return False, heredoc


def tokens(text, syntax):
    out, base = [], 0
    continued, heredoc = False, None
    for line in text.split("\n"):
        if syntax == "conf":
            conf_line(line, base, out)
        elif heredoc is not None:
            if line.strip() == heredoc:
                s = len(line) - len(line.lstrip())
                out.append((base + s, base + len(line.rstrip()), "s"))
                heredoc = None
            else:
                conf_line(line, base, out)
        else:
            continued, heredoc = sh_line(line, base, out, continued)
        base += len(line) + 1
    return out


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def paint(inner, syntax):
    pieces = parse(inner)
    text = "".join(p[-1] for p in pieces)
    runs = tokens(text, syntax)
    role = {}
    for a, b, r in runs:
        for k in range(a, b):
            role[k] = r
    out, pos = [], 0
    for p in pieces:
        s = p[-1]
        if p[0] == "elem":
            r = role.get(pos) if s else None
            attrs = p[1]
            if r:
                cm = CLASS.search(attrs)
                if cm:
                    attrs = CLASS.sub(f'class="{cm.group(1)} t-{r}"', attrs, count=1)
                else:
                    attrs = f'class="t-{r}" {attrs}'
            out.append(f"<span {attrs}>{esc(s)}</span>")
        else:
            k = 0
            while k < len(s):
                r = role.get(pos + k)
                j = k + 1
                while j < len(s) and role.get(pos + j) == r and s[j] != "\n":
                    j += 1
                seg = esc(s[k:j])
                out.append(f'<span class="t-{r}">{seg}</span>' if r and s[k] != "\n" else seg)
                k = j
        pos += len(s)
    return "".join(out)


def render(page):
    """Colour every opted-in block of a page."""
    def one(m):
        syntax = m.group(2)
        if syntax not in ("sh", "conf"):
            raise ValueError(f"未知的 data-syntax：{syntax}")
        return m.group(1) + paint(m.group(3), syntax) + m.group(4)
    return PRE.sub(one, page)
