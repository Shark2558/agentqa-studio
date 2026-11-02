"""Builds demo/srs/Demo_Certificate_Portal_SRS.docx - a deliberately imperfect SRS.

It contains clear rules, a field table, vague statements, a TBD, a feature the
portal never built, and an option list that disagrees with the live app.
"""
from pathlib import Path

from docx import Document

OUT = Path(__file__).parent / "srs" / "Demo_Certificate_Portal_SRS.docx"

doc = Document()
doc.add_heading("Software Requirements Specification - Demo Certificate Portal", 0)
doc.add_paragraph("Version 1.4 (demo). This SRS is intentionally imperfect for testing AgentQA Studio.")

doc.add_heading("1. Users and roles", 1)
doc.add_paragraph("The portal has four roles: Citizen, Clerk (front office), Officer (approving officer) "
                  "and Administrator.")

doc.add_heading("2. Functional requirements", 1)
reqs = [
    "FR-01: Citizens shall log in with their registered 10-digit mobile number and a 6-digit OTP sent by SMS. "
    "Department users (Clerk, Officer and Administrator) shall log in with a username and password.",
    "FR-02: Citizens shall be able to apply for a certificate online.",
    "FR-03: The Citizen shall be able to view the status of submitted applications in My Applications.",
    "FR-04: The Applicant Name field is mandatory and shall not exceed 50 characters.",
    "FR-05: The Mobile Number shall be a 10-digit mobile number starting with 6, 7, 8 or 9.",
    "FR-06: Only the Clerk shall be able to access the Verification Queue and verify applications.",
    "FR-07: When the Clerk verifies an application, its status shall change to Verified.",
    "FR-08: Only the Officer shall be able to access the Approval Queue and approve applications.",
    "FR-09: When the Officer approves an application, its status shall change to Approved.",
    "FR-10: Only the Administrator shall be able to access User Management and Reports.",
    "FR-11: The Citizen shall be able to download the approved certificate as a PDF.",
    "FR-12: Appropriate error messages shall be displayed for invalid inputs.",
    "FR-13: The Remarks field length is TBD.",
    "FR-14: Officers shall log in with their password and a one-time password (OTP) sent by SMS to their registered mobile number.",
    "FR-15: An OTP shall be valid for 5 minutes and shall be accepted only once.",
    "FR-16: The Citizen shall receive a confirmation email when an application is submitted.",
    "FR-17: The home page shall offer a Login button with two options: Citizen Login and Department Login.",
    "FR-18: The Citizen login shall show an error when the mobile number is not a valid 10-digit number starting with 6, 7, 8 or 9.",
    "FR-19: The Citizen shall be able to request a new OTP with Resend OTP on the OTP screen.",
    "FR-20: Logout shall end the session and return the user to the home page.",
]
for r in reqs:
    doc.add_paragraph(r)

doc.add_heading("3. Application form fields", 1)
doc.add_paragraph("Table 1 lists the fields on the certificate application form.")
rows = [
    ("Field Name", "Type", "Mandatory", "Length", "Validation"),
    ("Applicant Name", "Text", "Yes", "Max 50", "-"),
    ("Mobile Number", "Numeric", "Yes", "10", "10-digit mobile number starting with 6-9"),
    ("Email Address", "Email", "No", "Max 100", "Valid email format"),
    ("PIN Code", "Numeric", "Yes", "6", "6-digit PIN code"),
    ("Date of Birth", "Date", "Yes", "-", "Cannot be a future date"),
    ("Certificate Type", "Dropdown", "Yes", "-", "Values: Income, Caste, Residence"),
    ("Documents Attached", "Multi-select", "Yes", "-", "Values: Aadhaar, Ration Card, Voter ID, Passport"),
    ("Purpose of Certificate", "Rich text", "Yes", "Max 300", "-"),
    ("Address", "Text area", "Yes", "Max 200", "-"),
    ("Supporting Document", "File", "No", "Max 2 MB", "PDF, JPG or PNG only"),
    ("Remarks", "Text", "No", "TBD", "-"),
]
table = doc.add_table(rows=len(rows), cols=5)
table.style = "Table Grid"
for i, row in enumerate(rows):
    for j, cell in enumerate(row):
        table.cell(i, j).text = cell

doc.add_heading("4. Non-functional requirements", 1)
for r in [
    "NFR-01: The system shall respond quickly to user actions.",
    "NFR-02: Pages shall load within 3 seconds.",
    "NFR-03: The session shall expire after 15 minutes of inactivity.",
    "NFR-04: The portal should support multiple languages as applicable.",
]:
    doc.add_paragraph(r)

OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(f"wrote {OUT}")
