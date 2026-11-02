"""Build demo/manual_tests.xlsx: manual test cases in the layout many QA teams use.

Run: python demo/make_manual_tests.py
Some steps are written loosely on purpose, so the importer shows which steps
it automated and which it left for review.
"""
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

CASES = [
    ("TC_01", "Certificate", "Citizen applies for an income certificate", "Citizen is logged in",
     "1. Navigate to Apply for Certificate\n2. Enter Applicant Name as 'Ravi Kumar'\n3. Enter Mobile Number as '9876543210'\n"
     "4. Enter PIN Code as '695001'\n5. Enter Date of Birth as '15/05/1990'\n6. Select Income from Certificate Type\n"
     "7. Select Aadhaar in Documents Attached\n8. Enter Purpose of Certificate as 'Bank loan'\n"
     "9. Enter Address as '1 Test Road, Kowdiar'\n10. Tick the declaration checkbox\n11. Click Submit Application",
     "", "Application submitted successfully message is displayed", "Citizen", "FR-02"),
    ("TC_02", "Certificate", "Mobile number must be 10 digits", "Citizen is logged in",
     "1. Open Apply for Certificate\n2. Enter valid details in all mandatory fields\n3. Enter Mobile Number as '12345'\n"
     "4. Click Submit Application",
     "", "Error message 'Mobile Number must be 10 digits' is displayed", "Citizen", "FR-05"),
    ("TC_03", "Certificate", "Citizen views submitted applications", "Citizen is logged in",
     "1. Go to My Applications", "", "'Status' column is displayed", "Citizen", "FR-03"),
    ("TC_04", "Verification", "Clerk verifies a submitted application", "Clerk is logged in",
     "1. Open Verification Queue\n2. Click Verify button for the first application",
     "", "Application status changes to Verified", "Clerk", "FR-07"),
    ("TC_05", "Security", "Clerk cannot open the Approval Queue", "Clerk is logged in",
     "1. Open URL /officer/queue", "", "Access denied message is displayed", "Clerk", "FR-08"),
    ("TC_06", "Help", "Help page links to the FAQ", "",
     "1. Open Help\n2. Click on frequently asked questions link", "", "FAQ page is displayed", "Citizen", ""),
    ("TC_07", "Public", "Public user searches for a service", "User is not logged in",
     "1. Open Home page\n2. Enter 'income' in Search services\n3. Click Search", "", "Search results page is displayed",
     "Public user", ""),
    ("TC_08", "Certificate", "Citizen uploads a supporting document", "Citizen is logged in",
     "1. Navigate to Apply for Certificate\n2. Enter valid details in all mandatory fields\n"
     "3. Upload a PDF copy of the Aadhaar card as Supporting Document\n4. Click Submit Application",
     "", "Application submitted successfully message is displayed", "Citizen", "FR-02"),
    ("TC_09", "Notifications", "Citizen receives a confirmation email", "Citizen is logged in",
     "1. Navigate to Apply for Certificate\n2. Enter valid details in all mandatory fields\n"
     "3. Enter Email Address as 'ravi.kumar@example.com'\n4. Click Submit Application",
     "", "Confirmation email is received at 'ravi.kumar@example.com'", "Citizen", "FR-16"),
    ("TC_10", "Certificate", "Date of Birth cannot be in the future", "Citizen is logged in",
     "1. Navigate to Apply for Certificate\n2. Enter valid details in all mandatory fields\n"
     "3. Enter Date of Birth as '15/05/2035'\n4. Click Submit Application",
     "", "Error message 'Date of Birth cannot be in the future' is displayed", "Citizen", "TBL-005"),
]

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Test Cases"
ws.append(["Demo Certificate Portal - Manual Test Cases (v1.3)"])
ws.append([])
head = ["TC ID", "Module", "Test Scenario", "Pre-condition", "Test Steps", "Test Data", "Expected Result", "Role",
        "Requirement ID", "Priority", "Status"]
ws.append(head)
for c in CASES:
    ws.append(list(c) + ["High" if c[0] in ("TC_01", "TC_05") else "Medium", "Not run"])
for cell in ws[3]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="1D4ED8")
for row in ws.iter_rows(min_row=4):
    for cell in row:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
for col, width in zip("ABCDEFGHIJK", (8, 13, 34, 22, 52, 14, 40, 12, 14, 9, 9)):
    ws.column_dimensions[col].width = width
ws["A1"].font = Font(bold=True, size=13)
out = Path(__file__).parent / "manual_tests.xlsx"
wb.save(out)
print(f"wrote {out}")
