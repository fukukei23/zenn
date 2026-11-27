"""test_workflow_git_order.py — workflowのgit命令順序回帰テスト

2026-11-27実測事故: discover.ymlの「Push approval state json」が
pull --rebase → add → commit の順序のため、前ステップ（notifier_send_approval.py）が
書いたunstagedなjsonでpull --rebaseが拒否されexit 128＝jsonがrunner上で喪失した。
publish.ymlの「Push approval state json (reapproval)」も同型。
ymlのgit命令順序はCI実機でしか発光しないため、yml構造の機械検証で防ぐ。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows",
)


def _load_run_text(workflow_file, job_name, step_name):
    wf = yaml.safe_load(open(os.path.join(WF_DIR, workflow_file)))
    steps = wf["jobs"][job_name]["steps"]
    for s in steps:
        if s.get("name") == step_name:
            return s["run"]
    raise AssertionError(f"step not found: {step_name} in {workflow_file}")


class TestGitCommandOrder:
    def test_discover_json_push_commits_before_rebase(self):
        """jsonのadd/commitはpull --rebaseの前に実施すること（unstaged拒否事故の回帰防止）。"""
        run = _load_run_text("discover.yml", "discover", "Push approval state json")
        assert run.index("git add docs/discord_messages.json") < run.index("git pull --rebase")

    def test_publish_json_push_commits_before_rebase(self):
        """同型（publish.yml reapproval）もadd/commitをpull --rebaseの前に実施すること。"""
        run = _load_run_text(
            "publish.yml", "publish", "Push approval state json (reapproval)")
        assert run.index("git add docs/discord_messages.json") < run.index("git pull --rebase")
