#!/usr/bin/env python3
"""Cases for validate.py's bindist detection.

The pattern this replaces matched every ebuild in the overlay that carried
bindist and captured '\\n\\nRDEPEND=' from all of them, so the check never
fired. Ebuild shapes, not the live overlay: the check has to hold whatever the
overlay happens to contain today.
"""

import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "validate", pathlib.Path(__file__).with_name("validate.py"))
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

# The real shape from x11-terms/termius: RESTRICT is followed by more quoted
# text further down the file, which is what the old pattern ran into.
TERMIUS = '''EAPI=8
DESCRIPTION="Terminal"
RESTRICT="bindist mirror strip"

RDEPEND="dev-libs/glib"
'''

CASES = [
    ("bindist first in the list", 'RESTRICT="bindist mirror strip"\n', True),
    ("bindist last in the list", 'RESTRICT="mirror strip bindist"\n', True),
    ("bindist alone", 'RESTRICT="bindist"\n', True),
    ("no bindist", 'RESTRICT="mirror strip"\n', False),
    ("no RESTRICT at all", 'LICENSE="GPL-2"\n', False),
    ("indented, inside a conditional", '\tRESTRICT="bindist"\n', True),
    ("second assignment carries it",
     'RESTRICT="mirror"\nRESTRICT="bindist"\n', True),
    ("first assignment carries it",
     'RESTRICT="bindist"\nRESTRICT="mirror"\n', True),
    ("quoted text later in the file", TERMIUS, True),
    ("bindist only inside a comment", '# RESTRICT="bindist" upstream says no\n', False),
    ("substring of another token", 'RESTRICT="nobindistcheck"\n', True),
    # 跨行写法：两份实作曾经在这里分歧，gen-packages 认得而 ebuilds 不认，
    # 于是页面标着 bindist 而 validate 那道再散布闸门放行
    ("value spanning several lines", 'RESTRICT="\n\tbindist\n\tmirror"\n', True),
    ("several lines, no bindist", 'RESTRICT="\n\tmirror\n\ttest"\n', False),
]

print(f"  {'形状':<30} {'预期':<6} 实际")
bad = 0
for name, text, expect in CASES:
    got = validate.restricts_bindist(text)
    ok = got == expect
    print(f"  {'✓' if ok else '✗'} {name:<28} {str(expect):<6} {got}")
    bad += not ok

# The overlay is not the source of truth for the cases above, but a check that
# never fires on real data is exactly what went unnoticed, so assert on it too.
if len(sys.argv) > 1:
    overlay = pathlib.Path(sys.argv[1])
    hits = [eb for eb in overlay.glob("*/*/*.ebuild")
            if validate.restricts_bindist(eb.read_text(errors="ignore"))]
    ok = len(hits) > 0
    print(f"  {'✓' if ok else '✗'} {'真实 overlay 中可识别 bindist':<28} {'>0':<6} {len(hits)}")
    bad += not ok

sys.exit(1 if bad else 0)
