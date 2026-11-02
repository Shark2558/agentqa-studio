from agentqa.agents import srs_analyst


def test_demo_srs_is_read_into_requirements_and_rules(demo):
    p, s = demo
    out = srs_analyst.analyze(p, s, use_llm=False)
    assert out["requirements"] >= 25
    rules = {(r["field"], r["kind"]): r["value"] for r in s.all("SELECT * FROM rules") if r["field"]}
    assert rules[("Applicant Name", "max_length")] == {"max": 50}
    assert rules[("Mobile Number", "starts_with")] == {"chars": ["6", "7", "8", "9"]}
    assert rules[("Supporting Document", "file_types")] == {"types": ["pdf", "jpg", "png"]}
    assert rules[("Supporting Document", "file_max_size")] == {"kb": 2048}
    assert ("Remarks", "tbd") in rules, "a TBD in the SRS becomes a question, not a test"
    assert out["ambiguous"] >= 1, "vague words such as 'appropriate' are flagged"


def test_vague_words_are_flagged():
    flags = srs_analyst.ambiguity_flags("The system shall show appropriate error messages quickly. Remarks: TBD")
    terms = {f["term"].lower() for f in flags}
    assert {"appropriate", "quickly"} & terms
    assert any("tbd" in t for t in terms)
