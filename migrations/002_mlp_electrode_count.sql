-- Adds cathode/anode counts to MLP cells in an existing Hazbat database
-- (new databases get them from schemas/0000_schema.sql).
-- Run once:  gosu postgres psql -d bmac -v ON_ERROR_STOP=1 -f migrations/002_mlp_electrode_count.sql
ALTER TABLE tbl_mlp
    ADD COLUMN IF NOT EXISTS cathode_count INTEGER
        CHECK (cathode_count BETWEEN 1 AND 100);
-- Existing cells keep NULL ("not recorded") instead of a made-up 1. These two
-- lines also relax a database that ran an earlier version of this file.
ALTER TABLE tbl_mlp ALTER COLUMN cathode_count DROP NOT NULL;
ALTER TABLE tbl_mlp ALTER COLUMN cathode_count DROP DEFAULT;
ALTER TABLE tbl_mlp
    ADD COLUMN IF NOT EXISTS anode_count INTEGER GENERATED ALWAYS AS (cathode_count + 1) STORED;
