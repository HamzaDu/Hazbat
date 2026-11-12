"""Synthesis route page (GET /materials/{id}/synthesis) and its link on the card.

Needs a database with the dev seed (dev / dev login); skipped if none can be
reached. A fixture adds a test material and deletes it afterwards (its steps
go with it). The page's JavaScript is checked by hand.

pytest -q tests/test_synthesis_page.py
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg2 import OperationalError

import main
from core.db import get_connection

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Starts with CAT so detect_record_type sees a material
TEST_MATERIAL = "CAT-TEST-SYNTH-4"
PAGE_URL = f"/materials/{TEST_MATERIAL}/synthesis"
SEEDED_CELL = "CAT-NMC-001-C001-SLP-01"  # from the dev seed


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not database_available(), reason="no database reachable (set DATABASE_URL)"
)


@pytest.fixture(scope="module")
def client():
    """A logged-in browser session (dev / dev from the dev seed)."""
    c = TestClient(main.app, follow_redirects=False)
    response = c.post("/login", data={"username": "dev", "password": "dev"})
    assert response.status_code == 303, "dev login failed - is the dev seed loaded?"
    return c


@pytest.fixture
def material():
    """A test material whose chemistry contains HTML, deleted afterwards."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tbl_materials (material_id, chemistry) VALUES (%s, %s)",
        (TEST_MATERIAL, "<b>NMC</b>"),
    )
    conn.commit()
    try:
        yield TEST_MATERIAL
    finally:
        cur.execute(
            "DELETE FROM tbl_materials WHERE material_id = %s", (TEST_MATERIAL,)
        )
        conn.commit()
        cur.close()
        conn.close()


def test_page_shows_form_and_script(client, material):
    response = client.get(PAGE_URL)
    assert response.status_code == 200
    assert TEST_MATERIAL in response.text
    assert "data-step-form" in response.text
    assert "/static/js/synthesis.js" in response.text
    assert '<option value="calcination">' in response.text


def test_page_escapes_material_fields(client, material):
    text = client.get(PAGE_URL).text
    assert "<b>NMC</b>" not in text
    assert "&lt;b&gt;NMC&lt;/b&gt;" in text


def test_page_does_not_echo_step_text(client, material):
    client.post(
        f"/api/materials/{TEST_MATERIAL}/synthesis",
        json={"step_type": "mixing", "notes": "<script>alert(1)</script>"},
    )
    assert "<script>alert(1)</script>" not in client.get(PAGE_URL).text


def test_unknown_material_is_404(client):
    assert client.get("/materials/CAT-TEST-SYNTH-MISSING/synthesis").status_code == 404


def test_non_material_is_404(client):
    assert client.get(f"/materials/{SEEDED_CELL}/synthesis").status_code == 404


def test_not_logged_in_is_redirected(material):
    anonymous = TestClient(main.app, follow_redirects=False)
    response = anonymous.get(PAGE_URL)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_material_card_links_to_page(client, material):
    text = client.get(f"/card/{TEST_MATERIAL}").text
    assert f'href="{PAGE_URL}"' in text
    assert "Synthesis route" in text


def test_cell_card_has_no_link(client):
    response = client.get(f"/card/{SEEDED_CELL}")
    if response.status_code == 404:
        pytest.skip("dev seed cell not found")
    assert "Synthesis route" not in response.text


def test_script_is_served(client):
    response = client.get("/static/js/synthesis.js")
    assert response.status_code == 200
    assert "textContent" in response.text
