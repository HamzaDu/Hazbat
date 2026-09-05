-- BMAC PostgreSQL schema
-- Migrated from the Access backend, same ID convention and relationships,
-- but with FK constraints enforced natively by Postgres.

CREATE TABLE tbl_projects (
    project_name    TEXT PRIMARY KEY,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE tbl_materials (
    material_id     TEXT PRIMARY KEY,
    chemistry       TEXT,
    supplier        TEXT,
    date_received   DATE,
    quantity_kg     NUMERIC,
    location        TEXT,
    availability    TEXT,
    notes           TEXT
);

CREATE TABLE tbl_coating (
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
    ('Shared', TRUE);

    CREATE TABLE tbl_slp (
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

CREATE TABLE tbl_coincell (
    coincell_id         TEXT PRIMARY KEY,
    coating_id            TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    project                TEXT REFERENCES tbl_projects(project_name),
    date_made              DATE,
    made_by                TEXT,
    electrolyte            TEXT,
    formation_capacity     NUMERIC,
    cell_type              TEXT
);

CREATE TABLE tbl_mlp (
    mlp_id              TEXT PRIMARY KEY,
    cat_coating_id       TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    an_coating_id        TEXT NOT NULL REFERENCES tbl_coating(coating_id),
    project               TEXT REFERENCES tbl_projects(project_name),
    date_made             DATE,
    electrolyte           TEXT,
    cell_capacity         NUMERIC,
    ac_area_ratio         NUMERIC
);