#!/bin/sh
# Runs once, on first initialisation of the Postgres volume. Creates the database the
# backend test suite uses (<POSTGRES_DB>_test). The suite refuses any DB not ending in _test.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE \"${POSTGRES_DB}_test\" OWNER \"${POSTGRES_USER}\""
