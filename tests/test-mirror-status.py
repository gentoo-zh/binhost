#!/usr/bin/env python3
"""deploy/mirror-status.py against a fake mirror served by http.server from a temporary tree."""
import functools
import http.server
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "mirror-status.py"
ISO = "/gentoo-cjk-livecd/20260928T101603Z/install-amd64-cjk-minimal-20260928T101603Z.iso"
PACKAGES = "/binpkgs/x86-64/Packages"
FILES = {
    "/gentoo-cjk-livecd/20260921T100057Z/old.iso": b"old",
    ISO: b"iso",
    "/gentoo-cjk-livecd/20260928T101603Z/install-amd64-cjk-minimal-20260928T101603Z.iso.sha256": b"sum",
    "/gigos/gigos-1.iso": b"gig",
    PACKAGES: b"PACKAGES: 1\n",
    "/unstable/binpkgs/x86-64/Packages": b"PACKAGES: 2\n",
    "/distfiles/foo-1.tar.gz": b"foo",
}
METHODS = []


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        METHODS.append("GET")
        super().do_GET()

    def do_HEAD(self):
        METHODS.append("HEAD")
        # /r/... answers with a redirect, as the CERNET mirror does.
        if self.path.startswith("/r/"):
            self.send_response(302)
            self.send_header("Location", self.path[2:])
            self.end_headers()
            return
        super().do_HEAD()

    def translate_path(self, path):
        # /z/... serves the same tree with a Last-Modified in the -0000 zone.
        return super().translate_path(path[2:] if path.startswith("/z/") else path)

    def send_header(self, keyword, value):
        if keyword == "Last-Modified" and self.path.startswith("/z/"):
            value = value.replace("GMT", "-0000")
        super().send_header(keyword, value)


class RawServer:
    """Answers every connection with reply, or holds it open without a word when reply is None."""

    def __init__(self, reply):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.base = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.reply = reply
        self.conns = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(conn)
            if self.reply is None:
                continue
            try:
                conn.recv(4096)
                conn.sendall(self.reply)
            except OSError:
                pass
            conn.close()

    def close(self):
        self.sock.close()
        for conn in self.conns:
            conn.close()


# The sentinels the script picks from FILES: all but the older Live ISO release.
SENTINELS = sorted(p for p in FILES if not p.endswith("/old.iso"))


class MirrorStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin"
        self.mirror = self.tmp / "mirror"
        for rel, data in FILES.items():
            for top in (self.origin, self.mirror / "gentoo-zh"):
                p = top / rel.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                os.utime(p, (1_790_000_000, 1_790_000_000))
        handler = functools.partial(Handler, directory=str(self.mirror))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.out = self.tmp / "mirror-status.json"
        METHODS.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp)

    def run_script(self, mirrors, out=None, origin=None, **extra):
        env = dict(os.environ, ORIGIN=str(origin or self.origin), OUT=str(out or self.out), MIRRORS=mirrors)
        env.update({"TIMEOUT": "3", **extra})
        return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)

    def status(self):
        return json.loads(self.out.read_text())["mirrors"]

    def test_in_sync_mirror_is_ok(self):
        r = self.run_script(f"a={self.base}/gentoo-zh b={self.base}/r/gentoo-zh")
        self.assertEqual(r.returncode, 0, r.stderr)
        for m in self.status().values():
            self.assertEqual((m["reachable"], m["ok"], m["missing"]), (True, True, []))
        self.assertNotIn("GET", METHODS)
        self.assertFalse((self.tmp / "mirror-status.json.new").exists())

    def test_missing_newest_iso_is_listed(self):
        (self.mirror / "gentoo-zh" / ISO.lstrip("/")).unlink()
        self.run_script(f"a={self.base}/gentoo-zh")
        m = self.status()["a"]
        self.assertFalse(m["ok"])
        self.assertEqual(m["missing"], [ISO])

    def test_stale_packages_is_listed(self):
        (self.mirror / "gentoo-zh" / PACKAGES.lstrip("/")).write_bytes(b"PACKAGES: 0\nold\n")
        self.run_script(f"a={self.base}/gentoo-zh")
        self.assertEqual(self.status()["a"]["missing"], [PACKAGES])

    def test_older_copy_of_same_size_is_listed(self):
        os.utime(self.mirror / "gentoo-zh" / PACKAGES.lstrip("/"), (1_780_000_000, 1_780_000_000))
        self.run_script(f"a={self.base}/gentoo-zh")
        self.assertEqual(self.status()["a"]["missing"], [PACKAGES])

    def test_unreachable_mirror(self):
        r = self.run_script("gone=http://127.0.0.1:1/gentoo-zh")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = self.status()["gone"]
        self.assertEqual((m["reachable"], m["ok"]), (False, False))
        # Every probed path counts as missing, so the file browser keeps origin links for all of them.
        self.assertEqual(sorted(m["missing"]), SENTINELS)
        self.assertIn("!!", r.stderr)

    def test_symlink_at_temp_name_is_not_followed(self):
        victim = self.tmp / "victim"
        victim.write_text("keep\n")
        planted = self.tmp / "mirror-status.json.new"
        planted.symlink_to(victim)
        r = self.run_script(f"a={self.base}/gentoo-zh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(victim.read_text(), "keep\n")
        self.assertTrue(planted.is_symlink())
        self.assertFalse(self.out.is_symlink())
        self.assertEqual(self.status()["a"]["ok"], True)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o644)
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()),
                         ["mirror", "mirror-status.json", "mirror-status.json.new", "origin", "victim"])

    def test_garbage_answer_fails_only_that_mirror(self):
        bad = RawServer(b"garbage\r\n\r\n")
        try:
            r = self.run_script(f"bad={bad.base}/gentoo-zh a={self.base}/gentoo-zh")
        finally:
            bad.close()
        self.assertEqual(r.returncode, 0, r.stderr)
        m = self.status()
        self.assertEqual((m["bad"]["reachable"], m["bad"]["ok"]), (False, False))
        self.assertEqual(sorted(m["bad"]["missing"]), SENTINELS)
        self.assertEqual((m["a"]["reachable"], m["a"]["ok"]), (True, True))

    def test_deadline_bounds_a_hung_mirror(self):
        hung = RawServer(None)
        try:
            start = time.monotonic()
            r = self.run_script(f"hung={hung.base}/gentoo-zh a={self.base}/gentoo-zh", TIMEOUT="6", DEADLINE="1")
            took = time.monotonic() - start
        finally:
            hung.close()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(took, 4)
        m = self.status()
        self.assertEqual((m["hung"]["ok"], sorted(m["hung"]["missing"])), (False, SENTINELS))
        self.assertEqual(m["a"]["ok"], True)

    def test_last_modified_in_minus_zero_zone_is_utc(self):
        r = self.run_script(f"z={self.base}/z/gentoo-zh", TZ="Asia/Shanghai")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.status()["z"]["missing"], [])

    def test_unreadable_origin_keeps_old_file(self):
        (self.tmp / "empty").mkdir()
        for origin in (self.tmp / "empty", self.tmp / "no-such-dir"):
            self.out.write_text("old\n")
            r = self.run_script(f"a={self.base}/gentoo-zh", origin=origin)
            self.assertNotEqual(r.returncode, 0, origin)
            self.assertIn("!!", r.stderr)
            self.assertEqual(self.out.read_text(), "old\n", origin)

    def test_unwritable_output_fails_and_keeps_old_file(self):
        self.out.write_text("old\n")
        r = self.run_script(f"a={self.base}/gentoo-zh", out=self.tmp / "no-such-dir" / "x.json")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("!! 无法写出", r.stderr)
        self.assertEqual(self.out.read_text(), "old\n")


if __name__ == "__main__":
    unittest.main()
