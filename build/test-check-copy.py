#!/usr/bin/env python3
import importlib.util
import io
import contextlib
import pathlib
import sys
import tempfile

TARGET = pathlib.Path(__file__).with_name("check-copy.py")
spec = importlib.util.spec_from_file_location("check_copy", TARGET)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

CASES = [
    ("js 模板字面量", "assets/util.js", "const x = `直接跑完就行`;\n", "emitted"),
    ("js 单行字串", "assets/util.js", "var m = '装上就行';\n", "emitted"),
    ("js 跨行拼接的第二段", "assets/util.js",
     "var m = '第一段' +\n        '直接跑就行';\n", "emitted"),
    ("python 三引号", "gen.py", 'MSG = """\n第一行\n直接跑就行\n"""\n', "emitted"),
    ("python 逐行 print", "gen.py", 'print("装上就行")\n', "emitted"),
    ("shell heredoc", "run.sh", "cat <<EOF\n装上就行，跑完看日志\nEOF\n", "emitted"),
    ("shell 引号字串", "run.sh", 'echo "搞定了"\n', "emitted"),
    ("yaml 里的字串", "wf.yml", 'run: echo "装上就行"\n', "emitted"),
    ("html 里的 i18n 串", "page.html", "var T = { a: '加载中，装上就行' };\n", "emitted"),

    ("css 多行注释", "assets/site.css", "/* 多行\n   直接跑完就行\n*/\nbody{}\n", "comment"),
    ("html 多行注释", "page.html", "<!-- 多行\n   装上就行\n-->\n", "comment"),
    ("shell 单行注释", "run.sh", "# 这一步搞定之后继续\ntrue\n", "comment"),
    ("python 行末注释", "gen.py", "x = 1  # 装上就行\n", "comment"),
    ("markdown 正文", "README.md", "装上就行。\n", "comment"),

    ("任何中文注释", "run.sh", "# 这是中文代码注释\ntrue\n", "comment"),
    ("python 中文注释", "gen.py", "# 中文说明\nx = 1\n", "comment"),
    ("js 中文注释", "assets/util.js", "// 中文说明\nvar y = 1;\n", "comment"),
    ("单独的跑", "run.sh", 'echo "跑 deploy/install.sh"\n', "emitted"),
]

CLEAN = {
    "assets/util.js": "const x = '已复制';\n",
    "gen.py": 'print("索引无法读取")\n',
    "run.sh": 'echo "本轮终止"\n',
    "wf.yml": 'run: echo "已发布"\n',
    "page.html": "<!-- chrome:head -->\n<p>未找到请求的资源。</p>\n",
    "assets/site.css": "body{}\n",
    "README.md": "在构建机上运行。\n",
}


def run(tree):
    root = pathlib.Path(tree)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        n = cc.check_comments(root) + cc.check_emitted(root)
    return n, buf.getvalue()


def plant(tree, rel, body):
    p = pathlib.Path(tree) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


bad = 0
with tempfile.TemporaryDirectory() as base:
    for rel, body in CLEAN.items():
        plant(base, rel, body)
    n, out = run(base)
    if n:
        print(f"  ✗ 干净的样本被报了 {n} 处\n{out}")
        bad += 1
    else:
        print("  ✓ 干净的样本不报")

for name, rel, body, kind in CASES:
    with tempfile.TemporaryDirectory() as base:
        for r, b in CLEAN.items():
            plant(base, r, b)
        plant(base, rel, CLEAN.get(rel, "") + body)
        n, out = run(base)
        if n:
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}：塞了口语词，检查器仍报全绿")
            bad += 1

# 站点正文走的是 main() 那条路，不是注释也不是字串常量
with tempfile.TemporaryDirectory() as base:
    site = pathlib.Path(base) / "site"
    site.mkdir()
    (site / "ok.html").write_text("<p>先执行一次配置</p>\n")
    if cc.main(str(site)) == 0:
        print("  ✓ 站点正文用词正确时不报")
    else:
        print("  ✗ 站点正文用词正确时被误报")
        bad += 1
    (site / "bad.html").write_text("<p>先跑一次配置</p>\n")
    if cc.main(str(site)) != 0:
        print("  ✓ 站点正文里单独的跑会被抓到")
    else:
        print("  ✗ 站点正文里单独的跑没有被抓到")
        bad += 1

if bad:
    print(f"\n>>> {bad} 项未通过")
    sys.exit(1)
print(f"\n  {len(CASES)} 种写法都能被抓到")
