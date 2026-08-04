#!/usr/bin/env python3

import importlib.util
import pathlib
import sys
import tempfile
import types

import portage


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "sign-packages.py"
spec = importlib.util.spec_from_file_location("sign_packages", SCRIPT)
sign_packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_packages)


def stanza(cpv, path):
    return f"CPV: {cpv}\nPATH: {path}"


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    valid = "app-misc/a/a-1-1.gpkg.tar"
    invalid = "app-misc/b/b-1-1.gpkg.tar"
    for relative in (valid, invalid):
        package = root / relative
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_bytes(b"package")
    (root / "Packages").write_text(
        "PACKAGES: 2\nVERSION: 0\n\n" +
        stanza("app-misc/a-1", valid) + "\n\n" +
        stanza("app-misc/b-1", invalid) + "\n"
    )
    changed = root / ".changed"
    updated = []

    class FakeGpkg:
        def __init__(self, _settings, gpkg_file, verify_signature):
            assert not verify_signature
            self.path = gpkg_file

        def update_signature(self, keep_current_signature):
            assert not keep_current_signature
            updated.append(self.path)

    fake_module = types.ModuleType("portage.gpkg")
    fake_module.gpkg = FakeGpkg
    original_module = sys.modules.get("portage.gpkg")
    original_attribute = getattr(portage, "gpkg", None)
    original_import = sign_packages.verify_signatures.import_key
    original_valid = sign_packages.signature_valid
    original_run = sign_packages.subprocess.run
    try:
        sys.modules["portage.gpkg"] = fake_module
        portage.gpkg = fake_module
        sign_packages.verify_signatures.import_key = lambda *args: None
        sign_packages.signature_valid = (
            lambda path, *_args: pathlib.Path(path).as_posix().endswith(valid))
        sign_packages.subprocess.run = lambda *args, **kwargs: None
        result = sign_packages.sign(root, "", root / "public.asc", "fingerprint",
                                    changed)
    finally:
        if original_module is None:
            del sys.modules["portage.gpkg"]
        else:
            sys.modules["portage.gpkg"] = original_module
        if original_attribute is None:
            del portage.gpkg
        else:
            portage.gpkg = original_attribute
        sign_packages.verify_signatures.import_key = original_import
        sign_packages.signature_valid = original_valid
        sign_packages.subprocess.run = original_run

    assert result == (1, 2)
    assert updated == [str(root / invalid)]
    assert changed.read_text() == invalid + "\n"

assert sign_packages.signature_valid(
    pathlib.Path("package"), pathlib.Path("home"), "fingerprint",
    pathlib.Path("scratch")) is False

print("  当前密钥的有效签名会保留，只有无效签名会重新生成")
