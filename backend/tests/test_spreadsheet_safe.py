"""M1.4: text from the application under test cannot become a spreadsheet formula. `util.spreadsheet_safe` puts a
leading apostrophe before text a spreadsheet would run; the four exports use it (tested with each export)."""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook, load_workbook

from agentqa.util import spreadsheet_safe


@pytest.mark.parametrize("value", ["=HYPERLINK(\"http://x\",\"y\")", "+1+1", "-2+3", "@SUM(A1)", "\tx", "\rx", " =1",
                                   "  @x", "-1"])
def test_text_a_spreadsheet_would_run_gets_an_apostrophe(value):
    """Spaces before the sign count too (some spreadsheets trim them); "-1" in test data shows as '-1, accepted."""
    assert spreadsheet_safe(value) == "'" + value


@pytest.mark.parametrize("value", ["", "-", " - ", "Mobile accepts letters", "TC-0001", "a=b", 12, 3.5, None])
def test_everything_else_is_left_alone(value):
    assert spreadsheet_safe(value) == value


def _cell(value):
    wb = Workbook()
    wb.active.append([value])
    buf = io.BytesIO()
    wb.save(buf)
    return load_workbook(io.BytesIO(buf.getvalue())).active["A1"]


def test_openpyxl_stores_a_leading_equals_sign_as_a_formula():
    """The library behaviour the plan listed as not yet verified: without the apostrophe the cell is a formula."""
    assert _cell("=1+1").data_type == "f"


def test_a_made_safe_value_is_stored_as_text():
    cell = _cell(spreadsheet_safe("=1+1"))
    assert cell.data_type == "s" and cell.value == "'=1+1"
