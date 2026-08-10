#!/usr/bin/env python3

import pathlib

from active_source import active_text


ROOT = pathlib.Path(__file__).resolve().parent.parent

for name in ("newcomers.yml", "retire.yml", "moves.yml"):
    text = active_text(
        (ROOT / ".github" / "workflows" / name).read_text(), "yaml")
    assert "actions: write" in text
    pushed = text.index('git push -q origin "${branch}"')
    dispatched = text.index('gh workflow run validate.yml --ref "${branch}"')
    opened = text.index("gh pr create --base master")
    assert pushed < dispatched < opened

newcomers = (ROOT / ".github" / "workflows" / "newcomers.yml").read_text()
assert "关闭本 PR 并保留远端分支可停止重复提案" in newcomers
assert "删除远端分支 \\`${branch}\\` 后，下一次检查会重新提出" in newcomers
assert "否则每天会重新提出" not in newcomers

retire = (ROOT / ".github" / "workflows" / "retire.yml").read_text()
assert "关闭本 PR 并保留远端分支会停止该软件包的重复提案" in retire
assert "删除远端分支 \\`${branch}\\` 后，下一次检查会重新判断是否需要提出" in retire

validate = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
assert "workflow_dispatch:" in validate
assert "github.event_name == 'workflow_dispatch'" in validate

print("  自动 PR 仅在 validate dispatch 受理后建立")
