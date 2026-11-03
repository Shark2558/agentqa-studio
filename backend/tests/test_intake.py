"""Intake: documents, typed requirements, accounts and the environment, shared by both UIs."""
from __future__ import annotations

import pytest
import yaml
from cryptography.fernet import Fernet

from agentqa.config import Project, init_project
from agentqa.orchestrator import NotFound, intake
from agentqa.orchestrator.projects import ROOT
from agentqa.store import Store

DEMO_DOCX = ROOT / "demo" / "srs" / "Demo_Certificate_Portal_SRS.docx"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())   # a throw-away vault key, not the owner's
    init_project(tmp_path / "p", "Portal", "https://portal.example")
    return Project(tmp_path / "p")


# ---- documents ----------------------------------------------------------------------------------

def test_file_names_are_reduced_to_a_bare_supported_name():
    assert intake.safe_name("../../etc/passwd.docx") == "passwd.docx"
    assert intake.safe_name("C:\\Users\\x\\My SRS (v2).PDF") == "My SRS (v2).PDF"
    with pytest.raises(intake.Unsupported):
        intake.safe_name("virus.exe")
    with pytest.raises(intake.Unsupported):
        intake.safe_name("...")


def test_an_oversized_upload_is_refused_before_it_is_written(project):
    with pytest.raises(intake.TooLarge):
        intake.save_document(project, "big.txt", b"x" * (intake.MAX_UPLOAD + 1))
    assert not (project.srs_dir / "big.txt").exists()


def test_a_saved_document_is_probed_right_away(project):
    out = intake.save_document(project, "Demo_Certificate_Portal_SRS.docx", DEMO_DOCX.read_bytes())
    assert out["name"] == "Demo_Certificate_Portal_SRS.docx" and out["status"] == "read" and out["segments"] > 20
    empty = intake.save_document(project, "notes.txt", b"\n\n")
    assert empty["status"] == "partly" and "no text" in empty["detail"]
    assert {d["name"] for d in intake.list_documents(project, Store(project.db_path))} == {"Demo_Certificate_Portal_SRS.docx", "notes.txt"}


def test_documents_can_be_removed_but_only_from_the_srs_folder(project):
    intake.save_document(project, "a.txt", b"The system shall work.")
    intake.delete_document(project, "a.txt")
    assert not (project.srs_dir / "a.txt").exists()
    with pytest.raises(NotFound):
        intake.delete_document(project, "../project.yaml")


def test_a_manual_test_sheet_goes_to_the_imports_folder(project):
    out = intake.save_document(project, "manual.csv", b"ID,Title\nTC-1,Login works\n", folder="imports")
    assert (project.root / "imports" / "manual.csv").exists() and out["folder"] == "imports"


# ---- typed requirements ---------------------------------------------------------------------------

def test_typed_text_becomes_one_numbered_requirement_per_item_with_clarifications_merged(project):
    typed = "- The portal must send an SMS.\n- Reports must be exported quickly."
    path = intake.save_typed(project, typed)
    assert path == project.srs_dir / intake.TYPED_NAME
    text = path.read_text(encoding="utf-8")
    assert "REQ-001: The portal must send an SMS." in text and "REQ-002: Reports must be exported quickly." in text
    intake.save_typed(project, typed, answers=[
        {"topic": "roles", "question": "Who will use this?", "answer": "Citizens and clerks."},
        {"topic": "vague", "question": "You wrote “quickly” (no measurable time limit). What is the rule?", "answer": "Within 5 seconds."},
        {"topic": "login", "question": "Do people sign in?", "answer": ""},                       # blank answers are dropped
    ])
    text = path.read_text(encoding="utf-8")
    assert "REQ-002: Reports must be exported quickly. (“quickly” means: Within 5 seconds.)" in text
    assert "REQ-003: Users of the application: Citizens and clerks." in text
    assert "Sign-in" not in text and text.count("REQ-") == 3


def test_the_srs_analyst_reads_the_typed_document_as_separate_requirements(project):
    from agentqa.agents import srs_analyst
    intake.save_typed(project, "- The portal must send an SMS.\n- Reports must be exported within 5 seconds.")
    srs_analyst.analyze(project, Store(project.db_path), use_llm=False)
    rows = Store(project.db_path).all("SELECT id, text, source_file FROM requirements ORDER BY seq")
    assert [r["id"] for r in rows] == ["REQ-001", "REQ-002"] and all(r["source_file"] == intake.TYPED_NAME for r in rows)


# ---- environment and accounts -----------------------------------------------------------------------

def test_the_environment_is_written_into_the_main_application(project):
    intake.set_environment(project, "Production")
    cfg = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    assert cfg["applications"]["main"]["environment"] == "Production"
    with pytest.raises(ValueError):
        intake.set_environment(project, "Moon")


def test_accounts_split_into_yaml_without_secrets_and_the_encrypted_vault(project):
    intake.save_accounts(project, [
        {"role": "clerk", "login_option": "Department Login", "method": "password", "username": "clerk1",
         "password": "Clerk@123", "aliases": ["Clerk", "Front office"]},
        {"role": "citizen", "login_option": "Citizen Login", "method": "mobile_otp", "mobile": "9847012345", "otp_source": "ask"},
    ])
    text = project.config_path.read_text(encoding="utf-8")
    assert "Clerk@123" not in text and "clerk1" not in text and "9847012345" not in text
    cfg = yaml.safe_load(text)
    assert cfg["roles"]["clerk"]["login_option"] == "Department Login" and cfg["roles"]["clerk"]["aliases"] == ["Clerk", "Front office"]
    assert cfg["roles"]["citizen"]["method"] == "mobile_otp"
    fresh = Project(project.root)
    assert fresh.vault.account("clerk")["password"] == "Clerk@123" and fresh.vault.account("citizen")["mobile"] == "9847012345"

    view = intake.accounts_view(fresh)
    assert view["no_login"] is False
    clerk = next(r for r in view["roles"] if r["role"] == "clerk")
    assert clerk["has_password"] is True and "password" not in clerk and clerk["username"] == "clerk1"
    citizen = next(r for r in view["roles"] if r["role"] == "citizen")
    assert citizen["mobile"] == "98******45"                       # identities come back masked


def test_no_login_clears_the_roles(project):
    intake.save_accounts(project, [], no_login=True)
    cfg = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    assert cfg["roles"] == {} and cfg["onboarding"]["no_login"] is True
    assert intake.accounts_view(Project(project.root)) == {"no_login": True, "roles": []}


def test_role_names_and_methods_are_validated(project):
    with pytest.raises(ValueError):
        intake.save_accounts(project, [{"role": "Bad Role!", "method": "password"}])
    with pytest.raises(ValueError):
        intake.save_accounts(project, [{"role": "clerk", "method": "telepathy"}])
