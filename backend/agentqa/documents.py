"""Reading requirement documents in the formats teams actually send.

Every reader returns blocks ({kind: heading|para|table, text|rows, ref}) and a status for the file:
read (all of it), partial (some pages or parts could not be read, and which ones) or unread (nothing,
with the reason and what would fix it). Nothing is dropped silently: the Requirement Analyst records every block
as a source segment, and unread parts appear on the Requirements page.

Scanned pages and images are read with Tesseract OCR when it is installed, else with a vision-capable AI
key when images are allowed on the AI providers page.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

TEXT = {".md", ".markdown", ".txt"}
IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
SUPPORTED = {".docx", ".doc", ".pdf", ".xlsx", ".xlsm", ".xls", ".csv", ".html", ".htm", ".json"} | TEXT | IMAGES


def _tesseract() -> str | None:
    for c in (shutil.which("tesseract"), r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
        if c and Path(c).exists():
            return c
    return None


def ocr(image: bytes) -> tuple[str | None, str]:
    """(text, how). Tesseract first, then a vision-capable AI key (only when images are allowed)."""
    exe = _tesseract()
    if exe:
        try:
            out = subprocess.run([exe, "stdin", "stdout"], input=image, capture_output=True, timeout=120)
            text = out.stdout.decode("utf-8", errors="replace").strip()
            if text:
                return text, "Tesseract OCR"
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from agentqa.ai import gateway
        gw = gateway()
        if gw.has_keys() and gw.store.policy().get("send_screenshots"):
            out = gw.complete_json("You transcribe scanned requirement documents exactly. Reply with JSON only.",
                                   'Transcribe all text in the image, keeping headings, numbering and table rows (cells '
                                   'separated by " | "). Return {"text": "..."}.', task="ocr", max_tokens=4000,
                                   image=image, need_vision=True)
            if out and out.get("text"):
                return str(out["text"]), "AI vision model"
    except Exception:  # noqa: BLE001
        pass
    return None, ("install Tesseract OCR, or add a vision-capable AI key and allow images on the AI providers page")


def _convert_office(path: Path, to: str) -> Path | None:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    outdir = path.parent / ".converted"
    outdir.mkdir(exist_ok=True)
    try:
        subprocess.run([exe, "--headless", "--convert-to", to, "--outdir", str(outdir), str(path)], capture_output=True,
                       timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    out = outdir / (path.stem + "." + to)
    return out if out.exists() else None


# ---------------------------------------------------------------------------------------------

def read(path: Path) -> tuple[list[dict], dict]:
    ext = path.suffix.lower()
    info = {"kind": ext.lstrip("."), "pages": None, "status": "read", "detail": ""}
    try:
        if ext == ".docx":
            return _docx(path), info
        if ext == ".doc":
            conv = _convert_office(path, "docx")
            if not conv:
                return [], {**info, "status": "unread", "detail": "old Word format: save it as .docx (or install LibreOffice)"}
            return _docx(conv), {**info, "detail": "converted from .doc with LibreOffice"}
        if ext == ".pdf":
            return _pdf(path, info)
        if ext in TEXT:
            return text_blocks(path.read_text(encoding="utf-8", errors="replace")), info
        if ext in (".xlsx", ".xlsm"):
            return _xlsx(path, info)
        if ext == ".xls":
            import importlib.util
            if importlib.util.find_spec("xlrd"):
                return _xls(path, info)
            else:
                conv = _convert_office(path, "xlsx")
                if not conv:
                    return [], {**info, "status": "unread", "detail": "old Excel format: save it as .xlsx (or install LibreOffice)"}
                blocks, i2 = _xlsx(conv, info)
                return blocks, {**i2, "detail": "converted from .xls with LibreOffice"}
        if ext == ".csv":
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|") if text.strip() else csv.excel
            rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
            return [{"kind": "table", "rows": rows, "ref": "table"}] if rows else [], info
        if ext in (".html", ".htm"):
            return _html(path.read_text(encoding="utf-8", errors="replace")), info
        if ext == ".json":
            return _json(json.loads(path.read_text(encoding="utf-8", errors="replace"))), info
        if ext in IMAGES:
            text, how = ocr(path.read_bytes())
            if text is None:
                return [], {**info, "status": "unread", "detail": f"an image: {how}"}
            return text_blocks(text), {**info, "detail": f"read with {how}"}
    except Exception as exc:  # noqa: BLE001
        return [], {**info, "status": "unread", "detail": f"could not be read: {exc.__class__.__name__}: {str(exc)[:200]}"}
    return [], {**info, "status": "unread", "detail": "this file type is not supported"}


def _docx(path: Path) -> list[dict]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(str(path))
    blocks, section, tables = [], "", 0
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
                section = text
                blocks.append({"kind": "heading", "level": int(m.group(1) or 0), "text": text, "ref": text})
            else:
                blocks.append({"kind": "para", "text": text, "ref": section or "start"})
        elif tag == "tbl":
            tables += 1
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
            blocks.append({"kind": "table", "rows": rows, "ref": f"{section + ', ' if section else ''}table {tables}"})
    return blocks


def _pdf(path: Path, info: dict) -> tuple[list[dict], dict]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    blocks, unread, ocred = [], [], []
    info["pages"] = len(reader.pages)
    for n, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if len(text.strip()) < 20:
            imgs = []
            try:
                imgs = list(page.images)
            except Exception:  # noqa: BLE001
                pass
            got = ""
            for im in imgs[:4]:
                t, _how = ocr(im.data)
                got += (t or "") + "\n"
            if got.strip():
                text, _ = got, ocred.append(n)
            elif imgs or not text.strip():
                if imgs:
                    unread.append(n)
                continue
        for b in text_blocks(text, pdf=True):
            b["ref"] = f"page {n}"
            blocks.append(b)
    if unread:
        info.update(status="partial" if blocks else "unread",
                    detail=f"scanned page(s) {', '.join(map(str, unread))} could not be read: " + ocr(b"")[1])
    elif ocred:
        info["detail"] = f"page(s) {', '.join(map(str, ocred))} read with OCR"
    return blocks, info


def _xlsx(path: Path, info: dict) -> tuple[list[dict], dict]:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    blocks = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in r]
            if any(cells):
                while cells and not cells[-1]:
                    cells.pop()
                rows.append(cells)
        if rows:
            blocks.append({"kind": "heading", "level": 1, "text": ws.title, "ref": f"sheet {ws.title}"})
            blocks.append({"kind": "table", "rows": rows, "ref": f"sheet {ws.title}"})
    info["pages"] = len(wb.worksheets)
    return blocks, info


def _xls(path: Path, info: dict) -> tuple[list[dict], dict]:
    import xlrd
    book = xlrd.open_workbook(str(path))
    blocks = []
    for sh in book.sheets():
        rows = [[str(sh.cell_value(r, c)).strip() for c in range(sh.ncols)] for r in range(sh.nrows)]
        rows = [r for r in rows if any(r)]
        if rows:
            blocks += [{"kind": "heading", "level": 1, "text": sh.name, "ref": f"sheet {sh.name}"},
                       {"kind": "table", "rows": rows, "ref": f"sheet {sh.name}"}]
    info["pages"] = book.nsheets
    return blocks, info


class _HTML(HTMLParser):
    BLOCK = {"p", "li", "div", "section", "article", "dd", "dt", "blockquote", "br", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.section = [], [], ""
        self.heading = None
        self.table = None
        self.row = None
        self.cell = None
        self.skip = 0

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.blocks.append({"kind": "para", "text": text, "ref": self.section or "start"})

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "noscript"):
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = (int(tag[1]), [])
        elif tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in self.BLOCK and self.table is None and self.heading is None:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif re.fullmatch(r"h[1-6]", tag) and self.heading:
            text = re.sub(r"\s+", " ", "".join(self.heading[1])).strip()
            if text:
                self.section = text
                self.blocks.append({"kind": "heading", "level": self.heading[0], "text": text, "ref": text})
            self.heading = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table:
                self.blocks.append({"kind": "table", "rows": self.table, "ref": f"{self.section or 'start'}, table"})
            self.table = None
        elif tag in self.BLOCK and self.table is None:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.heading is not None:
            self.heading[1].append(data)
        elif self.cell is not None:
            self.cell.append(data)
        elif self.table is None:
            self.buf.append(data)


def _html(text: str) -> list[dict]:
    h = _HTML()
    h.feed(text)
    h._flush()
    return h.blocks


def _json(data, prefix: str = "") -> list[dict]:
    blocks: list[dict] = []
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        keys = list(dict.fromkeys(k for x in data for k in x))
        rows = [keys] + [[json.dumps(x.get(k)) if isinstance(x.get(k), (dict, list)) else str(x.get(k) or "") for k in keys]
                         for x in data]
        return [{"kind": "table", "rows": rows, "ref": prefix or "list"}]
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                if isinstance(v, dict) or (v and all(isinstance(x, dict) for x in v)):
                    blocks.append({"kind": "heading", "level": 2, "text": path, "ref": path})
                blocks += _json(v, path)
            elif isinstance(v, str) and v.strip():
                blocks.append({"kind": "para", "text": (f"{k}: {v}" if len(v) < 40 else v), "ref": path})
    elif isinstance(data, list):
        for i, v in enumerate(data):
            blocks += _json(v, f"{prefix}[{i}]") if isinstance(v, (dict, list)) else (
                [{"kind": "para", "text": str(v), "ref": f"{prefix}[{i}]"}] if str(v).strip() else [])
    return blocks


# kept here so the Requirement Analyst and readers share one plain-text splitter
MODAL = re.compile(r"\b(shall|must|should|will|may|is (?:mandatory|required)|are (?:mandatory|required)|is tbd)\b", re.I)
REQ_ID = re.compile(r"^\s*((?:FR|NFR|BR|REQ|UC|SR|UR|US|SRS|F|R)[-_. ]?\d+(?:[.\-]\d+)*)\s*[:.)\-]\s*(.+)$", re.I | re.S)


def text_blocks(text: str, pdf: bool = False) -> list[dict]:
    blocks, table = [], []
    para: list[str] = []
    section = ""

    def flush_para():
        if para:
            blocks.append({"kind": "para", "text": " ".join(para).strip(), "ref": section or "start"})
            para.clear()

    def flush_table():
        if table:
            blocks.append({"kind": "table", "rows": [r for r in table], "ref": f"{section or 'start'}, table"})
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
            section = line.lstrip("# ").strip()
            blocks.append({"kind": "heading", "level": len(line) - len(line.lstrip("#")), "text": section, "ref": section})
            continue
        if pdf and re.match(r"^\d+(\.\d+)*\.?\s+[A-Z][\w ,/&-]{2,60}$", line) and not MODAL.search(line):
            flush_para()
            section = line
            blocks.append({"kind": "heading", "level": line.split()[0].count(".") + 1, "text": line, "ref": line})
            continue
        if REQ_ID.match(line):
            flush_para()
        para.append(line)
    flush_para()
    flush_table()
    return blocks
