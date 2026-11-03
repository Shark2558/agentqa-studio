"""Intake: what the onboarding wizard (and the old dashboard) store for a project — requirement documents, typed
requirements, the environment and the test accounts. One set of checks for both UIs."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import yaml

from agentqa import documents
from agentqa.config import Project
from agentqa.orchestrator import NotFound
from agentqa.store import Store
from agentqa.vault import METHODS, OTP_SOURCES, SECRET_FIELDS, mask
from agentqa.yamledit import replace_top_block

MAX_UPLOAD = 50 * 1024 * 1024
MAX_UNPACKED = 200 * 1024 * 1024          # what a zipped Office file may expand to before the readers see it
MAX_NAME = 120
ZIPPED = {".docx", ".xlsx", ".xlsm"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
TYPED_NAME = "typed-requirements.md"
FOLDERS = {"srs": "requirement documents", "imports": "manual test sheets"}
ENVIRONMENTS = ("Development", "Test / QA", "UAT", "Staging", "Production")
ROLE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
ROLE_FIELDS = ("login_option", "method", "username", "mobile", "email", "otp_source", "aliases", "app")
IDENTITY_FIELDS = ("username", "mobile", "email")          # shown back masked; never the SECRET_FIELDS
_NAME_BAD = re.compile(r"[^\w .()\[\]&,+'-]")


class Unsupported(ValueError):
    """Not a document type the readers know."""


class TooLarge(ValueError):
    """Over MAX_UPLOAD bytes."""


# ---- documents ----------------------------------------------------------------------------------

def safe_name(filename: str) -> str:
    """A bare file name (no folders, no odd characters) with a supported extension, or Unsupported."""
    name = _NAME_BAD.sub("_", Path(str(filename).replace("\\", "/")).name).strip(" .")
    if not name or name.startswith(".") or len(name) > MAX_NAME or Path(name).stem.lower() in WINDOWS_RESERVED:
        raise Unsupported(f"{name[:40]!r}: the file needs a plain name of at most {MAX_NAME} characters")
    if Path(name).suffix.lower() not in documents.SUPPORTED:
        raise Unsupported(f"{name}: not a supported document type")
    return name


def check_unpacked_size(name: str, data: bytes) -> None:
    """A zipped Office file must not expand beyond MAX_UNPACKED (a zip bomb would exhaust memory in the parser)."""
    if Path(name).suffix.lower() not in ZIPPED:
        return
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(zi.file_size for zi in z.infolist())
    except zipfile.BadZipFile:
        return                                              # the reader reports it as unreadable, with the reason
    if total > MAX_UNPACKED:
        raise TooLarge(f"{name} would expand to more than {MAX_UNPACKED // (1024 * 1024)} MB")


def _no_paths(detail: str, path: Path) -> str:
    """Error texts from the readers may quote the file's full path; the API never shows server paths."""
    for root in (path.parent.parent, path.parent):
        detail = detail.replace(str(root), "<project>").replace(str(root).replace("\\", "/"), "<project>")
    return detail


def probe_document(path: Path, folder: str = "srs", ai=None) -> dict:
    """read in full / partly read / not read, with the reason and how many pieces the reader found. `ai` is the
    project's `documents` client (OCR of scanned pages), or None."""
    blocks, info = documents.read(path, ai=ai)
    status, detail = info["status"], _no_paths(info.get("detail") or "", path)
    if status == "read" and not blocks:
        status, detail = "partly", "no text was found in it"
    elif status != "read":
        status = "unread"
    return {"name": path.name, "folder": folder, "size": path.stat().st_size, "kind": info["kind"], "status": status,
            "detail": detail, "segments": len(blocks)}


def _folder(p: Project, folder: str) -> Path:
    if folder not in FOLDERS:
        raise ValueError(f"unknown folder {folder!r}")
    d = p.srs_dir if folder == "srs" else p.root / folder
    d.mkdir(exist_ok=True)
    return d


def save_document(p: Project, filename: str, data: bytes, folder: str = "srs") -> dict:
    name = safe_name(filename)
    if len(data) > MAX_UPLOAD:
        raise TooLarge(f"{name} is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    check_unpacked_size(name, data)
    path = _folder(p, folder) / name
    path.write_bytes(data)
    from agentqa.ai.client import model_for
    return probe_document(path, folder, ai=model_for(p, "documents"))


def list_documents(p: Project, s: Store | None = None) -> list[dict]:
    """Every document in srs/, with the SRS stage's verdict when it has run and a fresh probe otherwise."""
    known = {d["name"]: d for d in s.all("SELECT * FROM documents")} if s and p.db_path.exists() else {}
    out = []
    for f in sorted(x for x in p.srs_dir.iterdir() if x.is_file() and x.suffix.lower() in documents.SUPPORTED):
        if f.name in known:
            k = known[f.name]
            out.append({"name": f.name, "folder": "srs", "size": f.stat().st_size, "kind": k.get("kind"),
                        "status": "read" if k.get("status") == "read" else "unread", "detail": k.get("detail") or "",
                        "segments": k.get("segments") or 0, "read_at": k.get("read_at")})
        else:
            out.append(probe_document(f))
    return out


def delete_document(p: Project, name: str, folder: str = "srs") -> None:
    base = _folder(p, folder).resolve()
    target = (base / Path(name).name).resolve()
    if target.parent != base or not target.is_file() or Path(name).name != name:
        raise NotFound("No such document")
    target.unlink()


# ---- typed requirements ---------------------------------------------------------------------------

ANSWER_LABELS = {"roles": "Users of the application", "limit": "Limit", "failure": "When something goes wrong",
                 "login": "Sign-in"}
QUOTED = re.compile(r"[“\"]([^”\"]+)[”\"]")


def save_typed(p: Project, text: str, answers: list[dict] | None = None, items: list[str] | None = None) -> Path:
    """Typed English as a document source the SRS stage reads like any file: one `REQ-nnn:` paragraph per
    requirement — the list the owner confirmed (`items`, which may have come from the AI path) or, without one,
    what the rule extractor finds — with each clarification merged into the requirement it is about, or added as
    a requirement of its own."""
    from agentqa.agents import req_chat
    items = [" ".join(i.split()) for i in (items or []) if i.strip()] or [i["text"] for i in req_chat.extract(text)] \
        or [" ".join(text.split())]
    extra: list[str] = []
    for a in answers or []:
        answer, question, topic = str(a.get("answer", "")).strip(), str(a.get("question", "")).strip(), str(a.get("topic", ""))
        if not answer:
            continue
        word = QUOTED.search(question)
        hit = next((i for i, t in enumerate(items) if word and re.search(rf"\b{re.escape(word.group(1))}\b", t, re.I)), None)
        if topic == "vague" and hit is not None:
            items[hit] = f"{items[hit]} (“{word.group(1)}” means: {answer})"
        elif topic in ANSWER_LABELS:
            extra.append(f"{ANSWER_LABELS[topic]}: {answer}")
        else:
            extra.append(f"{question} {answer}".strip())
    lines = ["# Typed requirements", ""]
    for n, item in enumerate(items + extra, 1):
        lines += [f"REQ-{n:03d}: {item}", ""]
    path = p.srs_dir / TYPED_NAME
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---- environment -----------------------------------------------------------------------------------

def set_environment(p: Project, environment: str) -> None:
    if environment not in ENVIRONMENTS:
        raise ValueError(f"environment must be one of {', '.join(ENVIRONMENTS)}")
    raw = yaml.safe_load(p.config_path.read_text(encoding="utf-8")) or {}
    apps = raw.get("applications") or {"main": {"name": p.name, "base_url": p.base_url}}
    first = next(iter(apps))
    apps[first] = {**(apps[first] or {}), "environment": environment}
    replace_top_block(p.config_path, "applications", yaml.safe_dump({"applications": apps}, sort_keys=False, allow_unicode=True))


def environment(p: Project) -> str:
    apps = p.applications()
    return next(iter(apps.values()))["environment"] if apps else ""


# ---- accounts ---------------------------------------------------------------------------------------

def _clean_role(spec: dict) -> tuple[str, dict, dict]:
    """(role, yaml part, vault part) for one wizard row; ValueError when the row is not usable."""
    role = str(spec.get("role", "")).strip().lower().replace(" ", "_")
    if not ROLE_RE.match(role):
        raise ValueError(f"Role names use letters, digits and _ only (got {spec.get('role')!r})")
    method = str(spec.get("method") or "password")
    if method not in METHODS:
        raise ValueError(f"{role}: unknown way of logging in {method!r}")
    otp_source = str(spec.get("otp_source") or "")
    if otp_source and otp_source not in OTP_SOURCES:
        raise ValueError(f"{role}: unknown OTP source {otp_source!r}")
    aliases = spec.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split(",") if a.strip()]
    public = {"login_option": str(spec.get("login_option") or "Login"), "method": method}
    if aliases:
        public["aliases"] = [str(a) for a in aliases]
    if spec.get("app"):
        public["app"] = str(spec["app"])
    private = {k: str(spec[k]).strip() for k in (*IDENTITY_FIELDS, *SECRET_FIELDS) if spec.get(k)}
    if otp_source:
        private["otp_source"] = otp_source
    return role, public, private


def save_accounts(p: Project, roles: list[dict], no_login: bool = False) -> None:
    """Non-secret parts to the `roles:` block of project.yaml; identities and secrets to the encrypted vault."""
    cleaned = [] if no_login else [_clean_role(r) for r in roles]
    if not no_login and not cleaned:
        raise ValueError("Add at least one role, or choose 'no login needed'")
    public = {role: pub for role, pub, _ in cleaned}
    replace_top_block(p.config_path, "roles", yaml.safe_dump({"roles": public}, sort_keys=False, allow_unicode=True))
    replace_top_block(p.config_path, "onboarding", yaml.safe_dump({"onboarding": {"no_login": bool(no_login)}}))
    vault = p.vault
    for stale in [r for r in vault.accounts() if r not in public and not vault.login_steps(r)]:
        vault.remove_account(stale)                         # a role with a recorded login was set up by hand: kept
    for role, _, private in cleaned:
        vault.set_account(role, {**{k: "" for k in IDENTITY_FIELDS}, **private}, keep_secrets=True)
    vault.save()


def accounts_view(p: Project) -> dict:
    """What the wizard may show again: never a password or OTP secret; identities masked."""
    if (p.cfg.get("onboarding") or {}).get("no_login") and not p.cfg.get("roles"):
        return {"no_login": True, "roles": []}
    rows = []
    for role, spec in p.roles().items():
        acc = p.account(role)
        row = {"role": role, "login_option": acc.get("login_option") or spec.get("login_option") or "",
               "method": acc.get("method") or spec.get("method") or "password", "otp_source": acc.get("otp_source") or "",
               "aliases": list(spec.get("aliases") or []), "app": acc.get("app") or spec.get("app") or "",
               "has_password": bool(acc.get("password")), "has_fixed_otp": bool(acc.get("otp_fixed")),
               "has_totp": bool(acc.get("totp_secret"))}
        for k in IDENTITY_FIELDS:
            row[k] = mask(acc.get(k)) if k != "username" else str(acc.get(k) or "")
        rows.append(row)
    return {"no_login": False, "roles": rows}


