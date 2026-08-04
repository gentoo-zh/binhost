#!/usr/bin/env python3

import importlib.util
import pathlib
import tempfile


SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "build" / "move-package.py"
spec = importlib.util.spec_from_file_location("move_package", SCRIPT)
move = importlib.util.module_from_spec(spec)
spec.loader.exec_module(move)

with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "packages.txt"
    path.write_text("app-misc/old\napp-misc/z-last\n")
    move.main("app-misc/old", "net-misc/new", path)
    assert path.read_text().splitlines() == ["app-misc/z-last", "net-misc/new"]

print("  move 会在同一份清单中替换来源与目标")
