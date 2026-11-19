-- Mixing (slurry) data: one run, its ingredients, its stages and the 1 Hz mixer log.
-- A coating points at the slurry it was made from. For an existing database run once:
--   gosu postgres psql -d bmac -v ON_ERROR_STOP=1 -f migrations/004_mixing.sql
-- (new databases get this from schemas/0000_schema.sql; renumber the file to the next free number)

CREATE TABLE IF NOT EXISTS tbl_mixing_run (
    mixing_id               TEXT PRIMARY KEY,                 -- e.g. MIX-0001
    project                 TEXT REFERENCES tbl_projects(project_name),
    mixer                   TEXT NOT NULL DEFAULT 'Eirich',
    started_at              TIMESTAMPTZ,
    duration_s              INTEGER CHECK (duration_s >= 0),
    total_energy_kj         NUMERIC,                          -- from the mixer's own summary
    first_addition_energy_kj NUMERIC,
    knead_energy_kj         NUMERIC,
    peak_power_w            NUMERIC,
    made_by                 TEXT,
    source_filename         TEXT,
    source_sha256           TEXT,                             -- stops the same log being loaded twice
    notes                   TEXT,
    UNIQUE (source_sha256)
);

-- What went into the slurry. Each ingredient is a material already in tbl_materials.
CREATE TABLE IF NOT EXISTS tbl_mixing_ingredient (
    mixing_id       TEXT NOT NULL REFERENCES tbl_mixing_run(mixing_id) ON DELETE CASCADE,
    material_id     TEXT NOT NULL REFERENCES tbl_materials(material_id),
    role            TEXT,                                     -- active material, binder, conductive additive, solvent ...
    mass_g          NUMERIC CHECK (mass_g > 0),
    added_in_stage  INTEGER,                                  -- stage_no it was added before; NULL if unknown
    PRIMARY KEY (mixing_id, material_id)
);

-- A rotor-on period of the run, worked out from the log (services/mixing.py).
CREATE TABLE IF NOT EXISTS tbl_mixing_stage (
    mixing_id       TEXT NOT NULL REFERENCES tbl_mixing_run(mixing_id) ON DELETE CASCADE,
    stage_no        INTEGER NOT NULL CHECK (stage_no > 0),
    start_s         INTEGER NOT NULL,
    duration_s      INTEGER NOT NULL CHECK (duration_s > 0),
    pause_before_s  INTEGER NOT NULL DEFAULT 0,               -- rotor-off time before the stage (additions, scraping)
    rotor_rpm       NUMERIC,
    pan_rpm         NUMERIC,
    mean_power_w    NUMERIC,
    peak_power_w    NUMERIC,
    energy_kj       NUMERIC,
    PRIMARY KEY (mixing_id, stage_no)
);

-- The raw log, one row per second. Redundant columns (m/s, kJ, kWh) are not stored.
CREATE TABLE IF NOT EXISTS tbl_mixing_log (
    mixing_id           TEXT NOT NULL REFERENCES tbl_mixing_run(mixing_id) ON DELETE CASCADE,
    t_s                 INTEGER NOT NULL,                     -- seconds since the first row
    rotor_rpm           NUMERIC,
    rotor_power_w       NUMERIC,
    pan_rpm             NUMERIC,
    pan_power_w         NUMERIC,
    temperature_c       NUMERIC,
    total_power_w       NUMERIC,
    cumulative_energy_j NUMERIC,
    PRIMARY KEY (mixing_id, t_s)
);

-- The link to coatings: the slurry a coating was made from (NULL when unknown).
ALTER TABLE tbl_coating
    ADD COLUMN IF NOT EXISTS mixing_id TEXT REFERENCES tbl_mixing_run(mixing_id);
CREATE INDEX IF NOT EXISTS idx_coating_mixing ON tbl_coating (mixing_id);

INSERT INTO tbl_unprivileged_tables (table_name) VALUES
    ('tbl_mixing_run'), ('tbl_mixing_ingredient'), ('tbl_mixing_stage'), ('tbl_mixing_log')
ON CONFLICT (table_name) DO NOTHING;
