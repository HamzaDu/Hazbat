"""Cathode count checks for MLP cells (services/forms.py, services/bulk.py).
No database needed.

pytest -q tests/test_cathode_count.py
"""

import io
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

import services.bulk
from services.bulk import process_bulk_upload, read_upload
from services.forms import parse_cathode_count

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


@pytest.mark.parametrize(
    "value, count",
    [
        (None, 1),  # field not sent
        ("", 1),
        ("  ", 1),
        ("1", 1),
        ("7", 7),
        (" 12 ", 12),
        ("100", 100),
    ],
)
def test_accepts_valid_counts(value, count):
    assert parse_cathode_count(value) == (count, None)


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "101",
        "-1",
        "2.5",
        pytest.param("2.0", id="decimal-whole-number"),
        "1e2",
        "+3",
        "abc",
        "1 2",
        pytest.param("٣", id="non-ascii-digit"),
    ],
)
def test_rejects_bad_counts(value):
    count, error = parse_cathode_count(value)
    assert count is None
    assert "1 to 100" in error


def mlp_row(mlp_id, **extra):
    """One spreadsheet row with the required MLP columns filled in."""
    return {
        "mlp_id": mlp_id,
        "cat_coating_id": "CAT-X-C001",
        "an_coating_id": "AN-X-C001",
        "project": "LEAP",
        **extra,
    }


@pytest.fixture
def inserted(monkeypatch):
    """Replaces the database insert; collects the rows that would be saved."""
    rows = []

    def fake_insert(table, data):
        rows.append(data)

    monkeypatch.setattr(services.bulk, "insert_record", fake_insert)
    return rows


def upload(rows):
    # allowed=None (admin) and no check, so nothing touches the database
    return process_bulk_upload(rows, "tbl_mlp", None)


def test_bulk_without_column_gives_one(inserted):
    upload([mlp_row("MLP-0001")])
    assert inserted[0]["cathode_count"] == 1


@pytest.mark.parametrize("cell", ["", "N/A", "-"])
def test_bulk_blank_cell_gives_one(inserted, cell):
    upload([mlp_row("MLP-0001", cathode_count=cell)])
    assert inserted[0]["cathode_count"] == 1


def test_bulk_valid_count_and_header_variants(inserted):
    results = upload(
        [
            mlp_row("MLP-0001", cathode_count="3"),
            mlp_row("MLP-0002", **{"Cathode Count": "4"}),
            mlp_row("MLP-0003", **{"Number of cathodes": "5"}),
        ]
    )
    assert [r["cathode_count"] for r in inserted] == [3, 4, 5]
    assert results["ignored"] == []


def test_bulk_bad_count_fails_only_that_row(inserted):
    results = upload(
        [
            mlp_row("MLP-0001", cathode_count="abc"),
            mlp_row("MLP-0002", cathode_count="2"),
            mlp_row("MLP-0003", cathode_count="0"),
        ]
    )
    assert results["success"] == ["MLP-0002"]
    assert [f["row"] for f in results["failed"]] == [2, 4]
    assert all("1 to 100" in f["reason"] for f in results["failed"])
    assert len(inserted) == 1


def test_excel_whole_number_reads_without_decimal():
    buf = io.BytesIO()
    pd.DataFrame({"cathode_count": [2]}).to_excel(buf, index=False)
    rows = read_upload(buf.getvalue(), "mlp.xlsx")
    assert rows[0]["cathode_count"] == "2"
