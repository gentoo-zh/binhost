#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


copy = load("check_copy", ROOT / "site" / "tools" / "check-copy.py")
css = load("check_css", ROOT / "site" / "tools" / "check-css.py")
bad = 0
forbidden = "值得" + "注意的是"

for label, marker in (("void", "<img data-specimen>"),
                      ("self-closing", "<span data-specimen />")):
    text = copy.visible_text(f"<p>正常</p>{marker}<p>{forbidden}</p>")
    if forbidden in text:
        print(f"  ✓ {label} specimen 不会跳过后续文案")
    else:
        print(f"  ✗ {label} specimen 让后续文案退出检查")
        bad += 1

sample = "a { color: red; }\n@media (x) { * { color: blue; } }\na { color: green; }\n"
top_level = [(line, selector) for line, selector, media in css.rules(sample)
             if selector == "a" and media is None]
if top_level == [(1, "a"), (3, "a")]:
    print("  ✓ 单行 media 结束后的规则仍属于顶层")
else:
    print(f"  ✗ 单行 media 污染了后续规则： {top_level}")
    bad += 1

with tempfile.TemporaryDirectory() as base:
    tree = pathlib.Path(base)
    tools = tree / "site" / "tools"
    chrome = tools / "chrome"
    chrome.mkdir(parents=True)
    shutil.copy2(ROOT / "site" / "tools" / "render-chrome.py", tools)
    for name in ("head", "nav", "foot"):
        (chrome / f"{name}.html").write_text(f"<{name}>内容</{name}>\n")
    page = tree / "site" / "index.html"
    page.write_text("".join(
        f"<!-- chrome:{name} -->\n旧内容\n<!-- /chrome:{name} -->\n"
        for name in ("head", "nav", "foot")))
    script = tools / "render-chrome.py"
    subprocess.run([sys.executable, script], check=True, capture_output=True, text=True)
    clean = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    nav = "<!-- chrome:nav -->\n<nav>内容</nav>\n<!-- /chrome:nav -->\n"
    page.write_text(page.read_text().replace(nav, ""))
    missing = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    if clean.returncode == 0 and missing.returncode != 0 and "nav 标记数量" in missing.stderr:
        print("  ✓ 共用区块标记被移除时检查失败")
    else:
        print("  ✗ 共用区块标记被移除后检查仍然通过")
        bad += 1

if bad:
    print(f"\n>>> {bad} 项未通过")
    sys.exit(1)
print("\n  三类检查器绕过均已覆盖")
