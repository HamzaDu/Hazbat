#!/bin/bash

trap 'kill -INT $(jobs -p); wait; exit 0' TERM INT

source /opt/venv/bin/activate

cron

if [ -n "$START_LOCAL_DB" ]; then
    mkdir -p /run/postgresql
    chown postgres /run/postgresql
    mkdir -p "$PGDATA"
    [ "$(stat -c %U "$PGDATA")" = postgres ] || chown -R postgres "$PGDATA"
    [ -f "$PGDATA/PG_VERSION" ] || gosu postgres initdb -D "$PGDATA" --auth-local=trust --auth-host=scram-sha-256

    gosu postgres postgres -D "$PGDATA" &
    until gosu postgres pg_isready -q; do sleep 0.2; done

    gosu postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='bmac'" | grep -q 1 || gosu postgres createdb bmac
fi

cd /app || exit 1

python3 -m scripts.initconfig || exit 1
python3 -m scripts.dbgen || exit 1

if [ -n "$SEED_SQL" ]; then
    gosu postgres psql -d bmac -v ON_ERROR_STOP=1 -f "$SEED_SQL" || exit 1
fi

gosu app python3 -m scripts.serve &

wait
