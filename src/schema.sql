PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS watermarks (
    id                  INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    last_full_parse     INTEGER NOT NULL DEFAULT 0,
    last_incremental    INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO watermarks (id, last_full_parse, last_incremental) VALUES (1, 0, 0);

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
    line_count          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS models (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER REFERENCES files(id),
    qualified_name      TEXT NOT NULL,
    kind                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS models_qualified_name_index ON models (qualified_name);

CREATE TABLE IF NOT EXISTS macros (
    id                  INTEGER NOT NULL PRIMARY KEY,
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_macros (
    macro_name          TEXT NOT NULL,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    PRIMARY KEY (macro_name, model_id)
);
CREATE INDEX IF NOT EXISTS model_macros_model_id_index ON model_macros (model_id);

CREATE TABLE IF NOT EXISTS columns (
    id                  INTEGER NOT NULL PRIMARY KEY,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    query_name          TEXT NOT NULL,
    from_table          TEXT NULL,
    name                TEXT NOT NULL,
    qualified_name      TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    context             TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS columns_qualified_name_index ON columns (qualified_name);

CREATE TABLE IF NOT EXISTS column_references_staging (
    id                              INTEGER NOT NULL,
    ref_column_qualified_name       TEXT NOT NULL,
    source_column_id                INTEGER REFERENCES columns(id),
    source_model_id                 INTEGER NOT NULL REFERENCES models(id),
    source_column_qualified_name    TEXT NULL,
    source_line                     INTEGER NOT NULL,
    source_column                   INTEGER NOT NULL,
    ref_kind                        TEXT NOT NULL,
    context                         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS column_references (
    id                              INTEGER NOT NULL PRIMARY KEY,
    ref_column_id                   INTEGER NOT NULL REFERENCES columns(id),
    ref_column_file_id              INTEGER NOT NULL REFERENCES files(id),
    ref_column_qualified_name       TEXT NOT NULL,
    source_column_id                INTEGER REFERENCES columns(id),
    source_file_id                  INTEGER NOT NULL REFERENCES files(id),
    source_column_qualified_name    TEXT NULL,
    source_line                     INTEGER NOT NULL,
    source_column                   INTEGER NOT NULL,
    ref_kind                        TEXT NOT NULL,
    context                         TEXT NOT NULL
);
