import yaml

from agentqa import yamledit

TEXT = """# Demo project
project: Demo
workflows:
  # the maker-checker flow
  - id: WF-01
    steps:
      - role: clerk
        click: "text=Verify {app_id}"   # the clerk's button
  - id: WF-02
    steps:
      - role: clerk
        click: "text=Verify {app_id}"
"""


def test_workflow_value_replaced_in_one_workflow_only_and_comments_kept(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(TEXT, encoding="utf-8")
    assert yamledit.replace_in_workflow(f, "WF-01", "text=Verify {app_id}", "text=Mark verified {app_id}")
    out = f.read_text(encoding="utf-8")
    assert "# the clerk's button" in out and "# the maker-checker flow" in out
    cfg = yaml.safe_load(out)
    assert cfg["workflows"][0]["steps"][0]["click"] == "text=Mark verified {app_id}"
    assert cfg["workflows"][1]["steps"][0]["click"] == "text=Verify {app_id}"


def test_unknown_workflow_changes_nothing(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(TEXT, encoding="utf-8")
    assert not yamledit.replace_in_workflow(f, "WF-99", "text=Verify {app_id}", "x")
    assert f.read_text(encoding="utf-8") == TEXT
