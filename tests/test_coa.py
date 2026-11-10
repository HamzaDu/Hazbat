"""COA upload checks (services/coa.py). No database needed.

pytest -q tests/test_coa.py
"""

import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

from services.coa import (
    MAX_COA_BYTES,
    OLE_MAGIC,
    CoaError,
    detect_kind,
    safe_display_name,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def make_docx(with_body=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        if with_body:
            z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


@pytest.mark.parametrize(
    "name, data, kind",
    [
        ("coa.pdf", b"%PDF-1.7\n...", "pdf"),
        ("COA.PDF", b"\n %PDF-1.4", "pdf"),
        pytest.param(
            "coa.docx",
            make_docx(),
            "docx",
            id="word-docx",
        ),
        pytest.param(
            "coa.doc",
            OLE_MAGIC + b"\x00" * 64,
            "doc",
            id="legacy-word-doc",
        ),
    ],
)
def test_accepts_real_files(name, data, kind):
    assert detect_kind(name, data) == kind


@pytest.mark.parametrize(
    "name, data",
    [
        ("coa.txt", b"hello"),  # wrong extension
        pytest.param(
            "coa.pdf",
            b"MZ\x90\x00",
            id="renamed-exe",
        ),
        ("coa.pdf", b""),  # empty
        ("coa.docx", b"%PDF-1.7"),  # not a zip
        pytest.param(
            "coa.docx",
            make_docx(with_body=False),
            id="zip-but-not-word",
        ),
        ("coa.doc", b"%PDF-1.7"),  # not an OLE file
        pytest.param(
            "coa.pdf", b"%PDF-" + b"0" * MAX_COA_BYTES, id="too-big"
        ),  # too big
    ],
)
def test_rejects_bad_files(name, data):
    with pytest.raises(CoaError):
        detect_kind(name, data)


def test_display_name_drops_folders_and_control_chars():
    assert (
        safe_display_name("C:\\Users\\x\\BTR COA\x07 batch 12.pdf")
        == "BTR COA batch 12.pdf"
    )
    assert safe_display_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_display_name("") == "coa"
