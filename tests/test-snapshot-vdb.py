#!/usr/bin/env python3

import importlib.util
import pathlib
import tempfile


SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "build" / "snapshot-vdb.py"
spec = importlib.util.spec_from_file_location("snapshot_vdb", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp) / "vdb"
    package = root / "dev-libs" / "lib-2-r1"
    package.mkdir(parents=True)
    values = {
        "SLOT": "2/2\n",
        "USE": "foo  bar\n",
        "IUSE_EFFECTIVE": "foo bar baz\n",
        "EAPI": "8\n",
        "repository": "gentoo\n",
    }
    for name, value in values.items():
        (package / name).write_text(value)
    text = module.snapshot(root)
    expected = ("PACKAGES: 1\nVERSION: 1\n\nCPV: dev-libs/lib-2-r1\n"
                "SLOT: 2/2\nUSE: foo bar\nIUSE: foo bar baz\nEAPI: 8\n"
                "REPO: gentoo\n")
    assert text == expected, text

    minimal = root / "sys-apps" / "base-1"
    minimal.mkdir(parents=True)
    text = module.snapshot(root)
    header, *stanzas = text.rstrip("\n").split("\n\n")
    assert header == "PACKAGES: 2\nVERSION: 1", header
    assert set(stanzas) == {
        ("CPV: dev-libs/lib-2-r1\nSLOT: 2/2\nUSE: foo bar\n"
         "IUSE: foo bar baz\nEAPI: 8\nREPO: gentoo"),
        ("CPV: sys-apps/base-1\nSLOT: 0\nUSE:\nIUSE:\n"
         "EAPI: 0\nREPO:"),
    }, stanzas

print("  基础系统快照保留完整的 Portage 匹配元数据")
