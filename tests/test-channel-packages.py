#!/usr/bin/env python3

import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build/channel_packages.py"


def run(packages, excluded, previous=None):
    with tempfile.TemporaryDirectory() as temporary:
        directory = pathlib.Path(temporary)
        package_file = directory / "packages.txt"
        excluded_file = directory / "stable-excluded.txt"
        output = directory / "effective.txt"
        package_file.write_text(packages)
        excluded_file.write_text(excluded)
        if previous is not None:
            output.write_text(previous)
        result = subprocess.run(
            [sys.executable, "-B", SCRIPT, package_file, excluded_file, output],
            capture_output=True, text=True)
        text = output.read_text() if output.exists() else ""
        return result.returncode, result.stdout + result.stderr, text


def case(name, check):
    global failures
    try:
        passed = check()
    except Exception as error:                              # noqa: BLE001
        passed = False
        print(f"      {error}")
    print(f"  {'✓' if passed else '✗'} {name}")
    failures += not passed


failures = 0

case("stable 排除项从有效清单移除", lambda: (
    lambda result: result[0] == 0 and result[2] == "app-misc/a\napp-misc/c\n")(
        run("app-misc/a\napp-misc/b\napp-misc/c\n",
            "app-misc/b\tstable dependency unavailable\n")))

case("排除项必须写明原因", lambda: (
    lambda result: result[0] != 0 and "needs a tab and a reason" in result[1])(
        run("app-misc/a\n", "app-misc/a\n")))

case("排除项必须仍在共用清单", lambda: (
    lambda result: result[0] != 0 and "not present in package list" in result[1])(
        run("app-misc/a\n", "app-misc/b\tnot stable\n")))

case("排除清单必须排序", lambda: (
    lambda result: result[0] != 0 and "exclusions are not sorted" in result[1])(
        run("app-misc/a\napp-misc/b\n",
            "app-misc/b\tnot stable\napp-misc/a\tnot stable\n")))

case("排除清单不能重复", lambda: (
    lambda result: result[0] != 0 and "duplicate exclusion" in result[1])(
        run("app-misc/a\n", "app-misc/a\tone\napp-misc/a\ttwo\n")))

case("共用清单不能重复", lambda: (
    lambda result: result[0] != 0 and "duplicate package" in result[1])(
        run("app-misc/a\napp-misc/a\n", "")))

case("失败时保留上一份有效清单", lambda: (
    lambda result: result[0] != 0 and result[2] == "app-misc/previous\n")(
        run("app-misc/a\n", "app-misc/b\tnot stable\n", "app-misc/previous\n")))

sys.exit(1 if failures else 0)
