#!/usr/bin/env python3

import importlib.util
import pathlib
import tempfile


SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "build" / "generation.py"
spec = importlib.util.spec_from_file_location("generation", SCRIPT)
generation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generation)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    for name, content in {
            "Packages": b"index\n", "Packages.gz": b"gzip\n",
            "installed.txt": b"snapshot\n",
            "official.txt": b"available\n",
            "source.txt": b"source\n"}.items():
        (root / name).write_bytes(content)
    generation.create(root)
    generation.verify(root)
    originals = {name: (root / name).read_bytes() for name in generation.FILES}
    for name in generation.FILES:
        (root / name).write_text("changed\n")
        try:
            generation.verify(root)
        except ValueError as error:
            assert name in str(error)
        else:
            raise AssertionError(f"a generation with a changed {name} was accepted")
        (root / name).write_bytes(originals[name])

print("  同代清单会拒绝混合的索引与基础系统快照")
