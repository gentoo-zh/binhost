#!/usr/bin/env python3
"""site/tools/highlight.py: roles per language, spans that scripts rewrite, idempotence, and the text of a
block staying exactly what it was, since copy puts that text on the clipboard."""
import html
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("highlight", ROOT / "site" / "tools" / "highlight.py")
hl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hl)

bad = 0


def check(name, ok, detail=""):
    global bad
    if ok:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}" + (f"\n      {detail}" if detail else ""))
        bad += 1


def text(block):
    return html.unescape(re.sub(r"<[^>]+>", "", block))


def roles(block):
    """(role, text) for every coloured span, in order."""
    return re.findall(r'<span class="(?:[\w-]+ )*t-(\w)"[^>]*>([^<]*)</span>', block)


SH = ('<pre data-syntax="sh"><span class="prompt"></span><span class="sudo">sudo </span>tee '
      '/etc/portage/make.conf &gt; /dev/null &lt;&lt;\'EOF\'\n'
      'FEATURES="${FEATURES} getbinpkg"\n'
      'EOF\n'
      '<span class="prompt"></span><span class="sudo">sudo </span>gpg --homedir /etc/portage/gnupg \\\n'
      '    --lsign-key 6A07 # trust it\n'
      '<span class="prompt user"></span>curl -O <span data-src-slot="top" data-src-suffix="/k.asc">'
      'https://a.example/k.asc</span></pre>')
CONF = ('<pre data-syntax="conf"># /etc/portage/binrepos.conf/gentoo-zh.conf\n'
        '[gentoo-zh]\n'
        'sync-uri = <span class="val" data-src-slot="repo" data-src-suffix="/binpkgs/x86-64">'
        'https://a.example/binpkgs/x86-64</span>\n'
        'priority = 10\n'
        'verify-signature = true</pre>')

sh = hl.render(SH)
conf = hl.render(CONF)
r_sh, r_conf = roles(sh), roles(conf)

check("shell: sudo is a keyword and the command after it a function",
      ("k", "sudo ") in r_sh and ("f", "tee") in r_sh and ("f", "gpg") in r_sh, r_sh)
check("shell: a continued line starts with an argument, not a command",
      ("f", "--lsign-key") not in r_sh)
check("shell: the heredoc delimiter and terminator are strings", ("s", "'EOF'") in r_sh and ("s", "EOF") in r_sh)
check("shell: the heredoc body takes config colours",
      ("p", "FEATURES") in r_sh and ("v", "${FEATURES}") in r_sh and ("s", ' getbinpkg"') in r_sh, r_sh)
check("shell: a trailing # starts a comment", ("c", "# trust it") in r_sh)
check("conf: the file comment, section, keys and typed values",
      [("c", "# /etc/portage/binrepos.conf/gentoo-zh.conf"), ("f", "gentoo-zh"), ("p", "sync-uri")] == r_conf[:3]
      and ("n", "10") in r_conf and ("k", "true") in r_conf, r_conf)
check("the mirror slot keeps its data and takes the string colour",
      '<span class="t-s" data-src-slot="repo" data-src-suffix="/binpkgs/x86-64">' in conf, conf)
check("a slot outside any run keeps its attributes and gains no class",
      '<span data-src-slot="top" data-src-suffix="/k.asc">https://a.example/k.asc</span>' in sh, sh)
check("the sudo span stays one element and keeps its class", '<span class="sudo t-k">sudo </span>' in sh)
check("prompts stay empty and uncoloured", sh.count('<span class="prompt"></span>') == 2
      and '<span class="prompt user"></span>' in sh)
check("the text of each block is unchanged", text(sh) == text(SH) and text(conf) == text(CONF))
check("a second run changes nothing", hl.render(sh) == sh and hl.render(conf) == conf)
check("a block without data-syntax is left alone", hl.render("<pre>a = 1</pre>") == "<pre>a = 1</pre>")
try:
    hl.render('<pre data-syntax="sh"><b>x</b></pre>')
    check("an element other than span is refused", False)
except ValueError:
    check("an element other than span is refused", True)
try:
    hl.render('<pre data-syntax="js">x</pre>')
    check("an unknown syntax is refused", False)
except ValueError:
    check("an unknown syntax is refused", True)

# Every opted-in block in the tree is current; render-chrome.py --check covers the same, per page.
stale = [f.name for f in sorted((ROOT / "site").glob("*.html")) + sorted((ROOT / "site").glob("internal/*.html"))
         if hl.render(f.read_text()) != f.read_text()]
check("every page's code colours are current", not stale, "，".join(stale))

sys.exit(1 if bad else 0)
