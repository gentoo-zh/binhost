#!/usr/bin/env python3
"""Check commit subjects against the repository's convention.

    check-commits.py <base>..<head>

Checked in CI over a pull request's own commits, not over history: the rules
came after most of it, and rewriting a public branch to satisfy them would cost
more than it is worth.

The scope is not a fixed list. It has to name something the commit actually
touches -- a top-level directory, or a file's name without its extension -- so
a new script brings its own scope with it and nothing here has to be updated.
"""

import re
import subprocess
import sys
import unicodedata


# 首字符也允许下划线：仓库里有 site/_app.html，它的 scope 就是 _app。
SUBJECT = re.compile(r"^([a-z0-9_][a-z0-9._-]*): (\S.*)$")
# GLEP 66, the same limit the overlay holds its own subjects to.
SUBJECT_LEN = 69
BODY_WIDTH = 78
# The subject is English so that the log reads for anyone; the body is written
# in the language of whoever is directing the work, which here is Chinese.
CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
# Chinese in this project sets terms off with backticks, not with the
# full-width brackets.
FULLWIDTH_QUOTES = re.compile(r"[\u300c\u300d\u300e\u300f]")
# Never signed by a tool. Kept as a check rather than a habit because a habit
# has already failed once.
ATTRIBUTION = re.compile(r"co-authored-by:.*(claude|copilot|gpt)|generated with",
                         re.I)


def width(s):
    """Display width, counting the wide forms as two columns."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def scopes_for(sha):
    """What this commit may call itself.

    Top-level directories, plus the stem of every file it touches. A commit
    editing build/stage-index.py may be `stage-index:` or `build:`; one that
    edits four files across build/ has `build:` and each of the four stems.
    """
    files = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", sha],
        capture_output=True, text=True, check=True).stdout.split()
    out = set()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            out.add(parts[0])
        else:
            # 根目录的文件：小写它自己的名字，另外一律接受 docs。README.md、
            # CONTRIBUTING.md、LICENSE、.gitignore 原来一个可用的写法都没有
            # ——主题必须小写开头，而候选集里只有原样大小写的文件名，于是
            # 只改这些文件的提交无论怎么写都过不了，纯文档的 PR 合不进来。
            out.add("docs")
        stem = parts[-1].split(".")[0].lower()
        if not stem:
            # .gitignore 这种全是后缀的，用去掉点的那一段
            stem = parts[-1].lstrip(".").split(".")[0].lower()
        if not stem:
            continue
        out.add(stem)
        # A family of files shares the part before the hyphen, so a commit
        # across test-stage-index.py and test-validate.py is `test:` rather
        # than picking one of them to speak for the rest.
        while "-" in stem:
            stem = stem.rsplit("-", 1)[0]
            out.add(stem)
    # .github/workflows/... would otherwise ask for a scope spelled `.github`
    if any(f.startswith(".github/") for f in files):
        out.add("ci")
    return out


def check(sha):
    """Problems with one commit, as a list of strings."""
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        capture_output=True, text=True, check=True).stdout.rstrip("\n")
    lines = message.split("\n")
    subject = lines[0]
    problems = []

    m = SUBJECT.match(subject)
    if not m:
        problems.append(f"主题不是 `scope: 主题` 的形式: {subject!r}")
    else:
        scope, rest = m.group(1), m.group(2)
        allowed = scopes_for(sha)
        if scope not in allowed:
            problems.append(
                f"scope `{scope}` 不是这个提交改动的部分"
                f"（可用: {', '.join(sorted(allowed)) or '无'}）")
        if rest.endswith(("。", ".")):
            problems.append("主题结尾不要句号")
        if CJK.search(rest):
            problems.append("主题写英文，正文才用中文")

    if len(subject) > SUBJECT_LEN:
        problems.append(f"主题 {len(subject)} 个字符，超过 {SUBJECT_LEN}")

    if len(lines) > 1 and lines[1].strip():
        problems.append("主题与正文之间要空一行")

    for i, line in enumerate(lines[2:], start=3):
        # Indented lines are quoted output or a command, left as they were
        # written.
        if line.startswith(("  ", "\t")):
            continue
        # A line holding one token longer than the limit -- a URL or a path --
        # cannot be wrapped to fit, and breaking it would make it worse. CJK
        # does not count: it has no spaces, so the whole line arrives as one
        # token while in fact it breaks anywhere.
        if any(width(tok) > BODY_WIDTH and not CJK.search(tok)
               for tok in line.split()):
            continue
        if width(line) > BODY_WIDTH:
            problems.append(f"正文第 {i} 行 {width(line)} 列，超过 {BODY_WIDTH}")

    if ATTRIBUTION.search(message):
        problems.append("提交信息里有工具署名")

    if FULLWIDTH_QUOTES.search(message):
        problems.append("中文不用全角引号，代码和字面量用反引号")

    return problems


def main(rev_range):
    if ".." not in rev_range:
        # 传单一 ref 会走完整段历史，而这套规矩是后来才有的。
        print(f"!!! 需要一个 a..b 范围，收到 {rev_range!r}", file=sys.stderr)
        return 1

    shas = subprocess.run(["git", "rev-list", "--no-merges", rev_range],
                          capture_output=True, text=True, check=True).stdout.split()
    if not shas:
        # 空范围是问题，不是通过。CI 若把基线算错（fork 点漂移、浅克隆），
        # 整个检查会静默跳过而全绿。
        print(f"!!! {rev_range} 里一个提交都没有，基线算错了", file=sys.stderr)
        return 1

    bad = 0
    for sha in reversed(shas):
        subject = subprocess.run(["git", "log", "-1", "--format=%s", sha],
                                 capture_output=True, text=True, check=True).stdout.strip()
        problems = check(sha)
        print(f"  {'✗' if problems else '✓'} {sha[:8]}  {subject}")
        for p in problems:
            print(f"      {p}")
        bad += bool(problems)

    print(f"\n>>> {len(shas)} 个提交，{bad} 个不合规范")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
