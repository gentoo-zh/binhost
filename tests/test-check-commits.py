#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

CHECK = str(BUILD / "check-commits.py")


def run(subject, body="", files=("build/stage-index.py",)):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        git = ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git[:3] + ["init", "-q", "-b", "master"], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base: 起点"],
                       check=True)
        for f in files:
            p = d / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n")
        subprocess.run(git + ["add", "-A"], check=True)
        message = subject + ("\n\n" + body if body else "")
        subprocess.run(git + ["commit", "-q", "-m", message], check=True)
        p = subprocess.run([sys.executable, CHECK, "master~1..master"],
                           capture_output=True, text=True, cwd=d)
        return p.returncode, p.stdout


CASES = [
    ("脚本名当 scope", "stage-index: decide by version", "", ("build/stage-index.py",), True),
    ("目录名当 scope", "build: change three scripts together", "",
     ("build/a.py", "build/b.py"), True),
    ("一族文件用横线前那段", "test: change two cases together", "",
     ("tests/test-validate.py", "tests/test-stage-index.py"), True),
    (".github 用 ci", "ci: add a job", "", (".github/workflows/validate.yml",), True),
    ("根目录文件用小写文件名", "readme: fix a typo", "", ("README.md",), True),
    ("根目录文件用 docs", "docs: fix a typo", "", ("README.md",), True),
    ("点开头的文件", "gitignore: ignore pyc", "", (".gitignore",), True),
    ("根目录文件仍不能乱认 scope", "nginx: fix a typo", "", ("README.md",), False),
    ("没有 scope", "decide by version without a scope", "",
     ("build/stage-index.py",), False),
    ("scope 指不到改动的部分", "nginx: decide by version", "",
     ("build/stage-index.py",), False),
    ("主题结尾有句号", "stage-index: decide by version.", "",
     ("build/stage-index.py",), False),
    ("主题过长", "stage-index: " + "a very long subject " * 6, "",
     ("build/stage-index.py",), False),
    ("主题与正文之间没空行", "stage-index: decide by version",
     None, ("build/stage-index.py",), False),
    ("正文超宽", "stage-index: decide by version", "非常长的一行说明" * 12,
     ("build/stage-index.py",), False),
    ("正文里缩进的引文不算超宽", "stage-index: decide by version",
     "说明：\n\n    " + "x" * 120, ("build/stage-index.py",), True),
    ("正文里断不开的地址不算超宽", "stage-index: decide by version",
     "见 https://example.invalid/" + "a" * 100, ("build/stage-index.py",), True),
    ("主题写中文", "stage-index: 按版本判断", "", ("build/stage-index.py",), False),
    ("中文正文里的全角引号", "stage-index: decide by version",
     "把 `直接取` 写成「直接下载」", ("build/stage-index.py",), False),
    ("有工具署名", "stage-index: decide by version",
     "Co-Authored-By: Claude <noreply@anthropic.com>",
     ("build/stage-index.py",), False),
]

def multi(subjects):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        git = ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t",
               "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q", "-b", "master"], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base: 起点"],
                       check=True)
        for n, s in enumerate(subjects):
            f = d / "build" / f"stage-index.py"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"x{n}\n")
            subprocess.run(git + ["add", "-A"], check=True)
            subprocess.run(git + ["commit", "-q", "-m", s], check=True)
        p = subprocess.run([sys.executable, CHECK, f"master~{len(subjects)}..master"],
                           capture_output=True, text=True, cwd=d)
        return p.returncode, p.stdout


print(f"  {'情形':<26} {'预期':<6} 实际")
bad = 0
for name, subject, body, files, ok in CASES:
    if body is None:
        rc, out = run(subject + "\n紧接着的正文", "", files)
    else:
        rc, out = run(subject, body, files)
    got = rc == 0
    good = got == ok
    print(f"  {'✓' if good else '✗'} {name:<24} {'通过' if ok else '不通过':<6} "
          f"{'通过' if got else '不通过'}")
    if not good:
        for line in out.splitlines():
            print(f"      {line}")
        bad += 1


MULTI = [
    ("整段范围都合规", ["stage-index: first change", "stage-index: second change"], True),
    ("第二个提交主题写中文", ["stage-index: first change", "stage-index: 第二个"], False),
    ("第一个提交主题写中文", ["stage-index: 第一个", "stage-index: second change"], False),
]
for name, subjects, ok in MULTI:
    rc, out = multi(subjects)
    got = rc == 0
    good = got == ok
    print(f"  {'✓' if good else '✗'} {name:<24} {'通过' if ok else '不通过':<6} "
          f"{'通过' if got else '不通过'}")
    if not good:
        bad += 1
        for line in out.splitlines():
            print(f"      {line}")

rc, out = run("stage-index: decide by version")
plain_status = rc == 0 and "通过" in out \
    and "✓" not in out and "✗" not in out
print(f"  {'✓' if plain_status else '✗'} {'检查器状态不用装饰符号':<24}")
if not plain_status:
    bad += 1

sys.exit(1 if bad else 0)
