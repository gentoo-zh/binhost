#!/usr/bin/env python3

import pathlib
import re
import sys

from active_source import active_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
if not INSTALL.exists():
    print(f"  跳过：{INSTALL} 不存在，本机没有完整仓库")
    sys.exit(0)

DIRS = {
    "/usr/local/lib/binhost": ("${LIB}", "/usr/local/lib/binhost"),
    "/usr/local/bin": ("/usr/local/bin",),
}


def installed():
    out = {d: set() for d in DIRS}
    for line in active_text(INSTALL.read_text(), "shell").splitlines():
        m = re.search(r"install\s+-m\d+\s+(\S+)\s+(/usr/local/\S+)", line)
        if not m:
            continue
        dest = m.group(2)
        for d in out:
            if dest.startswith(d + "/"):
                out[d].add(pathlib.PurePath(dest).name)
    return out


def referenced():
    out = {d: set() for d in DIRS}
    for source in sorted(p for p in (ROOT / "deploy").iterdir() if p.is_file()):
        text = active_text(source.read_text(), "shell")
        for d, prefixes in DIRS.items():
            for p in prefixes:
                for m in re.finditer(re.escape(p) + r"/([A-Za-z0-9._-]+)", text):
                    out[d].add(m.group(1))
    return out


def staged_sources():
    """Repo paths the installers hand to rsync, per script."""
    out = {}
    for name in ("deploy/install.sh", "deploy/install-builder.sh", "deploy-site.sh"):
        script = ROOT / name
        if not script.exists():
            continue
        text = active_text(script.read_text(), "shell")
        # Join continuation lines so a multi-line rsync is one command.
        joined = re.sub(r"\\\n\s*", " ", text)
        for m in re.finditer(r"^\s*(?:sudo\s+)?rsync\s+([^\n]*)$", joined, re.M):
            for token in m.group(1).split():
                if ":" in token or token.startswith("-") or token.startswith("$"):
                    continue
                if "${" in token or not re.match(r"^[a-z][A-Za-z0-9._/-]*$", token):
                    continue
                out.setdefault(name, set()).add(token.rstrip("/") if token.endswith("/") else token)
    return out


def builder_dirs():
    """(dirs rsynced to the builder, dirs it then installs from)."""
    script = ROOT / "deploy" / "install-builder.sh"
    if not script.exists():
        return set(), set()
    text = re.sub(r"\\\n\s*", " ", active_text(script.read_text(), "shell"))
    sent = set()
    for m in re.finditer(r"^\s*rsync\s+([^\n]*)$", text, re.M):
        for token in m.group(1).split():
            if ":" in token or token.startswith("-") or "${" in token:
                continue
            if re.match(r"^[a-z][A-Za-z0-9._-]*/?$", token):
                sent.add(token.rstrip("/"))
    used = set(re.findall(
        r"install -m\d+ '?\$\{ROOT\}/([A-Za-z0-9._-]+)/", text))
    return sent, used


inst, refs = installed(), referenced()
bad = 0
sent, used = builder_dirs()
if sent or used:
    print(f"  install-builder.sh: rsync 送出 {sorted(sent)}，安装时读取 {sorted(used)}")
    for d in sorted(used - sent):
        print(f"    ✗ {d}/ 没有被 rsync 送到建置机，安装那步会失败")
        bad += 1
for script, sources in sorted(staged_sources().items()):
    print(f"  {script}: rsync 送出 {len(sources)} 个源码路径")
    for src in sorted(sources):
        if not (ROOT / src).exists():
            print(f"    ✗ {src} 不存在，{script} 的 rsync 会失败")
            bad += 1
for d in DIRS:
    missing = sorted(refs[d] - inst[d])
    print(f"  {d}: 引用 {len(refs[d])} 个，安装 {len(inst[d])} 个")
    for name in missing:
        print(f"    ✗ {name} 被引用但 install.sh 未安装")
        bad += 1

sys.exit(1 if bad else 0)
