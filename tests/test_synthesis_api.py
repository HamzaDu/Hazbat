"""Synthesis step endpoints (routers/synthesis.py).

Needs a database with the dev seed (dev / dev login); skipped if none can be
reached. A fixture adds a test material and deletes it afterwards (its steps
go with it).

pytest -q tests/test_synthesis_api.py
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
TEST_MATERIAL = "CAT-TEST-SYNTH-3"
STEPS_URL = f"/api/materials/{TEST_MATERIAL}/synthesis"


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
    """A test material, deleted afterwards along with its steps."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO tbl_materials (material_id) VALUES (%s)", (TEST_MATERIAL,))
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


def test_list_starts_empty(client, material):
    response = client.get(STEPS_URL)
    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == TEST_MATERIAL
    assert data["steps"] == []
    assert "calcination" in data["step_types"]


def test_add_then_list(client, material):
    response = client.post(
        STEPS_URL, json={"step_type": "calcination", "temperature_c": "900"}
    )
    assert response.status_code == 201
    step = response.json()["step"]
    assert step["step_no"] == 1
    assert step["temperature_c"] == 900.0
    steps = client.get(STEPS_URL).json()["steps"]
    assert [s["step_id"] for s in steps] == [step["step_id"]]


def test_add_invalid_is_400(client, material):
    response = client.post(STEPS_URL, json={"step_type": "drying", "duration_h": -1})
    assert response.status_code == 400
    assert "Duration" in response.json()["error"]


def test_add_duplicate_step_no_is_400(client, material):
    client.post(STEPS_URL, json={"step_type": "mixing", "step_no": 1})
    response = client.post(STEPS_URL, json={"step_type": "drying", "step_no": 1})
    assert response.status_code == 400
    assert "already exists" in response.json()["error"]


def test_missing_material_is_404(client):
    url = "/api/materials/CAT-TEST-SYNTH-MISSING/synthesis"
    assert client.get(url).status_code == 404
    assert client.post(url, json={"step_type": "mixing"}).status_code == 404


def test_body_must_be_an_object(client, material):
    assert client.post(STEPS_URL, json=["mixing"]).status_code == 422


def test_update(client, material):
    step = client.post(STEPS_URL, json={"step_type": "mixing"}).json()["step"]
    url = f"/api/synthesis/{step['step_id']}"
    response = client.put(url, json={"step_type": "milling", "duration_h": 2})
    assert response.status_code == 200
    assert response.json()["step"]["step_type"] == "milling"
    assert response.json()["step"]["duration_h"] == 2.0
    response = client.put(url, json={"step_type": "milling", "duration_h": 0})
    assert response.status_code == 400


def test_update_missing_step_is_404(client):
    response = client.put("/api/synthesis/-1", json={"step_type": "mixing"})
    assert response.status_code == 404


def test_delete(client, material):
    step = client.post(STEPS_URL, json={"step_type": "sieving"}).json()["step"]
    url = f"/api/synthesis/{step['step_id']}"
    assert client.delete(url).status_code == 200
    assert client.delete(url).status_code == 404
    assert client.get(STEPS_URL).json()["steps"] == []


def test_not_logged_in_is_redirected(material):
    anonymous = TestClient(main.app, follow_redirects=False)
    response = anonymous.post(STEPS_URL, json={"step_type": "mixing"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert anonymous.get(STEPS_URL).status_code == 303


def test_bad_api_key_is_401(material):
    anonymous = TestClient(main.app, follow_redirects=False)
    headers = {"Authorization": "Bearer not-a-real-key"}
    assert anonymous.get(STEPS_URL, headers=headers).status_code == 401


def test_nothing_added_without_login(client, material):
    anonymous = TestClient(main.app, follow_redirects=False)
    anonymous.post(STEPS_URL, json={"step_type": "mixing"})
    assert client.get(STEPS_URL).json()["steps"] == []
