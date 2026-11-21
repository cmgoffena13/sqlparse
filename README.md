<p align="center">
  <img alt="SQLParse" src="static/logo.svg" width="560">
</p>

<p align="center">
  <img alt="Lines of Code" src="https://aschey.tech/tokei/github/cmgoffena13/sqlparse?category=code">
  <a href="https://github.com/cmgoffena13/sqlparse/actions"><img alt="Build Status" src="https://github.com/cmgoffena13/sqlparse/actions/workflows/build-release.yml/badge.svg"></a>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-informational?style=flat">
</p>

SQLParse is a SQLMesh project indexer that gives agents fast, accurate, and compact context while reducing token usage. It parses your SQLMesh project and stores those relationships in a local SQLite database.

## Install MCP Server and Skill

1. Put the `sqlparse` binary on your PATH (release asset or `make compile` → `dist/sqlparse`).
2. `sqlparse install`

## Tools

| Tool | Description |
| --- | --- |
| `list_schemas` | Return every schema name. |
| `list_models` | Return the model names in one schema. |
| `get_directory_tree` | Return the project's directory/file tree with line counts. |
| `search` | Full-text search model, query, and column names. |
| `get_model` | Return a model's SQL tree, macro refs, and audit refs. |
| `get_query` | Return a query's output schema and definition. |
| `get_span_at_lines` | Return the query, audit, macro, or test that covers a line range. |
| `get_test` | Return a test definition. |
| `get_macro` | Return a macro's definition and the models that use it. |
| `get_audit` | Return an audit's definition and the models that use it. |
| `get_model_relations` | Return dependents or dependencies for one model. |
| `get_column_relations` | Return dependents or dependencies for one column. |

## Resources

| Resource | Description |
| --- | --- |
| `skill://sqlparse/SKILL.md` | Guided exploration skill for navigating SQLMesh projects. |
| `stats://sqlparse/sessions` | Per-session markdown table of files with tool calls and a tokens-saved range. |

## Commands

| Command | Description |
| --- | --- |
| `install` | Register the MCP server in installed clients and write the skill. |
| `uninstall` | Remove the sqlparse MCP server, skill, and indexes. |
| `cleanup` | Remove indexes whose workspace directories no longer exist. |
| `update` | Replace the binary with the latest release (`--version` optional) and update the skill. |
| `mcp` | Start the MCP server. |
| `reload` | Drop the index and reprocess the SQLMesh project. |
