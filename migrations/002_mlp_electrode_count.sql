-- Adds cathode/anode counts to MLP cells in an existing Hazbat database
-- (new databases get them from schemas/0000_schema.sql).
-- Run once:  gosu postgres psql -d bmac -v ON_ERROR_STOP=1 -f migrations/002_mlp_electrode_count.sql
ALTER TABLE tbl_mlp
    ADD COLUMN IF NOT EXISTS cathode_count INTEGER NOT NULL DEFAULT 1
        CHECK (cathode_count BETWEEN 1 AND 100);
ALTER TABLE tbl_mlp
    ADD COLUMN IF NOT EXISTS anode_count INTEGER GENERATED ALWAYS AS (cathode_count + 1) STORED;
