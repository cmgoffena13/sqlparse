import asyncio
import importlib
import os
import sys
from pathlib import Path

import mcp_types
import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.exceptions import ToolError

from src.parse.parse_utils import is_sqlmesh_project, use_project_venv
from src.sqlparse_mcp.skill import SKILL_INSTRUCTIONS
from tests.conftest import FIXTURE_PROJECT

_TOOLS = {
    "list_catalogs",
    "list_models",
    "list_schemas",
    "search",
    "get_directory_tree",
    "get_model",
    "get_query",
    "get_query_schema",
    "get_span_at_lines",
    "get_test",
    "get_macro",
    "get_audit",
    "get_model_relations",
    "get_column_relations",
}


def _text(result: CallToolResult) -> str:
    assert result.is_error is False
    assert isinstance(result.data, str)
    return result.data


def _resource_text(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> str:
    block = contents[0]
    assert isinstance(block, mcp_types.TextResourceContents)
    return block.text


def test_client_lists_tools_and_reads_the_project(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQLPARSE_WORKSPACE", str(FIXTURE_PROJECT))

    async def run() -> None:
        async with mcp_client:
            tools = await mcp_client.list_tools()
            assert {tool.name for tool in tools} == _TOOLS
            skill = _resource_text(await mcp_client.read_resource("skill://sqlparse/SKILL.md"))
            assert skill == SKILL_INSTRUCTIONS
            root = _resource_text(await mcp_client.read_resource("workspace://sqlparse/root"))
            assert root.strip() == str(FIXTURE_PROJECT.resolve())
            search_out = _text(
                await mcp_client.call_tool("search", {"query": "customers", "limit": 30})
            )
            assert "## Models" in search_out
            assert "sushi.customers" in search_out
            assert "## Columns" in search_out
            tree_out = _text(
                await mcp_client.call_tool("get_directory_tree", {"directory_path": "models"})
            )
            assert tree_out.startswith("models/")
            assert "customers.sql" in tree_out
            assert "sushi.customers" not in tree_out
            relations_out = _text(
                await mcp_client.call_tool(
                    "get_model_relations",
                    {"model_name": "sushi.customers", "relation": "dependents"},
                )
            )
            assert relations_out.startswith("sushi.customer_orders\n")
            assert "sushi.customers\n" not in relations_out
            assert "sushi.customer_orders" in relations_out
            column_out = _text(
                await mcp_client.call_tool(
                    "get_column_relations",
                    {
                        "model_name": "sushi.customers",
                        "column_name": "$cte.customer_id",
                        "relation": "dependencies",
                    },
                )
            )
            assert "sushi.customers" in column_out
            assert "cte" in column_out

    asyncio.run(run())


def test_plain_config_yaml_is_not_a_sqlmesh_project(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("service: api\n", encoding="utf-8")
    assert is_sqlmesh_project(FIXTURE_PROJECT) is True
    assert is_sqlmesh_project(tmp_path) is False


def test_config_py_relative_credential_file_loads_from_other_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    (project / "gcp_service_account.json").write_text("{}", encoding="utf-8")
    (project / "config.py").write_text(
        "from pathlib import Path\n"
        "from sqlmesh.core.config import Config, ModelDefaultsConfig\n"
        "path = Path('gcp_service_account.json')\n"
        "if not path.is_file():\n"
        "    raise FileNotFoundError(f'File {path} was not found')\n"
        "config = Config(model_defaults=ModelDefaultsConfig(dialect='duckdb'))\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(elsewhere)
    assert is_sqlmesh_project(project) is True


def test_config_py_that_reads_dotenv_is_a_sqlmesh_project(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SQLPARSE_FIXTURE_DIALECT=duckdb\n", encoding="utf-8")
    (tmp_path / "config.py").write_text(
        "import os\n"
        "from sqlmesh.core.config import Config, ModelDefaultsConfig\n"
        "config = Config(\n"
        "    model_defaults=ModelDefaultsConfig(dialect=os.environ['SQLPARSE_FIXTURE_DIALECT'])\n"
        ")\n",
        encoding="utf-8",
    )
    os.environ.pop("SQLPARSE_FIXTURE_DIALECT", None)
    try:
        project = is_sqlmesh_project(tmp_path)
    finally:
        os.environ.pop("SQLPARSE_FIXTURE_DIALECT", None)
    assert project is True


def test_config_py_imports_a_package_from_the_project_venv(tmp_path: Path) -> None:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    package = tmp_path / ".venv" / "lib" / version / "site-packages" / "warehouse_secret"
    package.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (package / "__init__.py").write_text("TOKEN = 'duckdb'\n", encoding="utf-8")
    (tmp_path / "config.py").write_text(
        "import warehouse_secret\n"
        "from sqlmesh.core.config import Config, ModelDefaultsConfig\n"
        "config = Config(model_defaults=ModelDefaultsConfig(dialect=warehouse_secret.TOKEN))\n",
        encoding="utf-8",
    )
    before = list(sys.path)
    try:
        project = is_sqlmesh_project(tmp_path)
    finally:
        sys.path[:] = before
        sys.modules.pop("warehouse_secret", None)
    assert project is True


def test_project_venv_fills_missing_imports_only(tmp_path: Path) -> None:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = tmp_path / ".venv" / "lib" / version / "site-packages"
    site_packages.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (site_packages / "path_winner.py").write_text("VALUE = 'venv'\n", encoding="utf-8")
    ours = tmp_path / "ours"
    ours.mkdir()
    (ours / "path_winner.py").write_text("VALUE = 'process'\n", encoding="utf-8")
    before = list(sys.path)
    sys.path.insert(0, str(ours))
    sys.modules.pop("path_winner", None)
    try:
        use_project_venv(tmp_path)
        value = importlib.import_module("path_winner").VALUE
    finally:
        sys.path[:] = before
        sys.modules.pop("path_winner", None)
    assert value == "process"


def test_mcp_skips_the_database_outside_a_sqlmesh_project(
    mcp_client: Client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text("service: api\n", encoding="utf-8")
    monkeypatch.setenv("SQLPARSE_WORKSPACE", str(tmp_path))

    async def run() -> None:
        async with mcp_client:
            await mcp_client.call_tool("search", {"query": "customers"})

    with pytest.raises(ToolError, match="is not a SQLMesh project"):
        asyncio.run(run())
    config_dir = Path(os.environ["SQLPARSE_CONFIG_DIR"])
    assert list(config_dir.glob("indexes/*.db")) == []
