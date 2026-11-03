"""Requirement Analyst agent (formerly the SRS Analyst).

Reads SRS documents (.docx, .pdf, .md, .txt), splits them into numbered
requirements, extracts testable rules (field constraints, access rules,
features, workflow states, performance targets) and flags ambiguous text.

Rules come from deterministic patterns first. When the project's AI mode allows a model,
requirements the patterns could not interpret are sent to it one at a time,
and anything it proposes is marked source='llm' for a person to confirm.
"""
from __future__ import annotations

import re
from pathlib import Path

from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import log, warn

REQ_ID = re.compile(r"^\s*((?:FR|NFR|BR|REQ|UC|SR|UR|US|SRS|F|R)[-_. ]?\d+(?:[.\-]\d+)*)\s*[:.)\-]\s*(.+)$", re.I | re.S)
MODAL = re.compile(r"\b(shall|must|should|will|may|is (?:mandatory|required)|are (?:mandatory|required)|is tbd)\b", re.I)

VAGUE = {
    "quickly": "no measurable time limit", "fast": "no measurable time limit",
    "promptly": "no measurable time limit", "as soon as possible": "no measurable time limit",
    "appropriate": "does not say which behaviour is correct", "adequate": "no acceptance criterion",
    "user-friendly": "not measurable", "user friendly": "not measurable", "easy": "not measurable",
    "intuitive": "not measurable", "seamless": "not measurable", "efficient": "not measurable",
    "flexible": "not measurable", "robust": "not measurable", "sufficient": "no threshold given",
    "reasonable": "no threshold given", "minimal": "no threshold given",
    "as applicable": "condition not defined", "as required": "condition not defined",
    "as needed": "condition not defined", "if necessary": "condition not defined",
    "where possible": "condition not defined", "approximately": "imprecise value",
    "normally": "exceptions not defined", "usually": "exceptions not defined",
    "etc": "open-ended list", "and/or": "unclear whether both or either apply",
    "multiple languages": "languages not listed", "tbd": "value not yet decided",
    "tbc": "value not yet confirmed", "to be decided": "value not yet decided",
    "to be confirmed": "value not yet confirmed", "to be defined": "value not yet decided",
}

RULE_KINDS = {
    "required", "max_length", "min_length", "exact_length", "length_range", "digits_only",
    "alpha_only", "format_email", "format_mobile", "starts_with", "numeric_range",
    "date_not_future", "options", "access_only", "access_deny", "feature", "status_transition",
    "perf_max_load", "session_timeout", "tbd", "file_types", "file_max_size", "otp_single_use",
}
FILE_EXT = re.compile(r"\b(pdf|jpe?g|png|gif|bmp|tiff?|docx?|xlsx?|csv|txt|zip|odt|rtf)\b", re.I)


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------

def load_blocks(path: Path) -> list[dict]:
    """(kept for older callers) Blocks of a .docx, .pdf, .md or .txt file."""
    ext = path.suffix.lower()
    if ext == ".docx":
        return _docx_blocks(path)
    if ext == ".pdf":
        return _pdf_blocks(path)
    if ext in (".md", ".txt", ".markdown"):
        return _text_blocks(path.read_text(encoding="utf-8", errors="replace"))
    raise ValueError(f"Unsupported SRS format: {path.name} (use .docx, .pdf, .md or .txt)")


def _docx_blocks(path: Path) -> list[dict]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    blocks = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"(?:Heading|Title)\s*(\d*)", style)
            if m:
                blocks.append({"kind": "heading", "level": int(m.group(1) or 0), "text": text})
            else:
                blocks.append({"kind": "para", "text": text})
        elif tag == "tbl":
            t = Table(child, doc)
            rows = []
            for row in t.rows:
                cells, seen = [], set()
                for c in row.cells:
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(c.text.strip())
                rows.append(cells)
            blocks.append({"kind": "table", "rows": rows})
    return blocks


def _pdf_blocks(path: Path) -> list[dict]:
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    return _text_blocks(text, pdf=True)


def _text_blocks(text: str, pdf: bool = False) -> list[dict]:
    blocks, table = [], []
    para: list[str] = []

    def flush_para():
        if para:
            blocks.append({"kind": "para", "text": " ".join(para).strip()})
            para.clear()

    def flush_table():
        if table:
            blocks.append({"kind": "table", "rows": [r for r in table]})
            table.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            flush_para()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                table.append(cells)
            continue
        flush_table()
        if not line:
            flush_para()
            continue
        if line.startswith("#"):
            flush_para()
            blocks.append({"kind": "heading", "level": len(line) - len(line.lstrip("#")),
                           "text": line.lstrip("# ").strip()})
            continue
        if pdf and re.match(r"^\d+(\.\d+)*\.?\s+[A-Z][\w ,/&-]{2,60}$", line) and not MODAL.search(line):
            flush_para()
            blocks.append({"kind": "heading", "level": line.split()[0].count(".") + 1, "text": line})
            continue
        if REQ_ID.match(line):
            flush_para()
        para.append(line)
    flush_para()
    flush_table()
    return blocks


# ---------------------------------------------------------------------------
# Rule extraction
# ---------------------------------------------------------------------------

def find_roles(text: str, aliases: dict[str, list[str]]) -> list[str]:
    low = " " + text.lower() + " "
    found = []
    for role, names in aliases.items():
        if any(re.search(rf"\b{re.escape(n)}s?\b", low) for n in names):
            found.append(role)
    return found


def ambiguity_flags(text: str) -> list[dict]:
    low = text.lower()
    flags = []
    for term, reason in VAGUE.items():
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", low):
            flags.append({"term": term, "reason": reason})
    return flags


SUBJECT = re.compile(
    r"^(?:the |an? )?(?P<field>[A-Za-z0-9][A-Za-z0-9 /()'&-]{1,50}?)"
    r"(?: field| input| text ?box| drop ?down)?(?: length| value| format)?\s+"
    r"(?:is|are|shall|must|should|will|can|may|cannot)\b", re.I)


def subject_field(text: str, aliases: dict[str, list[str]]) -> str | None:
    m = SUBJECT.match(text.strip())
    if not m:
        return None
    field = m.group("field").strip()
    low = field.lower()
    role_names = {n for names in aliases.values() for n in names}
    bad = {"system", "portal", "application", "user", "users", "page", "pages", "session", "it", "this"}
    if low in bad or low.rstrip("s") in role_names or low in role_names:
        return None
    if low.startswith(("only ", "when ", "if ", "users ", "the system")):
        return None
    return field


def _digits_list(spec: str) -> list[str]:
    out: list[str] = []
    for a, b in re.findall(r"(\d)\s*-\s*(\d)", spec):
        out += [str(d) for d in range(int(a), int(b) + 1)]
    spec = re.sub(r"\d\s*-\s*\d", " ", spec)
    out += re.findall(r"\d", spec)
    return sorted(set(out))


def constraint_rules(text: str, field: str | None, col: dict | None = None) -> list[dict]:
    """Field constraints from a sentence and/or field-table columns."""
    rules: list[dict] = []
    low = text.lower()

    def add(kind, value=None):
        rules.append({"kind": kind, "field": field, "value": value or {}})

    col = col or {}
    mand = (col.get("mandatory") or "").strip().lower()
    if mand in ("yes", "y", "mandatory", "required", "true", "m"):
        add("required")
    elif re.search(r"\b(?:is|are|shall be|must be|should be)\s+(?:mandatory|required|compulsory)\b", low):
        add("required")

    length = (col.get("length") or "").strip()
    ftype = (col.get("type") or "").lower()
    if length:
        lm = re.fullmatch(r"(?:max(?:imum)?\.?\s*)(\d+)(?:\s*chars?|\s*characters)?", length, re.I)
        rm = re.fullmatch(r"(\d+)\s*(?:-|to)\s*(\d+)", length)
        em = re.fullmatch(r"(\d+)", length)
        if lm:
            add("max_length", {"max": int(lm.group(1))})
        elif rm:
            add("length_range", {"min": int(rm.group(1)), "max": int(rm.group(2))})
        elif em:
            add("exact_length", {"length": int(em.group(1))})
        elif re.search(r"tbd|tbc|to be", length, re.I):
            add("tbd", {"what": "length"})

    m = re.search(r"between (\d+) and (\d+) characters", low)
    if m:
        add("length_range", {"min": int(m.group(1)), "max": int(m.group(2))})
    else:
        m = re.search(r"(?:not exceed|at most|maximum of|max(?:imum)?|up to|no more than)\s*(\d+)\s*(?:characters|chars|letters)", low)
        if m:
            add("max_length", {"max": int(m.group(1))})
        m = re.search(r"(?:at least|minimum of|min(?:imum)?|no less than)\s*(\d+)\s*(?:characters|chars|letters)", low)
        if m:
            add("min_length", {"min": int(m.group(1))})

    is_file = ftype in ("file", "upload", "attachment", "document") or re.search(r"\b(upload|attachment|file)\b", low)
    if is_file:
        exts = []
        for e in FILE_EXT.findall(text):
            e = e.lower().replace("jpeg", "jpg").replace("tiff", "tif")
            if e not in exts:
                exts.append(e)
        if exts:
            add("file_types", {"types": exts})
        sm = re.search(r"(\d+(?:\.\d+)?)\s*(kb|mb)\b", f"{length} {low}", re.I)
        if sm:
            n = float(sm.group(1)) * (1024 if sm.group(2).lower() == "mb" else 1)
            add("file_max_size", {"kb": int(n)})
    m = re.search(r"\b(\d+)[- ]digit", low)
    if m:
        add("exact_length", {"length": int(m.group(1))})
        add("digits_only")
    elif ftype in ("numeric", "number", "integer") or re.search(r"\b(digits|numbers|numeric) only\b", low):
        add("digits_only")
    if "mobile" in low and ("digit" in low or ftype in ("numeric", "mobile")):
        add("format_mobile")
    m = re.search(r"start(?:ing|s)? with ([\d ,\-or]+)", low)
    if m:
        digits = _digits_list(m.group(1))
        if digits:
            add("starts_with", {"chars": digits})
    if re.search(r"\b(alphabets?|letters)( and spaces)? only\b|only (alphabets|letters)", low):
        add("alpha_only")
    if ftype == "email" or re.search(r"valid e-?mail", low):
        add("format_email")
    if re.search(r"cannot be (?:a |in the )?future|not be (?:a |in the )?future|future dates? (?:are |is )?not allowed", low):
        add("date_not_future")
    m = re.search(r"(?:values?|options?|one of)\s*[:\-]\s*(.+)$", text, re.I)
    if m:
        opts = [o.strip(" .") for o in re.split(r",|\bor\b|/", m.group(1)) if o.strip(" .")]
        if len(opts) >= 2:
            add("options", {"options": opts})
    m = re.search(r"value (?:shall|must|should) be between (\d+) and (\d+)(?! characters)", low)
    if m:
        add("numeric_range", {"min": int(m.group(1)), "max": int(m.group(2))})
    if re.search(r"\btbd\b|\btbc\b|to be (?:decided|confirmed|defined)", low) and not any(r["kind"] == "tbd" for r in rules):
        add("tbd", {"what": "value"})
    # dedupe
    seen, out = set(), []
    for r in rules:
        key = (r["kind"], str(r["value"]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def sentence_rules(text: str, aliases: dict[str, list[str]]) -> list[dict]:
    rules: list[dict] = []
    low = text.lower()
    m = re.search(r"\bonly (?:the |an? )?(?P<who>[a-z ,/]+?) (?:shall|should|must|can|may|will)(?: be able to)? (?P<what>.+)", low)
    if m:
        roles = find_roles(m.group("who"), aliases)
        if roles:
            rules.append({"kind": "access_only", "roles": roles, "target": m.group("what").strip(" .")})
    m = re.search(r"(?P<who>[a-z ]+?) (?:shall|must|should) not (?:be able to )?(?:access|view|see|open|modify|edit|approve|verify) (?P<what>.+)", low)
    if m and find_roles(m.group("who"), aliases):
        rules.append({"kind": "access_deny", "roles": find_roles(m.group("who"), aliases),
                      "target": m.group("what").strip(" .")})
    m = re.search(r"^(?:the )?(?P<who>[a-z ]+?) (?:shall|should|must|can|will|may) be able to (?P<what>.+)", low)
    if m and not rules and find_roles(m.group("who"), aliases):
        rules.append({"kind": "feature", "roles": find_roles(m.group("who"), aliases),
                      "target": m.group("what").strip(" .")})
    m = re.search(r"status (?:shall|will|should|must) (?:change|be (?:changed|updated|set)) to (\w+)", low)
    if m:
        rules.append({"kind": "status_transition", "value": {"status": m.group(1).capitalize()},
                      "roles": find_roles(text, aliases), "target": text})
    m = re.search(r"(?:load|respond|response|display|open)\w*.{0,30}?within (\d+(?:\.\d+)?) ?(seconds|secs|sec|s|milliseconds|ms)\b", low)
    if m:
        n = float(m.group(1))
        ms = int(n if m.group(2) in ("milliseconds", "ms") else n * 1000)
        rules.append({"kind": "perf_max_load", "value": {"ms": ms}})
    if re.search(r"\b(otp|one[- ]time password|one[- ]time code)\b", low) and re.search(
            r"only once|once only|single[- ]use|not be reused|cannot be reused|used only once|accepted only once|one time only", low):
        rules.append({"kind": "otp_single_use", "value": {}, "target": text})
    m = re.search(r"(?:session|log ?out|logged out).{0,40}?(\d+) ?minutes", low)
    if m:
        rules.append({"kind": "session_timeout", "value": {"minutes": int(m.group(1))}})
    field = subject_field(text, aliases)
    if field and not any(r["kind"] in ("access_only", "access_deny", "feature") for r in rules):
        rules += constraint_rules(text, field)
    return rules


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

MISSED_SYSTEM = """You are a senior QA analyst checking that no requirement in an SRS was missed. Each passage below
produced no requirement. For each one that states something the system must do or a rule it must enforce, write the
requirement as one plain sentence. Ignore introductions, headings and narrative. Reply with JSON:
{"requirements": [{"segment": "<the number in brackets>", "text": "The system shall ...", "kind": "functional|non-functional"}]}"""

LLM_SYSTEM = """You are a senior QA analyst. Read ONE software requirement and extract testable rules.
Return JSON: {"rules": [{"kind": "...", "field": "...", "value": {...}, "roles": [...], "target": "..."}],
"ambiguity": ["short reason"], "interpretation": "one sentence: the most likely testable meaning"}.
Allowed kinds: required, max_length{max}, min_length{min}, exact_length{length}, digits_only, alpha_only,
format_email, format_mobile, starts_with{chars}, numeric_range{min,max}, date_not_future, options{options},
access_only{roles,target}, access_deny{roles,target}, feature{roles,target}, status_transition{status},
perf_max_load{ms}. Use only facts stated in the requirement. Return {"rules": []} if nothing is testable."""


POSSIBLE = re.compile(r"\b(allow|enable|support|provide|display|show|generate|send|notify|receive|calculate|validate|"
                      r"verify|approve|reject|upload|download|submit|apply|register|log ?in|search|filter|export|print|"
                      r"able to|can|cannot|need|needs|required|mandatory|only|must|within|maximum|minimum|at least)\b", re.I)
REQ_TEXT_COL = re.compile(r"requirement|description|feature|functionality|statement|details|story|rule|criteria", re.I)
REQ_ID_COL = re.compile(r"^(id|req|ref|no|s\.? ?no|sr|#|req(uirement)? ?(id|no|#)|br ?id|fr ?id|uc ?id)\b", re.I)


def analyze(project: Project, store: Store, use_llm: bool | None = None) -> dict:
    from agentqa import documents
    from agentqa.ai.client import model_for
    files = sorted(p for p in project.srs_dir.iterdir() if p.is_file() and p.suffix.lower() in documents.SUPPORTED)
    if not files:
        raise FileNotFoundError(f"No requirement documents in {project.srs_dir}. Add .docx, .pdf, .xlsx, .csv, .html, "
                                f".json, .md, .txt or image files.")
    aliases = project.role_aliases()
    store.clear("requirements", "rules", "documents", "segments")
    store.exec("DELETE FROM questions WHERE status='open'")  # answers persist across runs
    seq = 0
    rule_seq = 0
    pending_llm: list[dict] = []
    ocr_ai = model_for(project, "documents")           # scanned pages: a model that can see, when allowed

    def add_rules(req_id: str, rules: list[dict], source: str, confidence: float):
        nonlocal rule_seq
        for r in rules:
            live.emit("srs", "rule", f"{req_id}: {r['kind'].replace('_', ' ')}"
                      + (f" on {r['field']}" if r.get("field") else "") + (f" {r['value']}" if r.get("value") else ""),
                      req=req_id, rule_kind=r["kind"], field=r.get("field"), value=r.get("value") or None,
                      roles=r.get("roles") or None, target=r.get("target"), source=source)
            rule_seq += 1
            store.insert("rules", {
                "id": f"R-{rule_seq:04d}", "req_id": req_id, "kind": r["kind"],
                "field": r.get("field"), "value": r.get("value") or {}, "roles": r.get("roles") or [],
                "target": r.get("target"), "source": source, "confidence": confidence,
                "status": "New", "status_note": "", "matched": None, "decided_value": None})

    def segment(f, block_ref, kind, text, req_ids=(), disposition="context", note=""):
        store.insert("segments", {"doc": f.name, "ref": block_ref, "kind": kind, "text": str(text)[:2000],
                                  "req_ids": list(req_ids), "disposition": disposition, "note": note})

    for f in files:
        log(f"  reading {f.name}")
        section = ""
        section_kind = "functional"
        blocks, info = documents.read(f, ai=ocr_ai)
        store.insert("documents", {"name": f.name, "kind": info["kind"], "size": f.stat().st_size, "pages": info.get("pages"),
                                   "segments": len(blocks), "status": info["status"], "detail": info.get("detail") or "",
                                   "read_at": now()})
        if info["status"] != "read":
            live.emit("srs", "issue", f"{f.name}: {info['status']} - {info.get('detail')}", file=f.name, level="warn")
            warn(f"{f.name}: {info['status']}: {info.get('detail')}")
        live.emit("srs", "open", f"Opening {f.name}", file=f.name, blocks=len(blocks))
        for block in blocks:
            ref = f"{block.get('ref') or section or 'start'}"
            if block["kind"] == "heading":
                segment(f, ref, "heading", block["text"], disposition="heading")
                live.emit("srs", "heading", block["text"], level=block.get("level", 1), file=f.name)
                section = block["text"]
                section_kind = "non-functional" if re.search(r"non[- ]?functional|performance|security|usability", section, re.I) else "functional"
                continue
            if block["kind"] == "table":
                rows = block["rows"]
                if not rows:
                    continue
                header = [h.lower() for h in rows[0]]
                is_fields = any("field" in h or h in ("name", "element", "attribute") for h in header)
                text_col = next((i for i, h in enumerate(header) if REQ_TEXT_COL.search(h)), None)
                live.emit("srs", "table", f"Reading a table with {len(rows) - 1} row(s)"
                          + (" - field specification detected" if is_fields else
                             " - requirement list detected" if text_col is not None else ""),
                          rows=rows[:40], fields_table=is_fields, section=section)
                if not is_fields and text_col is not None:
                    # a requirement list (ID | Requirement | Priority | Module ...): one requirement per row
                    id_col = next((i for i, h in enumerate(header) if REQ_ID_COL.search(h.strip())), None)
                    for ri, row in enumerate(rows[1:], 2):
                        body = row[text_col].strip() if text_col < len(row) else ""
                        if not body:
                            segment(f, f"{ref}, row {ri}", "table-row", " | ".join(row), disposition="context", note="empty")
                            continue
                        seq += 1
                        rid = row[id_col].strip() if id_col is not None and id_col < len(row) and row[id_col].strip() else ""
                        req_id = rid.upper().replace(" ", "-") if rid and not rid.replace(".", "").isdigit() else f"ROW-{seq:03d}"
                        if store.one("SELECT id FROM requirements WHERE id=?", [req_id]):
                            req_id = f"{req_id}-{seq}"
                        extra = "; ".join(f"{rows[0][i]}: {c}" for i, c in enumerate(row) if c and i not in (text_col, id_col)
                                          and i < len(rows[0]))
                        flags = ambiguity_flags(body)
                        kind = "non-functional" if re.search(r"non[- ]?functional|performance|security|usability",
                                                             extra + " " + req_id, re.I) else section_kind
                        live.emit("srs", "requirement", f"{req_id}: {body}", req=req_id, text=body, section=section)
                        store.insert("requirements", {
                            "id": req_id, "seq": seq, "section": section or "Requirement list", "text": body, "kind": kind,
                            "priority": "High" if re.search(r"high|must|critical|p1", extra, re.I) else "Medium",
                            "roles": find_roles(body, aliases), "ambiguity": flags, "source_file": f.name,
                            "source_ref": f"{f.name} › {ref}, row {ri}" + (f" ({extra[:120]})" if extra else "")})
                        rules = sentence_rules(body, aliases)
                        add_rules(req_id, rules, "srs-table", 0.85)
                        segment(f, f"{ref}, row {ri}", "table-row", " | ".join(row), [req_id], "requirement")
                        if not rules and not re.search(r"\blog ?in\b", body, re.I):
                            pending_llm.append({"id": req_id, "text": body, "flags": flags})
                    continue
                if not is_fields:
                    for ri, row in enumerate(rows, 1):
                        joined = " | ".join(c for c in row if c)
                        disp = "possibly missed" if ri > 1 and (MODAL.search(joined) or POSSIBLE.search(joined)) else "context"
                        segment(f, f"{ref}, row {ri}", "table-row", joined, disposition=disp,
                                note="a table AgentQA did not recognise as fields or requirements" if disp != "context" else "")
                    continue
                idx = {k: next((i for i, h in enumerate(header) if k in h), None)
                       for k in ("field", "type", "mandatory", "length", "validation")}
                if idx["field"] is None:
                    idx["field"] = 0
                if idx["mandatory"] is None:
                    idx["mandatory"] = next((i for i, h in enumerate(header) if "required" in h or "m/o" in h), None)
                for row in rows[1:]:
                    def cell(k):
                        i = idx[k]
                        return row[i] if i is not None and i < len(row) else ""
                    fname = cell("field").strip()
                    if not fname:
                        continue
                    seq += 1
                    req_id = f"TBL-{seq:03d}"
                    desc = "; ".join(f"{k.capitalize()}: {cell(k)}" for k in ("type", "mandatory", "length", "validation") if cell(k))
                    text = f"{fname} - {desc}"
                    segment(f, f"{ref}, row {rows.index(row) + 1}", "table-row", " | ".join(row), [req_id], "requirement")
                    flags = [fl for fl in ambiguity_flags(" ".join(row)) if fl["term"] in ("tbd", "tbc", "to be decided", "to be confirmed", "to be defined", "etc")]
                    live.emit("srs", "requirement", f"{req_id}: {text}", req=req_id, text=text, row=row,
                              flags=[fl["term"] for fl in flags] or None, section=section)
                    store.insert("requirements", {
                        "id": req_id, "seq": seq, "section": section or "Field table", "text": text,
                        "kind": "field-spec", "priority": "High" if cell("mandatory").lower().startswith("y") else "Medium",
                        "roles": [], "ambiguity": flags, "source_file": f.name,
                        "source_ref": f"{f.name} › {ref}, row {rows.index(row) + 1}"})
                    col = {"type": cell("type"), "mandatory": cell("mandatory"), "length": cell("length")}
                    rules = constraint_rules(cell("validation") if cell("validation") not in ("-", "") else "", fname, col)
                    add_rules(req_id, rules, "srs-table", 0.95)
                continue
            # paragraph
            text = block["text"]
            m = REQ_ID.match(text)
            candidates = []
            if m:
                candidates.append((m.group(1).upper().replace("_", "-").replace(" ", "-"), m.group(2).strip()))
            else:
                for sent in re.split(r"(?<=[.;])\s+(?=[A-Z])", text):
                    if MODAL.search(sent) and len(sent.split()) >= 4:
                        candidates.append((None, sent.strip()))
            if not candidates:
                live.emit("srs", "text", text[:400], section=section)
                maybe = bool(POSSIBLE.search(text)) and len(text.split()) >= 5
                segment(f, ref, "para", text, disposition="possibly missed" if maybe else "context",
                        note="has requirement-like wording but no 'shall', 'must' or requirement number" if maybe else "")
            made = []
            for rid, sent in candidates:
                seq += 1
                req_id = rid or f"SRS-{seq:03d}"
                if store.one("SELECT id FROM requirements WHERE id=?", [req_id]):
                    req_id = f"{req_id}-{seq}"
                kind = "non-functional" if req_id.upper().startswith("NFR") else section_kind
                pri = "High" if re.search(r"\b(shall|must)\b", sent, re.I) else ("Medium" if re.search(r"\bshould\b", sent, re.I) else "Low")
                flags = ambiguity_flags(sent)
                live.emit("srs", "requirement", f"{req_id}: {sent}", req=req_id, text=sent, section=section,
                          flags=[fl["term"] for fl in flags] or None, roles=find_roles(sent, aliases) or None)
                for fl in flags:
                    live.emit("srs", "ambiguity", f"{req_id}: '{fl['term']}' - {fl['reason']}", req=req_id,
                              term=fl["term"])
                store.insert("requirements", {
                    "id": req_id, "seq": seq, "section": section, "text": sent, "kind": kind,
                    "priority": pri, "roles": find_roles(sent, aliases), "ambiguity": flags,
                    "source_file": f.name, "source_ref": f"{f.name} › {ref}"})
                made.append(req_id)
                rules = sentence_rules(sent, aliases)
                add_rules(req_id, rules, "srs-text", 0.85)
                if not rules and not re.search(r"\blog ?in\b", sent, re.I):
                    live.emit("srs", "unclear", f"{req_id}: no testable rule recognised", req=req_id)
                    pending_llm.append({"id": req_id, "text": sent, "flags": flags})
            if made:
                segment(f, ref, "para", text, made, "requirement")

    # optional model pass on requirements the patterns could not interpret
    llm = model_for(project, "srs")
    want = (llm is not None) if use_llm is None else use_llm
    llm_used = 0
    if want and pending_llm and llm is not None and llm.available():
        cap = int((project.cfg.get("ai") or {}).get("max_chunks", 40))
        log(f"  asking the model ({llm.model}) about {min(cap, len(pending_llm))} requirement(s) "
            f"the patterns could not interpret (local CPU models take ~20-60 s each)")
        for item in pending_llm[:cap]:
            live.emit("srs", "model", f"Asking the model about {item['id']}", req=item["id"], text=item["text"])
            out = llm.chat_json(LLM_SYSTEM, f"Roles in this system: {', '.join(aliases)}.\nRequirement {item['id']}: {item['text']}")
            if not out:
                continue
            llm_used += 1
            good = []
            for r in out.get("rules") or []:
                if isinstance(r, dict) and r.get("kind") in RULE_KINDS:
                    good.append({"kind": r["kind"], "field": r.get("field"),
                                 "value": r.get("value") if isinstance(r.get("value"), dict) else {},
                                 "roles": [x for x in (r.get("roles") or []) if x in aliases],
                                 "target": r.get("target")})
            add_rules(item["id"], good, "llm", 0.5)
            interp = out.get("interpretation")
            if interp and item["flags"]:
                req = store.one("SELECT ambiguity FROM requirements WHERE id=?", [item["id"]])
                flags = (req or {}).get("ambiguity") or []
                flags.append({"term": "model interpretation", "reason": str(interp)[:300]})
                store.update("requirements", "id", item["id"], {"ambiguity": flags})
    elif want and pending_llm:
        warn("AI is on for this project but no model is available; skipped the model pass.")

    # completeness: text with requirement-like wording that produced no requirement
    missed = store.all("SELECT * FROM segments WHERE disposition='possibly missed'")
    if missed and want and llm is not None and llm.available():
        live.emit("srs", "model", f"Completeness check: asking the model about {len(missed)} passage(s) no requirement came from")
        for chunk in [missed[i:i + 12] for i in range(0, min(len(missed), 60), 12)]:
            out = llm.chat_json(MISSED_SYSTEM, "\n".join(f"[{m['id']}] ({m['doc']} › {m['ref']}) {m['text'][:600]}" for m in chunk),
                                max_tokens=1800) or {}
            for item in (out.get("requirements") or [])[:30]:
                sid = item.get("segment")
                seg = next((m for m in chunk if str(m["id"]) == str(sid)), None)
                text = str(item.get("text") or "").strip()
                if not seg or len(text.split()) < 4:
                    continue
                seq += 1
                req_id = f"MISS-{seq:03d}"
                store.insert("requirements", {"id": req_id, "seq": seq, "section": "Found by the completeness check",
                                              "text": text, "kind": item.get("kind") or "functional", "priority": "Medium",
                                              "roles": find_roles(text, aliases), "ambiguity": ambiguity_flags(text),
                                              "source_file": seg["doc"], "source_ref": f"{seg['doc']} › {seg['ref']}"})
                add_rules(req_id, sentence_rules(text, aliases), "llm", 0.5)
                store.update("segments", "id", seg["id"], {"disposition": "requirement",
                                                           "req_ids": (seg["req_ids"] or []) + [req_id],
                                                           "note": "found by the completeness check (model); please confirm"})
    counts = {
        "files": len(files),
        "requirements": store.scalar("SELECT COUNT(*) FROM requirements"),
        "rules": store.scalar("SELECT COUNT(*) FROM rules"),
        "ambiguous": store.scalar("SELECT COUNT(*) FROM requirements WHERE ambiguity != '[]'"),
        "uninterpreted": len(pending_llm),
        "llm_calls": llm_used,
        "segments": store.scalar("SELECT COUNT(*) FROM segments"),
        "possibly_missed": store.scalar("SELECT COUNT(*) FROM segments WHERE disposition='possibly missed'"),
        "documents_not_fully_read": store.scalar("SELECT COUNT(*) FROM documents WHERE status != 'read'"),
    }
    store.set_meta("analyze", counts)
    live.emit("srs", "summary", f"{counts['requirements']} requirements, {counts['rules']} rules, "
              f"{counts['ambiguous']} need clarification", **counts)
    return counts
