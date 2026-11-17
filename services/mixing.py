"""Mixing runs: read an Eirich mixer log, split it into stages, save and look it up.

Tables: tbl_mixing_run, tbl_mixing_ingredient, tbl_mixing_stage, tbl_mixing_log,
and tbl_coating.mixing_id (the slurry a coating was made from).

Reading a log and finding its stages need no database (parse_mixer_xlsx,
find_stages), so tests can run them on their own.
"""

import hashlib
import io
import re

import pandas as pd
from psycopg2.extras import execute_values

from core.db import get_connection

ROTOR_ON_RPM = 100  # above this the rotor counts as running
MIN_STAGE_S = 5  # shorter blips are ignored
MAX_LOG_BYTES = 10 * 1024 * 1024
ID_PATTERN = re.compile(r"^MIX-[A-Za-z0-9_-]{1,40}$")
ROLES = (
    "Active material",
    "Binder",
    "Conductive additive",
    "Solvent",
    "Other",
)

# Spreadsheet column (units stripped) -> database column
LOG_COLUMNS = {
    "RotorRev": "rotor_rpm",
    "RotorPower": "rotor_power_w",
    "MixingPanRev": "pan_rpm",
    "MixingPanPower": "pan_power_w",
    "Temperature": "temperature_c",
    "Total Power": "total_power_w",
    "Cumulative Energy (J)": "cumulative_energy_j",
}

# Summary block (columns P:Q of the log) -> tbl_mixing_run column
SUMMARY_LABELS = {
    "Total Energy": "total_energy_kj",
    "1st Addition Energy": "first_addition_energy_kj",
    "Knead Energy": "knead_energy_kj",
    "Peak Power": "peak_power_w",
}

STAGE_COLUMNS = (
    "stage_no",
    "start_s",
    "duration_s",
    "pause_before_s",
    "rotor_rpm",
    "pan_rpm",
    "mean_power_w",
    "peak_power_w",
    "energy_kj",
)


class MixingError(ValueError):
    """A log or form value was rejected; the message is shown to the user."""


# --- Reading a log -------------------------------------------------------------


def parse_mixer_xlsx(data: bytes):
    """Returns (summary dict, log DataFrame with t_s and the LOG_COLUMNS names).

    Rows without a timestamp are dropped, and so is any row whose time does not
    move forward (the export repeats or rewinds the clock at the very end).
    """
    try:
        sheet = pd.read_excel(io.BytesIO(data), header=0)
    except Exception as e:  # unreadable, or not a workbook
        raise MixingError(f"Could not read the spreadsheet: {e}") from None

    sheet.columns = [str(c).split(" [")[0].strip() for c in sheet.columns]
    needed = {"Date", "Time", "RotorRev", "Total Power"}
    missing = needed - set(sheet.columns)
    if missing:
        raise MixingError(f"Missing columns: {', '.join(sorted(missing))}.")

    log = sheet.dropna(subset=["Date", "Time"]).copy()
    stamp = pd.to_datetime(
        log["Date"].dt.strftime("%Y-%m-%d") + " " + log["Time"].astype(str)
    )
    log["t_s"] = (stamp - stamp.iloc[0]).dt.total_seconds().round().astype(int)
    log = log[log["t_s"] > log["t_s"].cummax().shift(fill_value=-1)]
    if len(log) < 10:
        raise MixingError("The log has fewer than 10 usable rows.")

    summary = {}
    if {"Unnamed: 15", "Unnamed: 16"} <= set(sheet.columns):
        for label, value in zip(
            sheet["Unnamed: 15"], sheet["Unnamed: 16"], strict=True
        ):
            if label in SUMMARY_LABELS and pd.notna(value):
                summary[SUMMARY_LABELS[label]] = float(value)
    summary["started_at"] = stamp.iloc[0].to_pydatetime()
    summary["duration_s"] = int(log["t_s"].iloc[-1])

    keep = ["t_s", *[c for c in LOG_COLUMNS if c in log.columns]]
    log = log[keep].rename(columns=LOG_COLUMNS).reset_index(drop=True)
    return summary, log


def find_stages(log: pd.DataFrame) -> pd.DataFrame:
    """One row per rotor-on period, with the columns in STAGE_COLUMNS."""
    on = log["rotor_rpm"] > ROTOR_ON_RPM
    block = (on != on.shift()).cumsum()
    rows, last_end = [], -1
    for _, part in log[on].groupby(block[on]):
        if len(part) < MIN_STAGE_S:
            continue
        start, end = int(part["t_s"].iloc[0]), int(part["t_s"].iloc[-1])
        power = part["total_power_w"]
        rows.append(
            {
                "stage_no": len(rows) + 1,
                "start_s": start,
                "duration_s": end - start + 1,
                "pause_before_s": max(start - last_end - 1, 0),
                "rotor_rpm": float(part["rotor_rpm"].median()),
                "pan_rpm": float(part["pan_rpm"].median()),
                "mean_power_w": float(power.mean()),
                "peak_power_w": float(power.max()),
                "energy_kj": float(power.sum() / 1000),  # one row per second
            }
        )
        last_end = end
    return pd.DataFrame(rows, columns=list(STAGE_COLUMNS))


# --- Saving --------------------------------------------------------------------


def clean_ingredients(rows):
    """Check the ingredient rows from the form: (material_id, role, mass) triples,
    blank rows skipped. Returns (list of (material_id, role, mass_g), error).
    """
    cleaned, seen = [], set()
    for material_id, role, mass in rows:
        material_id, role, mass = (
            (material_id or "").strip(),
            (role or "").strip(),
            (mass or "").strip(),
        )
        if not (material_id or mass):
            continue
        if not material_id:
            return None, "Each ingredient needs a material."
        if material_id in seen:
            return None, f"{material_id} is listed twice."
        try:
            grams = float(mass)
        except ValueError:
            return None, f"Mass for {material_id} must be a number (got '{mass}')."
        if not grams > 0 or grams == float("inf"):
            return None, f"Mass for {material_id} must be more than zero."
        if role and role not in ROLES:
            return None, f"Role for {material_id} must be one of: {', '.join(ROLES)}."
        seen.add(material_id)
        cleaned.append((material_id, role or None, grams))
    return cleaned, None


def next_mixing_id() -> str:
    """The next free MIX-0001 style ID."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT mixing_id FROM tbl_mixing_run WHERE mixing_id ~ '^MIX-[0-9]+$'"
        )
        numbers = [int(r[0][4:]) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()
    return f"MIX-{max(numbers, default=0) + 1:04d}"


def save_mixing_run(
    mixing_id,
    project,
    made_by,
    filename,
    data,
    ingredients=(),
    coating_id=None,
    notes=None,
):
    """Parse the log and save the run, its stages, its log, its ingredients and the
    link to a coating, all in one transaction.

    ingredients: (material_id, role, mass_g) triples. Raises MixingError for a bad
    file, an ID that exists, a log that was loaded before, or an unknown material.
    """
    if not ID_PATTERN.match(mixing_id or ""):
        raise MixingError(
            "The mixing ID must look like MIX-0001 (letters, digits, - or _)."
        )
    if len(data) > MAX_LOG_BYTES:
        raise MixingError("The file is larger than 10 MB.")
    summary, log = parse_mixer_xlsx(data)
    stages = find_stages(log)
    digest = hashlib.sha256(data).hexdigest()

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT mixing_id FROM tbl_mixing_run "
            "WHERE mixing_id = %s OR source_sha256 = %s",
            (mixing_id, digest),
        )
        found = cur.fetchone()
        if found:
            if found[0] == mixing_id:
                raise MixingError(f"{mixing_id} already exists.")
            raise MixingError(f"This log has already been loaded as {found[0]}.")
        for material_id, _, _ in ingredients:
            cur.execute(
                "SELECT 1 FROM tbl_materials WHERE material_id = %s", (material_id,)
            )
            if not cur.fetchone():
                raise MixingError(f"Material {material_id} doesn't exist.")
        if coating_id:
            cur.execute(
                "SELECT 1 FROM tbl_coating WHERE coating_id = %s", (coating_id,)
            )
            if not cur.fetchone():
                raise MixingError(f"Coating {coating_id} doesn't exist.")

        columns = [
            "mixing_id",
            "project",
            "made_by",
            "source_filename",
            "source_sha256",
            "notes",
            *summary,
        ]
        cur.execute(
            f"INSERT INTO tbl_mixing_run ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            [mixing_id, project, made_by, filename, digest, notes, *summary.values()],
        )
        if len(stages):
            execute_values(
                cur,
                "INSERT INTO tbl_mixing_stage "
                f"(mixing_id, {', '.join(STAGE_COLUMNS)}) VALUES %s",
                [(mixing_id, *row) for row in stages.itertuples(index=False)],
            )
        log_columns = ["t_s", *[c for c in LOG_COLUMNS.values() if c in log.columns]]
        clean = log[log_columns].astype(object).where(log[log_columns].notna(), None)
        execute_values(
            cur,
            "INSERT INTO tbl_mixing_log "
            f"(mixing_id, {', '.join(log_columns)}) VALUES %s",
            [(mixing_id, *row) for row in clean.itertuples(index=False)],
            page_size=1000,
        )
        if ingredients:
            execute_values(
                cur,
                "INSERT INTO tbl_mixing_ingredient "
                "(mixing_id, material_id, role, mass_g) VALUES %s",
                [(mixing_id, *item) for item in ingredients],
            )
        if coating_id:
            cur.execute(
                "UPDATE tbl_coating SET mixing_id = %s WHERE coating_id = %s",
                (mixing_id, coating_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return {"stages": len(stages), "log_rows": len(log), **summary}


# --- Looking runs up -------------------------------------------------------------


def run_visible(project, allowed) -> bool:
    """Admins (allowed is None) see every run. Others see runs of their projects,
    and runs with no project (like materials, which belong to no project).
    """
    return allowed is None or project is None or project in allowed


def number(value):
    return None if value is None else float(value)


def list_runs(allowed):
    """The runs this user may see, newest first."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT mixing_id, project, started_at, duration_s, made_by "
            "FROM tbl_mixing_run ORDER BY started_at DESC NULLS LAST, mixing_id DESC"
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    return [
        {
            "mixing_id": r[0],
            "project": r[1],
            "started_at": r[2].isoformat(timespec="minutes") if r[2] else None,
            "duration_s": r[3],
            "made_by": r[4],
        }
        for r in rows
        if run_visible(r[1], allowed)
    ]


def get_run(mixing_id, allowed):
    """Everything about one run (summary, ingredients, stages, coatings, cells and
    the log as columns), or None if it doesn't exist or isn't visible.
    """
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT mixing_id, project, mixer, started_at, duration_s, "
            "total_energy_kj, "
            "first_addition_energy_kj, knead_energy_kj, peak_power_w, made_by, "
            "source_filename, notes FROM tbl_mixing_run WHERE mixing_id = %s",
            (mixing_id,),
        )
        row = cur.fetchone()
        if not row or not run_visible(row[1], allowed):
            return None
        keys = (
            "mixing_id project mixer started_at duration_s total_energy_kj "
            "first_addition_energy_kj knead_energy_kj peak_power_w made_by "
            "source_filename notes"
        ).split()
        run = dict(zip(keys, row, strict=True))
        run["started_at"] = (
            run["started_at"].isoformat(timespec="seconds")
            if run["started_at"]
            else None
        )
        for key in (
            "total_energy_kj",
            "first_addition_energy_kj",
            "knead_energy_kj",
            "peak_power_w",
        ):
            run[key] = number(run[key])

        cur.execute(
            "SELECT i.material_id, i.role, i.mass_g, m.chemistry "
            "FROM tbl_mixing_ingredient i "
            "LEFT JOIN tbl_materials m ON m.material_id = i.material_id "
            "WHERE i.mixing_id = %s ORDER BY i.material_id",
            (mixing_id,),
        )
        ingredients = [
            {
                "material_id": r[0],
                "role": r[1],
                "mass_g": number(r[2]),
                "chemistry": r[3],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            f"SELECT {', '.join(STAGE_COLUMNS)} FROM tbl_mixing_stage "
            "WHERE mixing_id = %s ORDER BY stage_no",
            (mixing_id,),
        )
        stages = [
            {k: number(v) for k, v in zip(STAGE_COLUMNS, r, strict=True)}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT coating_id, material_id FROM tbl_coating "
            "WHERE mixing_id = %s ORDER BY coating_id",
            (mixing_id,),
        )
        coatings = [{"coating_id": r[0], "material_id": r[1]} for r in cur.fetchall()]
        coating_ids = [c["coating_id"] for c in coatings]

        cells = []
        if coating_ids:
            for kind, table, id_col, cols in (
                ("slp", "tbl_slp", "slp_id", ("coating_id",)),
                ("coincell", "tbl_coincell", "coincell_id", ("coating_id",)),
                ("mlp", "tbl_mlp", "mlp_id", ("cat_coating_id", "an_coating_id")),
            ):
                for col in cols:
                    cur.execute(
                        f"SELECT {id_col}, {col} FROM {table} "
                        f"WHERE {col} = ANY(%s) ORDER BY {id_col}",
                        (coating_ids,),
                    )
                    cells += [
                        {"id": r[0], "type": kind, "coating_id": r[1]}
                        for r in cur.fetchall()
                    ]

        log_columns = ["t_s", *LOG_COLUMNS.values()]
        cur.execute(
            f"SELECT {', '.join(log_columns)} FROM tbl_mixing_log "
            "WHERE mixing_id = %s ORDER BY t_s",
            (mixing_id,),
        )
        log_rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    log = {col: [number(r[i]) for r in log_rows] for i, col in enumerate(log_columns)}
    return {
        "run": run,
        "ingredients": ingredients,
        "stages": stages,
        "coatings": coatings,
        "cells": cells,
        "log": log,
    }


def load_logs(allowed):
    """Every visible run's log and stages as DataFrames, for the model:
    a list of (mixing_id, log, stages).
    """
    log_columns = ["t_s", *LOG_COLUMNS.values()]
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    out = []
    try:
        cur.execute("SELECT mixing_id, project FROM tbl_mixing_run ORDER BY mixing_id")
        for mixing_id, project in cur.fetchall():
            if not run_visible(project, allowed):
                continue
            cur.execute(
                f"SELECT {', '.join(log_columns)} FROM tbl_mixing_log "
                "WHERE mixing_id = %s ORDER BY t_s",
                (mixing_id,),
            )
            log = pd.DataFrame(cur.fetchall(), columns=log_columns).astype(float)
            out.append((mixing_id, log, find_stages(log)))
    finally:
        cur.close()
        conn.close()
    return out
