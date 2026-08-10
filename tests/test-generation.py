#!/usr/bin/env python3

import importlib.util
import json
import pathlib
import tempfile


SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "build" / "generation.py"
spec = importlib.util.spec_from_file_location("generation", SCRIPT)
generation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generation)

FILES = ("Packages", "Packages.gz", "installed.txt", "official.txt", "source.txt")
CONTENTS = {
    "Packages": b"index\n",
    "Packages.gz": b"gzip\n",
    "installed.txt": b"snapshot\n",
    "official.txt": b"available\n",
    "source.txt": b"source\n",
}
EXPECTED_DIGESTS = {
    "Packages": {"sha256": "f816b480f87144ec4de5862adf028ff66cc6964250325d53fd22bf8922824b6f", "size": 6},
    "Packages.gz": {"sha256": "f2f9e60a27b874939af599b1863012c34474650f0a8b247783ce0d35af004c18", "size": 5},
    "installed.txt": {"sha256": "827eeab94f7421c651f6170d7d0e62cd4fad4594fb07faff4466acb01128ccd9", "size": 9},
    "official.txt": {"sha256": "ed01b1557bd7a1e70f90d8838f38ae0bb6b8367122b3dca7e5935bafa440a45a", "size": 10},
    "source.txt": {"sha256": "b8bb034f9b63bd0254fbc7c157cae746c75853f4643d6cea844dc48ddb57f522", "size": 7},
}

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    for name, content in CONTENTS.items():
        (root / name).write_bytes(content)
    generation.create(root)
    manifest = json.loads((root / "generation.json").read_text())
    assert tuple(manifest["files"]) == FILES
    assert manifest["files"] == EXPECTED_DIGESTS
    generation.verify(root)
    manifest["schema"] = 2
    (root / "generation.json").write_text(json.dumps(manifest))
    try:
        generation.verify(root)
    except ValueError as error:
        assert "unsupported shape" in str(error)
    else:
        raise AssertionError("an unknown generation schema was accepted")
    manifest["schema"] = 1
    (root / "generation.json").write_text(json.dumps(manifest))
    originals = {name: (root / name).read_bytes() for name in FILES}
    for name in FILES:
        (root / name).write_text("changed\n")
        try:
            generation.verify(root)
        except ValueError as error:
            assert name in str(error)
        else:
            raise AssertionError(f"a generation with a changed {name} was accepted")
        (root / name).write_bytes(originals[name])

    (root / "Packages").write_bytes(b"other\n")
    try:
        generation.verify(root)
    except ValueError as error:
        assert "Packages" in str(error)
    else:
        raise AssertionError("a same-size replacement was accepted")

print("  同代清单会拒绝混合的索引与基础系统快照")
