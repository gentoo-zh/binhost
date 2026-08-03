#!/usr/bin/env python3

import pathlib
import sys

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"
sys.path.insert(0, str(BUILD))
from ebuilds import bindist_state, restricts_bindist          # noqa: E402

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
    ("second plain assignment carries it",
     'RESTRICT="mirror"\nRESTRICT="bindist"\n', True),
    ("last plain assignment wins, so this one is not bindist",
     'RESTRICT="bindist"\nRESTRICT="mirror"\n', False),
    ("+= appends to the earlier value",
     'RESTRICT="mirror"\nRESTRICT+=" bindist"\n', True),
    ("quoted text later in the file", TERMIUS, True),
    ("bindist only inside a comment", '# RESTRICT="bindist" upstream says no\n', False),
    ("substring of another token", 'RESTRICT="nobindistcheck"\n', False),
    ("bindist as a prefix of another token", 'RESTRICT="bindistfoo"\n', False),
    ("bindist as a suffix of another token", 'RESTRICT="nobindist"\n', False),
    ("value spanning several lines", 'RESTRICT="\n\tbindist\n\tmirror"\n', True),
    ("several lines, no bindist", 'RESTRICT="\n\tmirror\n\ttest"\n', False),
]

print(f"  {'形状':<30} {'预期':<6} 实际")
bad = 0
for name, text, expect in CASES:
    got = restricts_bindist(text)
    ok = got == expect
    print(f"  {'✓' if ok else '✗'} {name:<28} {str(expect):<6} {got}")
    bad += not ok

if len(sys.argv) > 1:
    overlay = pathlib.Path(sys.argv[1])
    hits = [eb for eb in overlay.glob("*/*/*.ebuild")
            if restricts_bindist(eb.read_text(errors="ignore"))]
    ok = len(hits) > 0
    print(f"  {'✓' if ok else '✗'} {'真实 overlay 中可识别 bindist':<28} {'>0':<6} {len(hits)}")
    bad += not ok

STATES = [
    ("plain bindist is decidable", 'RESTRICT="bindist"\n', "yes"),
    ("plain mirror is decidable", 'RESTRICT="mirror"\n', "no"),
    ("variable expansion is undecidable", 'R="bindist"\nRESTRICT="${R}"\n', "unknown"),
    ("command substitution is undecidable", 'RESTRICT="`f`"\n', "unknown"),
    ("two plain assignments are undecidable",
     'RESTRICT="bindist"\nRESTRICT="mirror"\n', "unknown"),
    ("assignment inside a conditional is undecidable",
     'if use foo; then\n\tRESTRICT="bindist"\nfi\n', "unknown"),
]
print()
for name, text, expect in STATES:
    got = bindist_state(text)
    ok = got == expect
    print(f"  {'✓' if ok else '✗'} {name:<44} {expect:<8} {got}")
    bad += not ok

sys.exit(1 if bad else 0)
