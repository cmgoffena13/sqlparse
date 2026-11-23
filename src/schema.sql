PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS index_root (
    id      INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    path    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id                  INTEGER NOT NULL PRIMARY KEY,
    name                TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS projects_name_index ON projects (name);

CREATE TABLE IF NOT EXISTS project_gateways (
    id                  INTEGER NOT NULL PRIMARY KEY,
    project_id          INTEGER NOT NULL REFERENCES projects(id),
    name                TEXT NOT NULL,
    catalog_name        TEXT NULL,
    dialect             TEXT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS project_gateways_project_id_name_index
    ON project_gateways (project_id, name);

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
    gateway_id          INTEGER NOT NULL REFERENCES project_gateways(id),
    dialect             TEXT NOT NULL,
    schema_name         TEXT NOT NULL,
    qualified_name      TEXT NOT NULL,
    kind                TEXT NOT NULL,
    time_column         TEXT NULL,
    grain               TEXT NULL,
    config_start_line   INTEGER NOT NULL,
    config_end_line     INTEGER NOT NULL,
    description         TEXT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS models_qualified_name_index ON models (qualified_name);

CREATE TABLE IF NOT EXISTS macros (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS macros_name_index ON macros (file_id, name);

CREATE TABLE IF NOT EXISTS model_macros (
    macro_name          TEXT NOT NULL REFERENCES macros(name),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    PRIMARY KEY (macro_name, model_id)
);
CREATE INDEX IF NOT EXISTS model_macros_model_id_index ON model_macros (model_id, macro_name);

CREATE TABLE IF NOT EXISTS audits (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    name                TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS audits_name_index ON audits (file_id, name);

CREATE TABLE IF NOT EXISTS model_audits (
    audit_name          TEXT NOT NULL REFERENCES audits(name),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    PRIMARY KEY (audit_name, model_id)
);
CREATE INDEX IF NOT EXISTS model_audits_model_id_index ON model_audits (model_id, audit_name);

CREATE TABLE IF NOT EXISTS queries (
    id                  INTEGER NOT NULL PRIMARY KEY,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    name                TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    depth               INTEGER NOT NULL,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    snapshot_hash       TEXT NOT NULL,
    select_col_count    INTEGER NOT NULL,
    select_expr_count   INTEGER NULL,
    select_alias_count  INTEGER NULL,
    where_condition_count INTEGER NULL,
    join_statement_count          INTEGER NULL,
    group_by_col_count  INTEGER NULL,
    having_condition_count INTEGER NULL,
    order_by_col_count INTEGER NULL,
    rendered_sql        TEXT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS queries_model_id_name_index ON queries (model_id, name);

CREATE TABLE IF NOT EXISTS columns (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    query_id            INTEGER NOT NULL REFERENCES queries(id),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    from_table          TEXT NULL,
    name                TEXT NOT NULL,
    column_name         TEXT NOT NULL,
    qualified_name      TEXT NOT NULL,
    data_type           TEXT NOT NULL,
    nullable            BOOLEAN NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    context             TEXT NOT NULL,
    description         TEXT NULL,
    is_select           BOOLEAN NOT NULL,
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
    ref_line                        INTEGER NOT NULL,
    ref_kind                        TEXT NOT NULL,
    ref_context                     TEXT NOT NULL,
    snapshot_hash                   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS column_lineage_ref_column_id_index
    ON column_lineage (ref_column_id);
CREATE INDEX IF NOT EXISTS column_lineage_source_column_id_index
    ON column_lineage (source_column_id);
CREATE INDEX IF NOT EXISTS column_lineage_ref_column_model_id_source_models_id_index
    ON column_lineage (ref_column_model_id, source_models_id);

CREATE TABLE IF NOT EXISTS tests (
    id                  INTEGER NOT NULL PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES files(id),
    model_id            INTEGER NOT NULL REFERENCES models(id),
    name                TEXT NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS tests_file_id_name_index ON tests (file_id, name);
CREATE INDEX IF NOT EXISTS tests_model_id_index ON tests (model_id);

CREATE TABLE IF NOT EXISTS test_references (
    test_id             INTEGER NOT NULL REFERENCES tests(id),
    column_id           INTEGER NOT NULL REFERENCES columns(id),
    PRIMARY KEY (test_id, column_id)
);
CREATE INDEX IF NOT EXISTS test_references_column_id_index ON test_references (column_id, test_id);

CREATE TABLE IF NOT EXISTS search_docs (
    id                  INTEGER NOT NULL PRIMARY KEY,
    model_name          TEXT NOT NULL,
    model_kind          TEXT NOT NULL,
    query_name          TEXT NOT NULL,
    column_name         TEXT NOT NULL,
    snapshot_hash       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS search_docs_names_index
    ON search_docs (model_name, query_name, column_name);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    model_name,
    model_kind,
    query_name,
    column_name
);

CREATE TABLE IF NOT EXISTS session_stats (
    id                  INTEGER NOT NULL PRIMARY KEY,
    session_id          TEXT NOT NULL,
    session_start_time  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS session_stats_session_id_index ON session_stats (session_id);

CREATE TABLE IF NOT EXISTS session_stats_files (
    id                      INTEGER NOT NULL PRIMARY KEY,
    session_id              INTEGER NOT NULL REFERENCES session_stats(id),
    file_id                 INTEGER NOT NULL REFERENCES files(id),
    current_file_tokens     INTEGER NOT NULL,
    tool_call_count         INTEGER NOT NULL,
    output_tokens           INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS session_stats_files_session_id_file_id_index
    ON session_stats_files (session_id, file_id);

CREATE TABLE IF NOT EXISTS session_stats_tool_outputs (
    id                          INTEGER NOT NULL PRIMARY KEY,
    session_file_id             INTEGER NOT NULL REFERENCES session_stats_files(id),
    tool                        TEXT NOT NULL,
    tool_symbol_qualified_name  TEXT,
    output_tokens               INTEGER NOT NULL,
    file_tokens                 INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS session_stats_tool_outputs_session_file_id_index
    ON session_stats_tool_outputs (session_file_id);
