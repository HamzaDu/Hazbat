"""Mixing page and API against a real database (needs the dev seed, as the smoke test).

pytest -q tests/test_mixing_page.py
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg2 import OperationalError

import main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core.db import get_admin_connection, get_connection  # noqa: E402
from tests.test_mixing import make_xlsx  # noqa: E402

PREFIX = "MIX-TEST"
# Five rotor-on stages of 15 s, with pauses between them
ROTOR = ([3500] * 15 + [0] * 5 + [2400] * 15 + [0] * 5) * 2 + [3500] * 15


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not database_available(), reason="no database reachable (set DATABASE_URL)"
)


def one(sql):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def clean_up():
    conn = get_admin_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tbl_coating SET mixing_id = NULL WHERE mixing_id LIKE %s",
        (PREFIX + "%",),
    )
    cur.execute("DELETE FROM tbl_mixing_run WHERE mixing_id LIKE %s", (PREFIX + "%",))
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture(scope="module")
def client():
    clean_up()
    c = TestClient(main.app, follow_redirects=False)
    assert (
        c.post("/login", data={"username": "dev", "password": "dev"}).status_code == 303
    )
    yield c
    clean_up()


@pytest.fixture(scope="module")
def ids():
    return {
        "material": one("SELECT material_id FROM tbl_materials ORDER BY 1 LIMIT 1"),
        "coating": one("SELECT coating_id FROM tbl_coating ORDER BY 1 LIMIT 1"),
        "project": one(
            "SELECT project_name FROM tbl_projects WHERE active ORDER BY 1 LIMIT 1"
        ),
    }


def upload(client, ids, mixing_id, data=None, filename="log.xlsx", **extra):
    form = {
        "mixing_id": mixing_id,
        "project": ids["project"],
        "made_by": "Test User",
        "coating_id": "",
        "notes": "",
        **extra,
    }
    files = {
        "file": (
            filename,
            data if data is not None else make_xlsx(ROTOR),
            "application/octet-stream",
        )
    }
    return client.post("/mixing", data=form, files=files)


def test_login_needed():
    anonymous = TestClient(main.app, follow_redirects=False)
    assert anonymous.get("/mixing").status_code in (302, 303, 307)
    assert anonymous.get("/api/mixing").status_code in (302, 303, 307)


def test_page_opens(client):
    page = client.get("/mixing")
    assert page.status_code == 200
    assert "Add a mixing run".upper() in page.text.upper()


def test_wrong_file_type_rejected(client, ids):
    response = upload(client, ids, f"{PREFIX}-A", data=b"not excel", filename="log.csv")
    assert response.status_code == 400
    assert ".xlsx" in response.text


def test_unreadable_workbook_rejected(client, ids):
    response = upload(client, ids, f"{PREFIX}-B", data=b"not excel")
    assert response.status_code == 400
    assert "Could not read" in response.text


def test_bad_id_rejected(client, ids):
    assert upload(client, ids, "RUN-1").status_code == 400


def test_unknown_material_saves_nothing(client, ids):
    response = upload(
        client,
        ids,
        f"{PREFIX}-C",
        ingredient_material=["CAT-NOPE-999"],
        ingredient_role=["Binder"],
        ingredient_mass=["5"],
    )
    assert response.status_code == 400
    assert client.get(f"/api/mixing/{PREFIX}-C").status_code == 404


def test_save_and_read_back(client, ids):
    response = upload(
        client,
        ids,
        f"{PREFIX}-1",
        coating_id=ids["coating"],
        ingredient_material=[ids["material"]],
        ingredient_role=["Active material"],
        ingredient_mass=["250.5"],
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/mixing?run={PREFIX}-1&saved=1"

    run = client.get(f"/api/mixing/{PREFIX}-1").json()
    assert len(run["stages"]) == 5
    assert run["stages"][1]["pause_before_s"] == 5
    assert run["ingredients"][0]["material_id"] == ids["material"]
    assert run["ingredients"][0]["mass_g"] == 250.5
    assert [c["coating_id"] for c in run["coatings"]] == [ids["coating"]]
    assert len(run["log"]["t_s"]) == len(run["log"]["total_power_w"]) == len(ROTOR)

    listed = [r["mixing_id"] for r in client.get("/api/mixing").json()["runs"]]
    assert f"{PREFIX}-1" in listed
    assert client.get(f"/mixing?run={PREFIX}-1").status_code == 200


def test_same_log_twice_rejected(client, ids):
    response = upload(client, ids, f"{PREFIX}-2")
    assert response.status_code == 400
    assert f"already been loaded as {PREFIX}-1" in response.text


def test_same_id_twice_rejected(client, ids):
    other = make_xlsx(ROTOR + [0] * 3)
    response = upload(client, ids, f"{PREFIX}-1", data=other)
    assert response.status_code == 400
    assert "already exists" in response.text


def test_model_trains(client):
    result = client.get("/api/mixing/model")
    assert result.status_code == 200
    body = result.json()
    assert body["stages"] >= 4 and body["runs"] >= 1
    assert f"{PREFIX}-1" in body["per_run"]
    assert {"r2", "mae_w", "baseline_r2", "importance", "scatter"} <= body.keys()


def test_unknown_run_is_404(client):
    assert client.get("/api/mixing/MIX-NOPE").status_code == 404
