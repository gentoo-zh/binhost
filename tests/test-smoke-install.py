#!/usr/bin/env python3

import copy
import contextlib
import importlib.util
import io
import json
import pathlib
import stat
import sys
import tempfile
from types import SimpleNamespace


ROOT = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
        pathlib.Path(__file__).resolve().parent.parent)
SCRIPT = ROOT / "build" / "smoke-install.py"
SPEC = importlib.util.spec_from_file_location("smoke_install", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

failed = 0


def check(name, actual, expected=True):
    global failed
    if actual == expected:
        print("  ✓ " + name)
        return
    print(f"  ✗ {name}\n      得到 {actual!r}，应为 {expected!r}")
    failed += 1


def packages(count=64):
    result = []
    for number in range(count):
        repo = "gentoo-zh" if number % 2 else "gentoo"
        result.append({
            "atom": f"=app-misc/package-{number}-1::{repo}",
            "cpv": f"app-misc/package-{number}-1",
            "repo": repo,
            "path": f"app-misc/package-{number}/package-{number}-1-1.gpkg.tar",
            "size": (number + 1) * 1000,
            "slot": "0",
            "cp": f"app-misc/package-{number}",
        })
    return result


def index(directory, items):
    stanzas = []
    for item in items:
        stanzas.append("\n".join((
            f"CPV: {item['cpv']}",
            f"PATH: {item['path']}",
            f"SIZE: {item['size']}",
            "SLOT: 0",
            f"REPO: {item['repo']}",
        )))
    text = (f"PACKAGES: {len(items)}\n"
            'REPO_REVISIONS: {"gentoo": "tree-a", "gentoo-zh": "overlay-a"}\n\n'
            + "\n\n".join(stanzas) + "\n")
    pathlib.Path(directory, "Packages").write_text(text)


def fake_docker(directory, payload=None, sleep=False, exit_code=0):
    script = pathlib.Path(directory, "docker")
    if sleep:
        run = "printf 'container started\\n'; sleep 5"
    elif payload is not None:
        encoded = json.dumps(payload, ensure_ascii=False).replace("'", "'\"'\"'")
        run = f"printf '%s\\n' '{encoded}'"
    else:
        run = "true"
    hashbang = "#!"
    script.write_text("\n".join((
        hashbang + "/bin/bash",
        "if [[ $1 == rm ]]; then exit 0; fi",
        run,
        f"exit {exit_code}",
        "",
    )))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def args(directory, docker, timeout=10, seconds_per_package=0):
    directory = pathlib.Path(directory)
    stage = directory / "stage"
    stage.mkdir()
    items = packages(16)
    index(stage, items)
    changed = directory / "changed.txt"
    changed.write_text("")
    package_use = directory / "package.use"
    package_use.write_text("app-misc/example test\n")
    tree = directory / "gentoo"
    overlay = directory / "gentoo-zh"
    gentoo_binpkgs = directory / "gentoo-binpkgs"
    gentoo_index = directory / "gentoo-Packages"
    tree.mkdir()
    overlay.mkdir()
    gentoo_binpkgs.mkdir()
    gentoo_index.write_text("PACKAGES: 0\n\n")
    return SimpleNamespace(
        channel="stable", stage=str(stage), changed_list=str(changed),
        report=str(directory / "smoke-install.json"),
        alert=str(directory / "smoke-alert.txt"), base="test-base",
        tree=str(tree), overlay=str(overlay), gentoo_binpkgs=str(gentoo_binpkgs),
        gentoo_index=str(gentoo_index), package_use=str(package_use),
        docker=str(docker), strict_limit=24, rotating_limit=8, timeout=timeout,
        seconds_per_package=seconds_per_package,
    )


print("== 确定抽样")
items = packages()
changed = [item["path"] for item in items[:30]]
revisions = {"gentoo": "tree-a", "gentoo-zh": "overlay-a"}
first = smoke.select_packages("stable", revisions, copy.deepcopy(items), changed)
second = smoke.select_packages("stable", revisions, copy.deepcopy(items), changed)
other_channel = smoke.select_packages(
    "unstable", revisions, copy.deepcopy(items), changed)
other_revision = smoke.select_packages(
    "stable", {**revisions, "gentoo": "tree-b"}, copy.deepcopy(items), changed)
other_items = copy.deepcopy(items)
other_items[-1]["atom"] = "=app-misc/replacement-1::gentoo-zh"
other_items[-1]["cpv"] = "app-misc/replacement-1"
other_cpv = smoke.select_packages("stable", revisions, other_items, changed)
check("同一组输入得到相同顺序", first, second)
check("每频道最多抽样 32 个", len(first), 32)
check("新签或重签最多取 24 个", sum(item["changed"] for item in first), 24)
check("未变更包轮替抽验 8 个", sum(not item["changed"] for item in first), 8)
check("两个仓库都在样本中", {item["repo"] for item in first},
      {"gentoo", "gentoo-zh"})
check("频道变化会改变抽样", first != other_channel)
check("仓库版本变化会改变抽样", first != other_revision)
check("CPV 集合变化会改变抽样", first != other_cpv)

same_slot = [
    {
        "atom": "=app-misc/same-1::gentoo-zh",
        "cpv": "app-misc/same-1",
        "repo": "gentoo-zh",
        "path": "app-misc/same/same-1-1.gpkg.tar",
        "size": 1000,
        "slot": "0",
        "cp": "app-misc/same",
    },
    {
        "atom": "=app-misc/same-2::gentoo-zh",
        "cpv": "app-misc/same-2",
        "repo": "gentoo-zh",
        "path": "app-misc/same/same-2-1.gpkg.tar",
        "size": 2000,
        "slot": "0",
        "cp": "app-misc/same",
    },
]
preferred = smoke.select_packages(
    "stable", revisions, copy.deepcopy(same_slot), [same_slot[1]["path"]],
    strict_limit=1, rotating_limit=1)
check("同 slot 抽样优先选择本轮新签版本",
      [item["atom"] for item in preferred], [same_slot[1]["atom"]])

print("== 失败分类")
check("严格预检通过后等待实际安装",
      smoke.classify(0), "strict-eligible")
check("源码回退单独归类",
      smoke.classify(1, 0, "[ebuild  N ] app-misc/a-1"), "source-fallback")
check("两个解析方式都失败时归类为解析失败",
      smoke.classify(1, 1, ""), "resolver-failed")
check("实际安装失败单独归类",
      smoke.classify(0, install_rc=1), "gpkg-install-failed")
check("实际安装成功单独归类",
      smoke.classify(0, install_rc=0), "installed")
check("严格预检使用 -K 而不是 -k",
      "-1K" in smoke.strict_command("=a/b-1::gentoo") and
      "-1k" not in smoke.strict_command("=a/b-1::gentoo"))
check("严格预检明确检查 USE 与依赖变化",
      {"--binpkg-respect-use=y", "--binpkg-changed-deps=y"}.issubset(
          smoke.strict_command("=a/b-1::gentoo")))
check("实际安装在一个批次内完成",
      smoke.install_command(["=a/b-1::gentoo", "=a/c-1::gentoo"])[-2:],
      ["=a/b-1::gentoo", "=a/c-1::gentoo"])

calls = []


def partial_install(command):
    calls.append(command)
    atoms = command[command.index("--binpkg-changed-deps=y") + 1:]
    if len(atoms) > 1:
        return 1, "batch conflict"
    return (0, "installed") if atoms[0] == "=a/b-1::gentoo" else (1, "broken gpkg")


installed, install_failed = smoke.install_selected(
    ["=a/b-1::gentoo", "=a/c-1::gentoo"], partial_install)
check("批次失败后逐包重试", len(calls), 3)
check("逐包重试按实际退出码记录成功", installed, ["=a/b-1::gentoo"])
check("逐包重试按实际退出码记录失败", install_failed,
      [{"atom": "=a/c-1::gentoo", "output": "broken gpkg"}])

print("== 容器内安装")
with tempfile.TemporaryDirectory() as directory:
    sandbox = pathlib.Path(directory)
    selection = sandbox / "selection.json"
    selected_atom = "=app-misc/selected-1::gentoo-zh"
    selection.write_text(json.dumps([{"atom": selected_atom}]))
    gentoo_packages = sandbox / "run" / "binhost-smoke" / "gentoo-packages"
    gentoo_packages.mkdir(parents=True)
    (gentoo_packages / "package.gpkg.tar").write_text("gpkg")
    real_path = pathlib.Path

    def sandbox_path(*parts):
        path = real_path(*parts)
        try:
            path.relative_to(sandbox)
        except ValueError:
            if path.is_absolute():
                return sandbox / path.relative_to("/")
        return path

    emerge_calls = []

    def successful_emerge(command):
        emerge_calls.append(command)
        return 0, "ok"

    original_pathlib = smoke.pathlib
    original_run_emerge = smoke.run_emerge
    original_install_selected = smoke.install_selected
    output = io.StringIO()
    try:
        smoke.pathlib = SimpleNamespace(Path=sandbox_path)
        smoke.run_emerge = successful_emerge
        smoke.install_selected = lambda atoms: original_install_selected(
            atoms, successful_emerge)
        with contextlib.redirect_stdout(output):
            smoke.inside(selection)
    finally:
        smoke.pathlib = original_pathlib
        smoke.run_emerge = original_run_emerge
        smoke.install_selected = original_install_selected
    inside_result = json.loads(output.getvalue())
    install_calls = [command for command in emerge_calls if "-1vK" in command]
    check("容器内报告实际安装选中的 atom",
          inside_result["installed"], [selected_atom])
    check("容器内安装命令使用选中的 atom",
          [command[-1] for command in install_calls], [selected_atom])

print("== 官方快取边界")
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    package_root = root / "packages"
    package = package_root / "app-misc" / "present" / "present-1-1.gpkg.tar"
    package.parent.mkdir(parents=True)
    package.write_text("gpkg")
    source = root / "Packages"
    source.write_text("""PACKAGES: 2

CPV: app-misc/present-1
PATH: app-misc/present/present-1-1.gpkg.tar

CPV: app-misc/missing-1
PATH: app-misc/missing/missing-1-1.gpkg.tar
""")
    output = root / "filtered"
    count = smoke.filter_available_index(source, package_root, output)
    filtered = output.read_text()
    check("离线索引只保留已有 gpkg", count, 1)
    check("离线索引移除缺少的路径", "missing-1" not in filtered)
    check("离线索引修正软件包数量", "PACKAGES: 1" in filtered)
    kept_paths = [line.removeprefix("PATH: ") for line in filtered.splitlines()
                  if line.startswith("PATH: ")]
    check("离线索引保留现有 gpkg 的 PATH", kept_paths,
          [package.relative_to(package_root).as_posix()])
    check("离线索引的 PATH 均存在于磁盘",
          all((package_root / path).is_file() for path in kept_paths))

print("== 容器边界")
with tempfile.TemporaryDirectory() as directory:
    docker = fake_docker(directory)
    probe = args(directory, docker)
    selection = pathlib.Path(directory, "selection.json")
    selection.write_text("[]")
    command = smoke.docker_command(probe, selection, "smoke-test")
    mounts = [command[index + 1] for index, value in enumerate(command[:-1])
              if value == "-v"]
    destinations = {value.rsplit(":", 2)[-2] for value in mounts}
    required = {
        "/var/db/repos/gentoo",
        "/var/db/repos/gentoo-zh",
        "/var/cache/binpkgs",
        "/run/binhost-smoke/gentoo-packages",
        "/run/binhost-smoke/gentoo-Packages",
        "/usr/local/bin/smoke-install.py",
        "/run/binhost-smoke/selection.json",
        "/run/binhost-smoke/package.use",
    }
    check("容器禁用网络", "--network" in command and
          command[command.index("--network") + 1] == "none")
    check("容器带齐仓库、索引与暂存包挂载", required <= destinations)
    check("仓库与暂存包都只读挂载",
          bool(mounts) and all(value.endswith(":ro") for value in mounts))
    check("容器不使用特权模式或设备直通",
          "--privileged" not in command and "--device" not in command)

print("== 建置接线")
container_script = (ROOT / "build" / "build-container.sh").read_text()
smoke_start = container_script.index('python3 "$(dirname "$0")/smoke-install.py"')
deps = container_script.index('python3 "$(dirname "$0")/verify-deps.py"')
versions = container_script.index('python3 "$(dirname "$0")/check-versions.py"')
generation = container_script.index('python3 "$(dirname "$0")/generation.py" create')
check("冒烟测试在依赖与版本验证之后", smoke_start > deps and smoke_start > versions)
check("冒烟测试在 generation 建立之前", smoke_start < generation)
smoke_block = container_script[smoke_start:generation]
check("冒烟测试接线不建立发布阻挡文件",
      "publish-blocked.txt" not in smoke_block)
check("签章变更清单保留到冒烟测试之后",
      container_script.index('rm -f "${STAGE}.new/.signed-packages"') > smoke_start)

print("== 报告、告警与非阻挡行为")
base_payload = {
    "strict_eligible": [], "source_fallback": [], "resolver_failed": [],
    "installed": [], "gpkg_install_failed": [], "harness_failed": [],
}
for category in ("source_fallback", "resolver_failed", "gpkg_install_failed",
                 "harness_failed"):
    with tempfile.TemporaryDirectory() as directory:
        payload = copy.deepcopy(base_payload)
        payload[category] = [{"atom": "=app-misc/example-1::gentoo-zh"}]
        docker = fake_docker(directory, payload=payload)
        probe = args(directory, docker)
        smoke.run(probe)
        report = json.loads(pathlib.Path(probe.report).read_text())
        check(f"{category} 写进结构化报告", len(report[category]), 1)
        check(f"{category} 不建立发布阻挡文件",
              not pathlib.Path(probe.stage, "publish-blocked.txt").exists())
        should_alert = category in {"gpkg_install_failed", "harness_failed"}
        check(f"{category} 的告警范围正确",
              pathlib.Path(probe.alert).exists(), should_alert)

with tempfile.TemporaryDirectory() as directory:
    alert = pathlib.Path(directory, "smoke-alert.txt")
    result = copy.deepcopy(base_payload)
    result["gpkg_install_failed"] = [{}, {}]
    result["harness_failed"] = [{}]
    result["report_path"] = str(pathlib.Path(directory, "smoke-install.json"))
    smoke.write_alert(alert, result)
    text = alert.read_text()
    check("告警分别写出安装失败与测试环境失败数量",
          text, f"gpkg 安装失败 2 个，测试环境失败 1 项；"
                f"详见 {result['report_path']}\n")

print("== 容器自己失败")
# The fake docker returns a payload with status 0 everywhere else, so nothing
# exercised the branch that reads a non-zero container exit. A crashed
# container has to land in harness_failed and alert, not disappear.
with tempfile.TemporaryDirectory() as directory:
    docker = fake_docker(directory, payload=copy.deepcopy(base_payload),
                         exit_code=3)
    probe = args(directory, docker)
    smoke.run(probe)
    report = json.loads(pathlib.Path(probe.report).read_text())
    check("容器非零退出归类为测试环境失败", len(report["harness_failed"]), 1)
    check("报告写出容器的退出码",
          "3" in report["harness_failed"][0]["reason"])
    check("容器非零退出不算软件包损坏", report["gpkg_install_failed"], [])
    check("容器非零退出会告警", pathlib.Path(probe.alert).is_file())
    check("容器非零退出仍不建立发布阻挡文件",
          not pathlib.Path(probe.stage, "publish-blocked.txt").exists())

print("== 逾时")
with tempfile.TemporaryDirectory() as directory:
    docker = fake_docker(directory, sleep=True)
    probe = args(directory, docker, timeout=0.05)
    smoke.run(probe)
    report = json.loads(pathlib.Path(probe.report).read_text())
    check("逾时归类为测试环境失败", len(report["harness_failed"]), 1)
    check("逾时保留容器已有输出",
          "container started" in report["harness_failed"][0]["output"])
    check("逾时不会归类为软件包损坏", report["gpkg_install_failed"], [])
    check("逾时产生告警", pathlib.Path(probe.alert).is_file())
    check("逾时仍不建立发布阻挡文件",
          not pathlib.Path(probe.stage, "publish-blocked.txt").exists())

print("== 逾时预算跟着抽样数走")
with tempfile.TemporaryDirectory() as directory:
    # One container installs the whole sample, so a fixed budget covers 9 and 32
    # packages alike. The unstable channel lost every result twice this way.
    docker = fake_docker(directory)
    probe = args(directory, docker, timeout=600, seconds_per_package=120)
    smoke.run(probe)
    report = json.loads(pathlib.Path(probe.report).read_text())
    check("抽样数决定预算", report["timeout_seconds"],
          120 * len(report["selected"]))
    check("预算记进报告，下次不用再猜", report["timeout_seconds"] > 600)

with tempfile.TemporaryDirectory() as directory:
    docker = fake_docker(directory)
    probe = args(directory, docker, timeout=600, seconds_per_package=1)
    smoke.run(probe)
    report = json.loads(pathlib.Path(probe.report).read_text())
    check("抽样很少时不低于下限", report["timeout_seconds"], 600)

with tempfile.TemporaryDirectory() as directory:
    docker = fake_docker(directory, sleep=True)
    probe = args(directory, docker, timeout=0.05, seconds_per_package=0)
    smoke.run(probe)
    report = json.loads(pathlib.Path(probe.report).read_text())
    check("逾时讯息带上抽样数",
          "个包" in report["harness_failed"][0]["reason"])

print()
print("  gpkg 安装冒烟测试：全部通过" if not failed else f"  {failed} 项不通过")
raise SystemExit(1 if failed else 0)
