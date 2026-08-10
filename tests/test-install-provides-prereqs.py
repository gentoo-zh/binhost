#!/usr/bin/env python3
"""install.sh must provide every nginx root and every command cron reaches for.

A fresh machine was missing git, logrotate, certbot and /var/www/acme in turn.
The old machine had them all, so none of it ever showed up.
"""

import pathlib
import re
import sys

from active_source import active_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
CRON = ROOT / "deploy" / "cron.d-binhost"
NGINX = ROOT / "nginx"

if not INSTALL.exists():
    print(f"  跳过：{INSTALL} 不存在，本机没有完整仓库")
    sys.exit(0)

install = active_text(INSTALL.read_text(), "shell")
failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def nginx_roots():
    """Directories nginx serves. Aliases holding a variable are per-user."""
    roots = set()
    for conf in sorted(NGINX.glob("*.conf")) + sorted(NGINX.glob("*.inc")):
        for path in re.findall(r"^\s*(?:root|alias)\s+(\S+?)/?;", conf.read_text(), re.M):
            if "$" not in path:
                roots.add(path)
    return roots


def created_dirs():
    return set(re.findall(r"install\s+-dm\d+[^\n]*?(/(?:srv|var|etc)/\S+)", install))


def cron_commands():
    """Absolute paths in cron that this repository does not install itself."""
    return {pathlib.PurePath(c).name
            for c in re.findall(r"/[a-z/]+bin/[a-z0-9_-]+", CRON.read_text())
            if not c.startswith("/usr/local/bin/")}


created = created_dirs()
for root in sorted(nginx_roots()):
    covered = any(d == root or d.startswith(root + "/") for d in created)
    check(f"install.sh 创建 nginx root {root}", covered,
          "已创建：" + " ".join(sorted(created)))

deps = set(re.findall(r"for cmd in ([a-z0-9 _-]+); do", install))
declared = set(" ".join(deps).split())
for cmd in sorted(cron_commands()):
    check(f"install.sh 保证 cron 用的 {cmd} 存在", cmd in declared,
          "依赖清单：" + " ".join(sorted(declared)))

print()
print("  部署前置条件：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
