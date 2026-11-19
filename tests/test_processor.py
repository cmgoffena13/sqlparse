import os
import shutil
from pathlib import Path

from src.db import ProjectDB
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT

CUSTOMERS_FQN = '"memory"."sushi"."customers"'
CUSTOMER_ORDERS_FQN = '"memory"."sushi"."customer_orders"'
ORDERS_FQN = '"memory"."sushi"."orders"'
WAITERS_FQN = '"memory"."sushi"."waiters"'
RAW_SEED_FQN = '"memory"."sushi"."raw_seed"'
RAW_CUSTOMERS_FQN = '"memory"."raw"."customers"'
RAW_ORDERS_FQN = '"memory"."raw"."orders"'


def test_processor_indexes_files_and_directories() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        first_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch("SELECT id, file_id, qualified_name, kind FROM models")
        }
        first_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, query_name, from_table, name, qualified_name, "
                "line_start, line_end, context FROM columns"
            )
        }
        first_macros = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name, kind FROM macros")
        }
        first_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        first_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_kind, context FROM column_lineage"
            )
        }
        ProjectProcessor(db, FIXTURE_PROJECT).process()
        second_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch("SELECT id, file_id, qualified_name, kind FROM models")
        }
        second_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, query_name, from_table, name, qualified_name, "
                "line_start, line_end, context FROM columns"
            )
        }
        second_macros = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name, kind FROM macros")
        }
        second_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        second_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_kind, context FROM column_lineage"
            )
        }
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        config = db.fetch(
            "SELECT directory_id, language, normalized_path FROM files WHERE path = ?",
            ("config.yaml",),
        )[0]
        waiter = db.fetch(
            "SELECT id, language, normalized_path FROM files WHERE path = ?",
            ("models/waiters.py",),
        )[0]
        customer = db.fetch(
            "SELECT id, language, normalized_path FROM files WHERE path = ?",
            ("models/customers.sql",),
        )[0]
        orders = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("models/orders.sql",),
        )[0]
        raw_seed = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("models/raw_seed.sql",),
        )[0]
        external = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("external_models.yaml",),
        )[0]
        file_count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        db.close()
    assert directories == ["audits", "macros", "models", "seeds", "tests"]
    assert config["directory_id"] is None
    assert config["language"] == "yaml"
    assert config["normalized_path"] == "config"
    assert waiter["language"] == "python"
    assert waiter["normalized_path"] == "models.waiters"
    assert customer["language"] == "sql"
    assert customer["normalized_path"] == "models/customers"
    assert file_count == 11
    assert set(first_models) == {
        CUSTOMERS_FQN,
        CUSTOMER_ORDERS_FQN,
        ORDERS_FQN,
        WAITERS_FQN,
        RAW_SEED_FQN,
        RAW_CUSTOMERS_FQN,
        RAW_ORDERS_FQN,
    }
    assert first_models[CUSTOMERS_FQN]["kind"] == "FULL"
    assert first_models[CUSTOMERS_FQN]["file_id"] == customer["id"]
    assert first_models[ORDERS_FQN]["kind"] == "INCREMENTAL_BY_TIME_RANGE"
    assert first_models[ORDERS_FQN]["file_id"] == orders["id"]
    assert first_models[WAITERS_FQN]["kind"] == "FULL"
    assert first_models[WAITERS_FQN]["file_id"] == waiter["id"]
    assert first_models[RAW_SEED_FQN]["kind"] == "SEED"
    assert first_models[RAW_SEED_FQN]["file_id"] == raw_seed["id"]
    assert first_models[RAW_CUSTOMERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_CUSTOMERS_FQN]["file_id"] == external["id"]
    assert first_models[RAW_ORDERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_ORDERS_FQN]["file_id"] == external["id"]
    assert second_models == first_models
    assert first_columns["sushi.customers.customer_id"]["query_name"] == "sushi.customers"
    assert first_columns["sushi.customers.customer_id"]["name"] == "customer_id"
    assert (
        first_columns["sushi.customers.customer_id"]["model_id"]
        == first_models[CUSTOMERS_FQN]["id"]
    )
    assert first_columns["sushi.customers.cte.raw.customers.customer_id"]["query_name"] == (
        "sushi.customers.cte"
    )
    assert (
        first_columns["sushi.customers.cte.raw.customers.customer_id"]["from_table"]
        == "raw.customers"
    )
    assert first_columns["sushi.customers.cte.raw.orders.customer_id"]["from_table"] == (
        "raw.orders"
    )
    assert first_columns["sushi.customers.cte.raw.customers.status"]["name"] == "status"
    assert first_columns["sushi.customers.customer_id"]["from_table"] is None
    assert first_columns["sushi.customers.customer_id"]["line_start"] == 12
    assert first_columns["sushi.customers.customer_id"]["line_end"] == 12
    assert first_columns["sushi.customers.amount"]["line_start"] == 14
    assert first_columns["sushi.customers.amount"]["line_end"] == 15
    assert first_columns["sushi.customers.status"]["line_start"] == 16
    assert first_columns["sushi.customers.status"]["line_end"] == 16
    assert first_columns["sushi.customers.cte.raw.customers.customer_id"]["line_start"] == 3
    assert first_columns["sushi.customers.cte.raw.customers.customer_id"]["line_end"] == 3
    assert first_columns["sushi.customers.cte.raw.orders.customer_id"]["line_start"] == 4
    assert first_columns["sushi.customers.cte.raw.orders.customer_id"]["line_end"] == 4
    assert first_columns["sushi.customers.cte.raw.customers.status"]["line_start"] == 5
    assert first_columns["sushi.customers.cte.raw.customers.status"]["line_end"] == 5
    assert first_columns["sushi.customers.cte.raw.orders.amount_cents"]["line_start"] == 6
    assert first_columns["sushi.customers.cte.raw.orders.amount_cents"]["line_end"] == 6
    assert first_columns["sushi.customers.cte.raw.orders.amount_cents"]["from_table"] == (
        "raw.orders"
    )
    assert first_columns["raw.customers.customer_id"]["from_table"] is None
    assert first_columns["raw.customers.customer_id"]["query_name"] == "raw.customers"
    assert (
        first_columns["raw.customers.customer_id"]["model_id"]
        == first_models[RAW_CUSTOMERS_FQN]["id"]
    )
    assert second_columns == first_columns
    assert first_macros == {"cents_to_dollars": first_macros["cents_to_dollars"]}
    assert first_macros["cents_to_dollars"]["kind"] == "jinja"
    assert "star" not in first_macros
    assert second_macros == first_macros
    assert first_model_macros == {("cents_to_dollars", first_models[CUSTOMERS_FQN]["id"])}
    assert second_model_macros == first_model_macros
    customer_id_refs = [
        row
        for row in first_references.values()
        if row["ref_column_qualified_name"] == "sushi.customers.customer_id"
    ]
    assert any(
        row["ref_column_query_name"] == "sushi.customers"
        and row["source_query_name"] == "sushi.customers.cte"
        and row["source_column_qualified_name"] == "sushi.customers.cte.raw.customers.customer_id"
        and row["ref_kind"] == "alias"
        for row in customer_id_refs
    )
    amount_refs = [
        row
        for row in first_references.values()
        if row["ref_column_qualified_name"] == "sushi.customers.amount"
    ]
    assert any(
        row["ref_column_query_name"] == "sushi.customers"
        and row["source_query_name"] == "sushi.customers.cte"
        and row["source_column_qualified_name"] == "sushi.customers.cte.raw.orders.amount_cents"
        and row["ref_kind"] == "expression"
        and "/ 100" in str(row["context"])
        for row in amount_refs
    )
    assert any(
        row["ref_column_qualified_name"] == "sushi.customers.cte.raw.orders.amount_cents"
        and row["source_column_qualified_name"] == "raw.orders.amount_cents"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )
    assert any(
        row["ref_column_query_name"] == "sushi.customers.cte"
        and row["ref_column_qualified_name"] == "sushi.customers.cte.raw.customers.customer_id"
        and row["source_query_name"] == "raw.customers"
        and row["source_column_qualified_name"] == "raw.customers.customer_id"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )
    assert any(
        row["ref_column_query_name"] == "sushi.customers.cte"
        and row["ref_column_qualified_name"] == "sushi.customers.cte.raw.orders.customer_id"
        and row["source_query_name"] == "raw.orders"
        and row["source_column_qualified_name"] == "raw.orders.customer_id"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )
    assert second_references == first_references
    assert all(
        row["ref_column_model_id"] == first_models[CUSTOMERS_FQN]["id"]
        for row in first_references.values()
        if str(row["ref_column_qualified_name"]).startswith("sushi.customers.")
    )
    assert all(row["source_column_id"] is not None for row in first_references.values())
    assert all("?" not in str(row["context"]) for row in first_references.values())
    assert all(
        "?" not in str(row["source_column_qualified_name"]) for row in first_references.values()
    )
    assert any(
        row["ref_column_qualified_name"] == "sushi.customer_orders.customer_id"
        and row["source_column_qualified_name"] == "sushi.customers.customer_id"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )
    assert any(
        row["ref_column_qualified_name"] == "sushi.customer_orders.status"
        and row["source_column_qualified_name"] == "sushi.customers.status"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )
    assert any(
        row["ref_column_qualified_name"] == "sushi.customer_orders.order_id"
        and row["source_column_qualified_name"] == "sushi.orders.order_id"
        and row["ref_kind"] == "alias"
        for row in first_references.values()
    )


def test_processor_drops_models_when_their_files_disappear(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        before = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM models")
        }
        before_columns = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM columns")
        }
        before_macros = {str(row["name"]) for row in db.fetch("SELECT name FROM macros")}
        before_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        before_references = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch("SELECT ref_column_qualified_name FROM column_lineage")
        }
        customers_model_id = db.fetch(
            "SELECT id FROM models WHERE qualified_name = ?",
            (CUSTOMERS_FQN,),
        )[0]["id"]
        (root / "models" / "customers.sql").unlink()
        (root / "macros" / "cents_to_dollars.sql").unlink()
        ProjectProcessor(db, root).process()
        after = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM models")
        }
        after_columns = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM columns")
        }
        after_macros = {str(row["name"]) for row in db.fetch("SELECT name FROM macros")}
        after_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        after_references = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch("SELECT ref_column_qualified_name FROM column_lineage")
        }
    finally:
        db.close()
    assert CUSTOMERS_FQN in before
    assert after == {
        CUSTOMER_ORDERS_FQN,
        ORDERS_FQN,
        WAITERS_FQN,
        RAW_SEED_FQN,
        RAW_CUSTOMERS_FQN,
        RAW_ORDERS_FQN,
    }
    assert "sushi.customers.customer_id" in before_columns
    assert "sushi.customers.cte.raw.customers.customer_id" in before_columns
    assert "sushi.customers.cte.raw.orders.customer_id" in before_columns
    assert "sushi.customers.customer_id" not in after_columns
    assert "sushi.customers.cte.raw.customers.customer_id" not in after_columns
    assert "raw.customers.customer_id" in after_columns
    assert "cents_to_dollars" in before_macros
    assert "cents_to_dollars" not in after_macros
    assert ("cents_to_dollars", customers_model_id) in before_model_macros
    assert after_model_macros == set()
    assert "sushi.customers.customer_id" in before_references
    assert "sushi.customers.cte.raw.orders.customer_id" in before_references
    assert "sushi.customers.customer_id" not in after_references
    assert "sushi.customers.cte.raw.orders.customer_id" not in after_references


def test_processor_records_plain_files_and_drops_deleted_ones(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config.yaml").write_text(
        "gateways:\n  local:\n    connection:\n      type: duckdb\n"
        "default_gateway: local\nmodel_defaults:\n  dialect: duckdb\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("hello\n")
    (root / "settings.yml").write_text("enabled: true\n")
    (root / "LICENSE").write_text("mit\n")
    os.mkfifo(root / "pipe")
    blocked = root / "blocked.txt"
    blocked.write_text("secret")
    blocked.chmod(0)
    notes = root / "notes"
    notes.mkdir()
    (notes / "keep.txt").write_text("x")
    hidden = root / ".sqlparse"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("no")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    module = pkg / "worker.py"
    module.write_text("VALUE = 1\n")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def main() -> None:\n    pass\n")
    fundamentals = root / "src" / "fundamentals"
    fundamentals.mkdir()
    (fundamentals / "__init__.py").write_text("")
    (fundamentals / "xxx.py").write_text("def y() -> int:\n    return 1\n")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        paths = {
            str(row["path"]): row["language"]
            for row in db.fetch("SELECT path, language FROM files")
        }
        model_count = db.fetch("SELECT COUNT(*) AS model_count FROM models")[0]["model_count"]
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        lines = db.fetch("SELECT line_count FROM files WHERE path = ?", ("README.md",))[0]
        normalized = {
            str(row["path"]): row["normalized_path"]
            for row in db.fetch("SELECT path, normalized_path FROM files")
        }
        module.write_text("VALUE = 1\nVALUE = 2\n")
        (root / "README.md").unlink()
        (notes / "keep.txt").unlink()
        notes.rmdir()
        ProjectProcessor(db, root).process()
        remaining = {str(row["path"]) for row in db.fetch("SELECT path FROM files")}
        remaining_dirs = {str(row["path"]) for row in db.fetch("SELECT path FROM directories")}
        updated = db.fetch("SELECT line_count FROM files WHERE path = ?", ("pkg/worker.py",))[0]
    finally:
        blocked.chmod(0o644)
        db.close()
    assert directories == ["notes", "pkg", "src", "src/fundamentals"]
    assert paths["README.md"] is None
    assert paths["config.yaml"] == "yaml"
    assert paths["settings.yml"] == "yaml"
    assert paths["LICENSE"] is None
    assert paths["notes/keep.txt"] is None
    assert paths["pkg/worker.py"] == "python"
    assert paths["pkg/__init__.py"] == "python"
    assert model_count == 0
    assert normalized["pkg/worker.py"] == "pkg.worker"
    assert normalized["pkg/__init__.py"] == "pkg"
    assert normalized["src/app.py"] == "src.app"
    assert normalized["src/fundamentals/xxx.py"] == "fundamentals.xxx"
    assert normalized["src/fundamentals/__init__.py"] == "fundamentals"
    assert normalized["notes/keep.txt"] == "notes/keep"
    assert "pipe" not in paths
    assert "blocked.txt" not in paths
    assert ".sqlparse/secret.txt" not in paths
    assert int(lines["line_count"]) == 2
    assert remaining == {
        "LICENSE",
        "config.yaml",
        "pkg/__init__.py",
        "pkg/worker.py",
        "settings.yml",
        "src/app.py",
        "src/fundamentals/__init__.py",
        "src/fundamentals/xxx.py",
    }
    assert remaining_dirs == {"pkg", "src", "src/fundamentals"}
    assert int(updated["line_count"]) == 3
