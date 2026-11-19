-- Adds the synthesis step table to an existing Hazbat database
-- (new databases get it from schemas/0000_schema.sql).
-- Run once:  gosu postgres psql -d bmac -v ON_ERROR_STOP=1 -f migrations/003_synthesis_step.sql
-- then rerun scripts.dbgen (or restart the app) to grant the roles access.

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
