-- BMAC PostgreSQL schema
-- Migrated from the Access backend, same ID convention and relationships,
-- but with FK constraints enforced natively by Postgres.

CREATE TABLE IF NOT EXISTS tbl_projects (
    project_name    TEXT PRIMARY KEY,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS tbl_materials (
    material_id     TEXT PRIMARY KEY,
    chemistry       TEXT,
    supplier        TEXT,
    date_received   DATE,
    quantity_kg     NUMERIC,
    location        TEXT,
    availability    TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS tbl_coating (
    coating_id      TEXT PRIMARY KEY,
    material_id     TEXT NOT NULL REFERENCES tbl_materials(material_id),
    project         TEXT REFERENCES tbl_projects(project_name),
    coating_date    DATE,
    made_by         TEXT,
    coat_weight_gsm NUMERIC,
    porosity        NUMERIC,
    notes           TEXT
);

INSERT INTO tbl_projects (project_name, active) VALUES
    ('LEAP', TRUE),
    ('FAST', TRUE),
    ('Shared', TRUE)
ON CONFLICT (project_name) DO NOTHING;


CREATE TABLE IF NOT EXISTS tbl_slp (
    slp_id              TEXT PRIMARY KEY,
    coating_id           TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    project               TEXT REFERENCES tbl_projects(project_name),
    date_made             DATE,
    made_by               TEXT,
    electrolyte           TEXT,
    formation_capacity    NUMERIC,
    np_ratio              NUMERIC,
    notes                 TEXT
);

CREATE TABLE IF NOT EXISTS tbl_coincell (
    coincell_id         TEXT PRIMARY KEY,
    coating_id            TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    project                TEXT REFERENCES tbl_projects(project_name),
    date_made              DATE,
    made_by                TEXT,
    electrolyte            TEXT,
    formation_capacity     NUMERIC,
    cell_type              TEXT,
    gsm                    NUMERIC,
    notes                  TEXT
);

CREATE TABLE IF NOT EXISTS tbl_mlp (
    mlp_id              TEXT PRIMARY KEY,
    cat_coating_id       TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    an_coating_id        TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    project               TEXT REFERENCES tbl_projects(project_name),
    date_made             DATE,
    electrolyte           TEXT,
    cell_capacity         NUMERIC,
    ac_area_ratio         NUMERIC
);

CREATE TABLE IF NOT EXISTS tbl_users (
    user_id         SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    full_name       TEXT,
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    locked          BOOLEAN NOT NULL DEFAULT FALSE,
    twofa_interval  INTERVAL NOT NULL DEFAULT '0 seconds'
);

-- Which projects each (non-admin) user can see. Read at login.
CREATE TABLE IF NOT EXISTS tbl_user_projects (
    user_id         INTEGER NOT NULL REFERENCES tbl_users(user_id) ON DELETE CASCADE,
    project_name    TEXT NOT NULL REFERENCES tbl_projects(project_name),
    PRIMARY KEY (user_id, project_name)
);

-- API keys for non-browser clients. Only a hash of each key is stored.
CREATE TABLE IF NOT EXISTS tbl_api_keys (
    key_id          SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES tbl_users(user_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    key_hash        TEXT UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ
);

-- Second factors. data holds what the method needs, so a new method needs no schema change.
CREATE TABLE IF NOT EXISTS tbl_user_2fa (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES tbl_users(user_id) ON DELETE CASCADE,
    method          TEXT NOT NULL,
    name            TEXT NOT NULL,
    data            JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at    TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ
);

-- Single-use recovery codes, stored hashed.
CREATE TABLE IF NOT EXISTS tbl_user_recovery_codes (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES tbl_users(user_id) ON DELETE CASCADE,
    code_hash       TEXT NOT NULL,
    used_at         TIMESTAMPTZ
);

-- Uploaded BioLogic .mpr cycling files, linked to a cell record.
CREATE TABLE IF NOT EXISTS tbl_cycling_data (
    cycling_id        SERIAL PRIMARY KEY,
    record_id         TEXT NOT NULL,
    filename          TEXT,
    file_path         TEXT NOT NULL,
    num_points        INTEGER,
    max_capacity_mah  NUMERIC,
    num_cycles        INTEGER,
    uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tables the read/write and read-only roles may use. Every other table is admin-only.
-- A later file that adds a non-sensitive table inserts it here.
CREATE TABLE IF NOT EXISTS tbl_unprivileged_tables (
    table_name      TEXT PRIMARY KEY
);

INSERT INTO tbl_unprivileged_tables (table_name) VALUES
    ('tbl_projects'),
    ('tbl_materials'),
    ('tbl_coating'),
    ('tbl_slp'),
    ('tbl_coincell'),
    ('tbl_mlp'),
    ('tbl_cycling_data')
ON CONFLICT (table_name) DO NOTHING;

-- Certificates of Analysis (COA) attached to a material. Several versions can be
-- kept per material; pages show the newest. Files live in uploads/coa/<material_id>/.
-- preview_path is a PDF copy used for in-browser preview (the original for PDFs,
-- a LibreOffice conversion for Word files; NULL if conversion failed).
CREATE TABLE IF NOT EXISTS tbl_material_coa (
    coa_id          SERIAL PRIMARY KEY,
    material_id     TEXT NOT NULL REFERENCES tbl_materials(material_id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    file_kind       TEXT NOT NULL CHECK (file_kind IN ('pdf', 'docx', 'doc')),
    file_path       TEXT NOT NULL,
    preview_path    TEXT,
    size_bytes      INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    uploaded_by     TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_material_coa_material ON tbl_material_coa (material_id, uploaded_at DESC);

INSERT INTO tbl_unprivileged_tables (table_name) VALUES
    ('tbl_material_coa')
ON CONFLICT (table_name) DO NOTHING;

-- Synthesis steps for a material, in order. step_no starts at 1.
-- The UNIQUE constraint's index also serves lookups by material.
CREATE TABLE IF NOT EXISTS tbl_material_synthesis_step (
    step_id         SERIAL PRIMARY KEY,
    material_id     TEXT NOT NULL REFERENCES tbl_materials(material_id) ON DELETE CASCADE,
    step_no         INTEGER NOT NULL CHECK (step_no > 0),
    step_type       TEXT NOT NULL,
    temperature_c   NUMERIC CHECK (temperature_c BETWEEN -273 AND 2000),
    duration_h      NUMERIC CHECK (duration_h > 0),
    atmosphere      TEXT,
    equipment       TEXT,
    notes           TEXT,
    performed_by    TEXT,
    performed_on    DATE,
    UNIQUE (material_id, step_no)
);

INSERT INTO tbl_unprivileged_tables (table_name) VALUES
    ('tbl_material_synthesis_step')
ON CONFLICT (table_name) DO NOTHING;
