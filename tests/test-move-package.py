#!/usr/bin/env python3

import importlib.util
import pathlib
import tempfile


SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "tools" / "move-package.py"
spec = importlib.util.spec_from_file_location("move_package", SCRIPT)
move = importlib.util.module_from_spec(spec)
spec.loader.exec_module(move)

with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "packages.txt"
    stable = pathlib.Path(tmp) / "stable-excluded.txt"
    path.write_text("app-misc/old\napp-misc/z-last\n")
    stable.write_text("# stable only\n\napp-misc/old\trequires testing dependency\n")
    move.main("app-misc/old", "net-misc/new", path, stable)
    assert path.read_text().splitlines() == ["app-misc/z-last", "net-misc/new"]
    assert stable.read_text() == (
        "# stable only\n\nnet-misc/new\trequires testing dependency\n")

print("  move 会同步替换主清单与 stable 排除项")
