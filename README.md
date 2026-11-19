<p align="center">
  <img alt="SQLParse" src="static/logo.svg" width="560">
</p>

SQLParse is a SQLMesh project indexer that gives agents fast, accurate, and compact context while reducing token usage. It parses your SQLMesh project and stores those relationships in a local SQLite database.

## Commands

| Command | Description |
| --- | --- |
| `install` | Register the MCP server in installed clients and write the skill. |
| `uninstall` | Remove the sqlparse MCP server, skill, and indexes. |
| `cleanup` | Remove indexes whose workspace directories no longer exist. |
| `update` | Replace the binary with the latest release (`--version` optional) and update the skill. |
| `mcp` | Start the MCP server. |
| `reload` | Drop the index and reprocess the SQLMesh project. |
