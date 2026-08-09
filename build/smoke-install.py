#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import time


SCHEMA = 1
STRICT_LIMIT = 24
ROTATING_LIMIT = 8
DEFAULT_TIMEOUT = 600


def parse_index(path):
    text = pathlib.Path(path).read_text()
    header, separator, body = text.partition("\n\n")
    if not separator:
        raise ValueError("Packages has no stanza separator")
    match = re.search(r"^REPO_REVISIONS: (.*)$", header, re.M)
    revisions = json.loads(match.group(1)) if match else {}
    if not isinstance(revisions, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in revisions.items()):
        raise ValueError("invalid REPO_REVISIONS")

    packages = []
    for stanza in body.split("\n\n"):
        fields = dict(re.findall(r"^([A-Z0-9_]+): (.*)$", stanza, re.M))
        if not all(fields.get(name) for name in ("CPV", "PATH", "REPO")):
            continue
        relative = pathlib.PurePosixPath(fields["PATH"])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
            raise ValueError(f"unsafe package path: {fields['PATH']}")
        try:
            size = int(fields.get("SIZE", "0"))
        except ValueError as error:
            raise ValueError(f"invalid package size: {fields.get('SIZE')}") from error
        packages.append({
            "atom": f"={fields['CPV']}::{fields['REPO']}",
            "cpv": fields["CPV"],
            "repo": fields["REPO"],
            "path": fields["PATH"],
            "size": size,
            "slot": fields.get("SLOT", "0").split("/", 1)[0],
            "cp": "/".join(relative.parts[:2]),
        })
    declared = re.search(r"^PACKAGES: ([0-9]+)$", header, re.M)
    if not declared or int(declared.group(1)) != len(packages):
        raise ValueError("Packages count does not match its stanzas")
    return revisions, packages


def digest(*parts):
    value = "\0".join(str(part) for part in parts)
    return hashlib.sha256(value.encode()).hexdigest()


def add_size_strata(packages):
    by_repo = {}
    for package in packages:
        by_repo.setdefault(package["repo"], []).append(package)
    for repo_packages in by_repo.values():
        ordered = sorted(repo_packages, key=lambda item: (item["size"], item["path"]))
        count = len(ordered)
        for index, package in enumerate(ordered):
            package["stratum"] = f"{package['repo']}:{min(3, index * 4 // count)}"


def balanced_pick(packages, limit, seed):
    if not packages or limit <= 0:
        return []
    groups = {}
    for package in packages:
        groups.setdefault(package["stratum"], []).append(package)
    for name in groups:
        groups[name].sort(key=lambda item: digest(seed, item["atom"], item["path"]))
    names = sorted(groups, key=lambda name: digest(seed, name))
    picked = []
    while names and len(picked) < limit:
        remaining = []
        for name in names:
            if len(picked) >= limit:
                break
            picked.append(groups[name].pop(0))
            if groups[name]:
                remaining.append(name)
        names = remaining
    return picked


def select_packages(channel, revisions, packages, changed_paths,
                    strict_limit=STRICT_LIMIT, rotating_limit=ROTATING_LIMIT):
    changed_paths = set(changed_paths)
    unknown = changed_paths - {package["path"] for package in packages}
    if unknown:
        raise ValueError(f"changed package is absent from index: {sorted(unknown)[0]}")

    material = "\n".join(sorted(
        f"{item['atom']}|{item['path']}|{item['size']}|{item['path'] in changed_paths}"
        for item in packages))
    seed = digest(channel, json.dumps(revisions, sort_keys=True), material)

    # Installing two versions of one slot in a shared container would create a
    # conflict caused by the sample itself. Prefer a changed package in each slot.
    grouped = {}
    for package in packages:
        grouped.setdefault((package["repo"], package["cp"], package["slot"]), []).append(
            package)
    candidates = []
    for key, values in sorted(grouped.items()):
        preferred = [item for item in values if item["path"] in changed_paths] or values
        candidates.append(min(preferred, key=lambda item: digest(seed, key, item["path"])))
    add_size_strata(candidates)

    changed = [item for item in candidates if item["path"] in changed_paths]
    unchanged = [item for item in candidates if item["path"] not in changed_paths]
    selected = balanced_pick(changed, strict_limit, seed + ":changed")
    selected += balanced_pick(unchanged, rotating_limit, seed + ":rotating")
    return [{**item, "changed": item["path"] in changed_paths} for item in selected]


def strict_command(atom):
    return ["emerge", "-p", "-1K", "--binpkg-respect-use=y",
            "--binpkg-changed-deps=y", atom]


def fallback_command(atom):
    return ["emerge", "-p", "-1k", "--binpkg-respect-use=y",
            "--binpkg-changed-deps=y", atom]


def install_command(atom):
    atoms = [atom] if isinstance(atom, str) else list(atom)
    return ["emerge", "-1vK", "--keep-going", "--binpkg-respect-use=y",
            "--binpkg-changed-deps=y", *atoms]


def classify(strict_rc, fallback_rc=None, fallback_output="", install_rc=None):
    if strict_rc == 0:
        if install_rc is None:
            return "strict-eligible"
        return "installed" if install_rc == 0 else "gpkg-install-failed"
    if fallback_rc == 0 and "[ebuild" in fallback_output:
        return "source-fallback"
    return "resolver-failed"


def tail(text, lines=20):
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def run_emerge(command):
    process = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=False)
    return process.returncode, process.stdout


def install_selected(atoms, runner=run_emerge):
    batch_rc, _batch_output = runner(install_command(atoms))
    if batch_rc == 0:
        return list(atoms), []

    installed = []
    failed = []
    for atom in atoms:
        install_rc, install_output = runner(install_command(atom))
        if install_rc == 0:
            installed.append(atom)
        else:
            failed.append({"atom": atom, "output": tail(install_output)})
    return installed, failed


def inside(selection_path):
    selected = json.loads(pathlib.Path(selection_path).read_text())
    package_use = pathlib.Path("/run/binhost-smoke/package.use")
    if package_use.exists():
        target = pathlib.Path("/etc/portage/package.use/binhost-smoke")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(package_use.read_text())
    binrepo = pathlib.Path("/etc/portage/binrepos.conf/binhost-smoke.conf")
    binrepo.parent.mkdir(parents=True, exist_ok=True)
    binrepo.write_text("""[binhost-smoke]
priority = 9999
location = /var/cache/binpkgs
sync-uri = file:///var/cache/binpkgs
verify-signature = true
""")
    gentoo = pathlib.Path("/var/cache/binhost/gentoo-smoke")
    gentoo.mkdir(parents=True, exist_ok=True)
    pathlib.Path(gentoo, "Packages").symlink_to(
        "/run/binhost-smoke/gentoo-Packages")
    for source in pathlib.Path("/run/binhost-smoke/gentoo-packages").iterdir():
        pathlib.Path(gentoo, source.name).symlink_to(source)
    pathlib.Path("/etc/portage/binrepos.conf/gentoo.conf").write_text("""[gentoo]
priority = 1
location = /var/cache/binhost/gentoo-smoke
sync-uri = file:///var/cache/binhost/gentoo-smoke
verify-signature = true
""")
    with pathlib.Path("/etc/portage/make.conf").open("a") as output:
        output.write('\nFEATURES="${FEATURES} binpkg-request-signature"\n')

    result = {
        "strict_eligible": [],
        "source_fallback": [],
        "resolver_failed": [],
        "installed": [],
        "gpkg_install_failed": [],
        "harness_failed": [],
    }
    for package in selected:
        atom = package["atom"]
        strict_rc, strict_output = run_emerge(strict_command(atom))
        if strict_rc == 0:
            result["strict_eligible"].append(atom)
            continue
        fallback_rc, fallback_output = run_emerge(fallback_command(atom))
        category = classify(strict_rc, fallback_rc, fallback_output)
        detail = {"atom": atom, "output": tail(fallback_output or strict_output)}
        result[category.replace("-", "_")].append(detail)

    if result["strict_eligible"]:
        installed, failed = install_selected(result["strict_eligible"])
        result["installed"] = installed
        result["gpkg_install_failed"] = failed
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def filter_available_index(index, packages, output):
    text = pathlib.Path(index).read_text()
    header, separator, body = text.partition("\n\n")
    if not separator:
        raise ValueError("Gentoo Packages has no stanza separator")
    kept = []
    for stanza in body.split("\n\n"):
        match = re.search(r"^PATH: (.+)$", stanza, re.M)
        if not match:
            continue
        relative = pathlib.PurePosixPath(match.group(1))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe Gentoo package path: {match.group(1)}")
        if pathlib.Path(packages, *relative.parts).is_file():
            kept.append(stanza)
    line = f"PACKAGES: {len(kept)}"
    if re.search(r"^PACKAGES: [0-9]+$", header, re.M):
        header = re.sub(r"^PACKAGES: [0-9]+$", line, header, flags=re.M)
    else:
        raise ValueError("Gentoo Packages has no package count")
    pathlib.Path(output).write_text(
        header + "\n\n" + "\n\n".join(kept) + ("\n" if kept else ""))
    return len(kept)


def docker_command(args, selection, container_name, gentoo_index=None):
    gentoo_index = gentoo_index or args.gentoo_index
    command = shlex.split(args.docker) + [
        "run", "--rm", "--name", container_name,
        "--network", "none", "--security-opt=no-new-privileges",
        "-v", f"{pathlib.Path(args.tree).resolve()}:/var/db/repos/gentoo:ro",
        "-v", f"{pathlib.Path(args.overlay).resolve()}:/var/db/repos/gentoo-zh:ro",
        "-v", f"{pathlib.Path(args.stage).resolve()}:/var/cache/binpkgs:ro",
        "-v", (f"{pathlib.Path(args.gentoo_binpkgs).resolve()}:"
               "/run/binhost-smoke/gentoo-packages:ro"),
        "-v", (f"{pathlib.Path(gentoo_index).resolve()}:"
               "/run/binhost-smoke/gentoo-Packages:ro"),
        "-v", f"{pathlib.Path(__file__).resolve()}:/usr/local/bin/smoke-install.py:ro",
        "-v", f"{pathlib.Path(selection).resolve()}:/run/binhost-smoke/selection.json:ro",
    ]
    if args.package_use:
        command += ["-v", (f"{pathlib.Path(args.package_use).resolve()}:"
                           "/run/binhost-smoke/package.use:ro")]
    command += [args.base, "python3", "/usr/local/bin/smoke-install.py",
                "--inside", "/run/binhost-smoke/selection.json"]
    return command


def empty_result(channel, revisions, selected):
    return {
        "schema": SCHEMA,
        "channel": channel,
        "revisions": revisions,
        "selected": selected,
        "strict_eligible": [],
        "source_fallback": [],
        "resolver_failed": [],
        "installed": [],
        "gpkg_install_failed": [],
        "harness_failed": [],
        "duration_seconds": 0,
    }


def write_result(path, result):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n")
    temporary.replace(path)


def write_alert(path, result):
    path = pathlib.Path(path)
    path.unlink(missing_ok=True)
    failed = len(result["gpkg_install_failed"])
    harness = len(result["harness_failed"])
    if failed or harness:
        path.write_text(
            f"gpkg 安装失败 {failed} 个，测试环境失败 {harness} 项；"
            f"详见 {result['report_path']}\n")


def summary(result):
    return (f">>> gpkg 安装冒烟测试：抽样 {len(result['selected'])} 个，"
            f"严格通过 {len(result['strict_eligible'])} 个，"
            f"源码回退 {len(result['source_fallback'])} 个，"
            f"解析失败 {len(result['resolver_failed'])} 个，"
            f"安装失败 {len(result['gpkg_install_failed'])} 个，"
            f"环境失败 {len(result['harness_failed'])} 项，"
            f"用时 {result['duration_seconds']} 秒")


def run(args):
    started = time.monotonic()
    revisions, packages = parse_index(pathlib.Path(args.stage) / "Packages")
    changed = [line.strip() for line in pathlib.Path(args.changed_list).read_text().splitlines()
               if line.strip()]
    selected = select_packages(args.channel, revisions, packages, changed,
                               args.strict_limit, args.rotating_limit)
    result = empty_result(args.channel, revisions, selected)
    result["report_path"] = str(pathlib.Path(args.report))
    pathlib.Path(args.alert).unlink(missing_ok=True)

    if selected:
        report_parent = pathlib.Path(args.report).resolve().parent
        report_parent.mkdir(parents=True, exist_ok=True)
        container = f"binhost-smoke-{args.channel}-{os.getpid()}"
        with tempfile.TemporaryDirectory(prefix=".smoke-", dir=report_parent) as temporary:
            selection = pathlib.Path(temporary) / "selection.json"
            selection.write_text(json.dumps(selected, ensure_ascii=False))
            gentoo_index = pathlib.Path(temporary) / "gentoo-Packages"
            filter_available_index(args.gentoo_index, args.gentoo_binpkgs,
                                   gentoo_index)
            command = docker_command(args, selection, container, gentoo_index)
            try:
                process = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, check=False,
                                         timeout=args.timeout)
                if process.returncode:
                    result["harness_failed"].append({
                        "reason": f"container exited with {process.returncode}",
                        "output": tail(process.stdout),
                    })
                else:
                    payload = json.loads(process.stdout)
                    for name in ("strict_eligible", "source_fallback", "resolver_failed",
                                 "installed", "gpkg_install_failed", "harness_failed"):
                        result[name] = payload[name]
            except subprocess.TimeoutExpired as error:
                subprocess.run(shlex.split(args.docker) + ["rm", "-f", container],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
                result["harness_failed"].append({
                    "reason": f"container exceeded {args.timeout} seconds",
                    "output": tail(error.stdout or ""),
                })
            except (json.JSONDecodeError, OSError, KeyError) as error:
                result["harness_failed"].append({"reason": str(error), "output": ""})

    result["duration_seconds"] = round(time.monotonic() - started)
    write_result(args.report, result)
    write_alert(args.alert, result)
    print(summary(result))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inside")
    parser.add_argument("--channel", choices=("stable", "unstable"))
    parser.add_argument("--stage")
    parser.add_argument("--changed-list")
    parser.add_argument("--report")
    parser.add_argument("--alert")
    parser.add_argument("--base")
    parser.add_argument("--tree")
    parser.add_argument("--overlay")
    parser.add_argument("--gentoo-binpkgs")
    parser.add_argument("--gentoo-index")
    parser.add_argument("--package-use")
    parser.add_argument("--docker", default=os.environ.get("SMOKE_DOCKER", "docker"))
    parser.add_argument("--strict-limit", type=int, default=STRICT_LIMIT)
    parser.add_argument("--rotating-limit", type=int, default=ROTATING_LIMIT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    if args.inside:
        return inside(args.inside)
    required = ("channel", "stage", "changed_list", "report", "alert", "base",
                "tree", "overlay", "gentoo_binpkgs", "gentoo_index", "package_use")
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        parser.error("missing: " + ", ".join(missing))
    try:
        return run(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result = empty_result(args.channel, {}, [])
        result["report_path"] = str(pathlib.Path(args.report))
        result["harness_failed"].append({"reason": str(error), "output": ""})
        write_result(args.report, result)
        write_alert(args.alert, result)
        print(summary(result))
        return 0


if __name__ == "__main__":
    sys.exit(main())
