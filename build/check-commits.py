#!/usr/bin/env python3
"""
check-commits.py <base>..<head>
"""

import re
import subprocess
import sys
import unicodedata


SUBJECT = re.compile(r"^([a-z0-9_][a-z0-9._-]*): (\S.*)$")
SUBJECT_LEN = 69
BODY_WIDTH = 78
CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
FULLWIDTH_QUOTES = re.compile(r"[\u300c\u300d\u300e\u300f]")
ATTRIBUTION = re.compile(r"co-authored-by:.*(claude|copilot|gpt)|generated with",
                         re.I)


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def scopes_for(sha):
    files = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", sha],
        capture_output=True, text=True, check=True).stdout.split()
    out = set()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            out.add(parts[0])
        else:
            out.add("docs")
        stem = parts[-1].split(".")[0].lower()
        if not stem:
            stem = parts[-1].lstrip(".").split(".")[0].lower()
        if not stem:
            continue
        out.add(stem)
        while "-" in stem:
            stem = stem.rsplit("-", 1)[0]
            out.add(stem)
    if any(f.startswith(".github/") for f in files):
        out.add("ci")
    return out


def check(sha):
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        capture_output=True, text=True, check=True).stdout.rstrip("\n")
    lines = message.split("\n")
    subject = lines[0]
    problems = []

    m = SUBJECT.match(subject)
    if not m:
        problems.append(f"主题不是 `scope: 主题` 的形式： {subject!r}")
    else:
        scope, rest = m.group(1), m.group(2)
        allowed = scopes_for(sha)
        if scope not in allowed:
            problems.append(
                f"scope `{scope}` 不是这个提交改动的部分"
                f"（可用： {', '.join(sorted(allowed)) or '无'}）")
        if rest.endswith(("。", ".")):
            problems.append("主题结尾不要句号")
        if CJK.search(rest):
            problems.append("主题写英文，正文才用中文")

    if len(subject) > SUBJECT_LEN:
        problems.append(f"主题 {len(subject)} 个字符，超过 {SUBJECT_LEN}")

    if len(lines) > 1 and lines[1].strip():
        problems.append("主题与正文之间要空一行")

    for i, line in enumerate(lines[2:], start=3):
        if line.startswith(("  ", "\t")):
            continue
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
        print(f"!!! 需要一个 a..b 范围，收到 {rev_range!r}", file=sys.stderr)
        return 1

    shas = subprocess.run(["git", "rev-list", "--no-merges", rev_range],
                          capture_output=True, text=True, check=True).stdout.split()
    if not shas:
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
