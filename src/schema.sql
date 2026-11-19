PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS index_root (
    id      INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    path    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS directories (
    id              INTEGER NOT NULL PRIMARY KEY,
    parent_id       INTEGER REFERENCES directories(id),
    name            TEXT NOT NULL,
    path            TEXT UNIQUE NOT NULL,
    depth           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id                  INTEGER NOT NULL PRIMARY KEY,
    directory_id        INTEGER REFERENCES directories(id),
    name                TEXT NOT NULL,
    path                TEXT UNIQUE NOT NULL,
    normalized_path     TEXT NOT NULL,
    language            TEXT,
    content_hash        TEXT NOT NULL,
    mtime_ns            INTEGER NOT NULL,
    size_bytes          INTEGER NOT NULL,
    line_count          INTEGER NOT NULL DEFAULT 0,
    is_test             INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    qualified_name      TEXT NOT NULL,
    kind                TEXT NOT NULL,
    config_start_line   INTEGER NOT NULL,
    config_end_line     INTEGER NOT NULL,
    description         TEXT NULL,
    snapshot_hash            TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS models_qualified_name_index ON models (qualified_name);

CREATE TABLE IF NOT EXISTS macros (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS macros_name_index ON macros (name);

CREATE TABLE IF NOT EXISTS model_macros (
    macro_name          TEXT NOT NULL REFERENCES macros(name),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    PRIMARY KEY (macro_name, model_id)
);
CREATE INDEX IF NOT EXISTS model_macros_model_id_index ON model_macros (model_id, macro_name);

CREATE TABLE IF NOT EXISTS audits (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    name                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS audits_name_index ON audits (name);

CREATE TABLE IF NOT EXISTS model_audits (
    audit_name          TEXT NOT NULL REFERENCES audits(name),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    PRIMARY KEY (audit_name, model_id)
);
CREATE INDEX IF NOT EXISTS model_audits_model_id_index ON model_audits (model_id, audit_name);

CREATE TABLE IF NOT EXISTS columns (
    id                  INTEGER NOT NULL PRIMARY KEY,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    query_name          TEXT NOT NULL,
    from_table          TEXT NULL,
    name                TEXT NOT NULL,
    qualified_name      TEXT NOT NULL,
    data_type           TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    context             TEXT NOT NULL,
    description         TEXT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS columns_qualified_name_index ON columns (qualified_name);

CREATE TABLE IF NOT EXISTS column_lineage (
    id                              INTEGER NOT NULL PRIMARY KEY,
    ref_column_id                   INTEGER NOT NULL REFERENCES columns(id),
    ref_column_model_id             INTEGER NOT NULL REFERENCES models(id),
    ref_column_query_name           TEXT NOT NULL,
    ref_column_qualified_name       TEXT NOT NULL,
    source_column_id                INTEGER NOT NULL REFERENCES columns(id),
    source_models_id                INTEGER NOT NULL REFERENCES models(id),
    source_query_name               TEXT NOT NULL,
    source_column_qualified_name    TEXT NOT NULL,
    source_line                     INTEGER NOT NULL,
    ref_kind                        TEXT NOT NULL,
    context                         TEXT NOT NULL,
    snapshot_hash                   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tests (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    name                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS tests_file_id_name_index ON tests (file_id, name);

CREATE TABLE IF NOT EXISTS test_references (
    test_id             INTEGER NOT NULL REFERENCES tests(id),
    column_id           INTEGER NOT NULL REFERENCES columns(id),
    PRIMARY KEY (test_id, column_id)
);
CREATE INDEX IF NOT EXISTS test_references_column_id_index ON test_references (column_id, test_id);
