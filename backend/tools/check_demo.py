"""Regression check for AgentQA itself: after a full demo pipeline, every seeded bug must be reported once.

The demo has two portals (Citizen Portal, and Department Portal written '@department/...').

    python tools/check_demo.py projects/demo

Exits 1 when a seeded bug was missed or an unexpected defect appeared (a false alarm), so CI fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentqa.config import Project  # noqa: E402
from agentqa.store import Store  # noqa: E402

EXPECTED = {
    "B1 Approval Queue open to every role": "access:@department/officer/queue",
    "B2 Applicant Name allows 100 characters": "field:/apply:applicant_name",
    "B3 Mobile Number accepts letters": "field:/apply:mobile",
    "B4 Admin Reports crashes": "page:@department/admin/reports",
    "B5 Help links to a missing FAQ": "link:/help/faq",
    "B6 Home image without alt text": "a11y:/",
    "B7 Certificate Type options": "field:/apply:cert_type:options",
    "B8 Search reflects input as HTML": "xss:/search:q",
    "B9 JavaScript error on My Applications": "js:/my-applications",
    "B10 No security headers": "security:headers",
    "B11 Another citizen's record via the API": "isolation:/api/applications/{n}",
    "B12 /api/users open to every role": "access:@department/api/users",
    "B13 Session survives logout": "security:session",
    "B14 No anti-CSRF tokens": "security:csrf",
    "B15 OTP accepted twice": "security:otp",
    "B16 Any file type accepted": "field:/apply:document",
    "B17 Documents Attached options": "field:/apply:docs:options",
    "B18 Citizen login takes a 9-digit mobile": "field:/citizen/login:mobile_no",
    "B19 Resend OTP does nothing": "func:login:citizen:resend",
}


def main(folder: str) -> int:
    p = Project(Path(folder))
    s = Store(p.db_path)
    found = {d["signature"]: d for d in s.all("SELECT * FROM defects WHERE status NOT IN ('rejected', 'resolved')")}
    missed = [bug for bug, sig in EXPECTED.items() if sig not in found]
    extra = [f"{d['id']} {d['signature']}: {d['title']}" for sig, d in found.items() if sig not in EXPECTED.values()]
    for bug, sig in EXPECTED.items():
        d = found.get(sig)
        print(f"  {'found ' if d else 'MISSED'}  {bug:44} {d['id'] + ' ' + d['severity'] if d else ''}")
    for e in extra:
        print(f"  EXTRA   {e}")
    print(f"{len(EXPECTED) - len(missed)}/{len(EXPECTED)} seeded bugs found, {len(extra)} unexpected defect(s)")
    return 1 if missed or extra else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects/demo"))
