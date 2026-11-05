import pytest
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


# ---- M1.4 Phase C: the new value comes from the tested site (a button's label), so it is hostile until proven not ----

HOSTILE = [
    'Mark " verified',                         # a double quote
    "it's done",                                # a single quote
    "Mark\nproject: Hijacked",                  # a newline that would start a key of its own
    "Verify: x",                                # a colon and a space
    "{oops} # not a comment",                   # flow braces and a hash
    "back\\slash \\1 \\n",                       # backslashes
    "yes",                                      # a word YAML reads as true
    "123",                                      # a number
    "ശരി",                                     # Malayalam (DEMO_LANG=ml)
    "bell\x07 del\x7f c1\x85\x9c",             # characters YAML may not hold as they are
    "line sep ﻿bom",                  # what YAML reads as a line break or a byte-order mark
    "  padded  ",
]


def _expected(cfg: dict, workflow: int, value: str) -> dict:
    import copy
    out = copy.deepcopy(cfg)
    out["workflows"][workflow]["steps"][0]["click"] = value
    return out


@pytest.mark.parametrize("new", HOSTILE)
def test_a_hostile_new_value_leaves_valid_yaml_with_only_that_value_changed(tmp_path, new):
    f = tmp_path / "project.yaml"
    f.write_text(TEXT, encoding="utf-8")
    before = yaml.safe_load(TEXT)
    assert yamledit.replace_in_workflow(f, "WF-01", "text=Verify {app_id}", new)
    out = f.read_text(encoding="utf-8")
    assert yaml.safe_load(out) == _expected(before, 0, new)
    assert "# the clerk's button" in out and "# the maker-checker flow" in out


def test_a_value_found_only_inside_a_longer_one_changes_nothing(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(TEXT, encoding="utf-8")
    assert not yamledit.replace_in_workflow(f, "WF-01", "text=Verify", "text=Mark")
    assert f.read_text(encoding="utf-8") == TEXT


FILL = """workflows:
  - id: WF-01
    steps:
      - role: citizen
        goto: /apply
        fill: {mobile: "{mobile}", name: "A"}   # the form
      - role: mobile
        click: "text=Submit"
"""


@pytest.mark.parametrize("new_key", ["mobile_no", "mob\\1ile", "a: b", "x\ny: z", "user[name]"])
def test_a_renamed_fill_field_changes_only_that_key(tmp_path, new_key):
    f = tmp_path / "project.yaml"
    f.write_text(FILL, encoding="utf-8")
    before = yaml.safe_load(FILL)
    assert yamledit.rename_fill_key(f, "WF-01", "mobile", new_key)        # quoted when it is not a plain name
    after = yaml.safe_load(f.read_text(encoding="utf-8"))
    fill = before["workflows"][0]["steps"][0]["fill"]
    fill[new_key] = fill.pop("mobile")
    assert after == before and "# the form" in f.read_text(encoding="utf-8")
    assert after["workflows"][0]["steps"][1]["role"] == "mobile"             # a value spelled like the key stays


TWO_STEPS = """workflows:
  - id: WF-01
    steps:
      - role: citizen
        city: Pune
      - role: clerk
        city: Pune   # the clerk's form
"""


def test_a_workflow_value_is_replaced_in_the_heals_own_step_and_key(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(TWO_STEPS, encoding="utf-8")
    assert yamledit.replace_in_workflow(f, "WF-01", "Pune", "Mumbai", step=2, key="city")
    cfg = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert [s["city"] for s in cfg["workflows"][0]["steps"]] == ["Pune", "Mumbai"]
    f.write_text(TWO_STEPS, encoding="utf-8")
    assert not yamledit.replace_in_workflow(f, "WF-01", "Pune", "Mumbai", step=3, key="city")
    assert f.read_text(encoding="utf-8") == TWO_STEPS


def test_a_rename_onto_a_key_the_form_already_has_changes_nothing(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(FILL, encoding="utf-8")
    assert not yamledit.rename_fill_key(f, "WF-01", "mobile", "name")         # would lose the "name" value
    assert f.read_text(encoding="utf-8") == FILL
