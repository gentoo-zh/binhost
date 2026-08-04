#!/usr/bin/env python3

import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent

for name in ("newcomers.yml", "retire.yml", "moves.yml"):
    text = (ROOT / ".github" / "workflows" / name).read_text()
    assert "actions: write" in text
    pushed = text.index('git push -q origin "${branch}"')
    dispatched = text.index('gh workflow run validate.yml --ref "${branch}"')
    opened = text.index("gh pr create --base master")
    assert pushed < dispatched < opened

validate = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
assert "workflow_dispatch:" in validate
assert "github.event_name == 'workflow_dispatch'" in validate

print("  自动 PR 仅在 validate dispatch 受理后建立")
