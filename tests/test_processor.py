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
        first_projects = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name FROM projects")
        }
        first_gateways = {
            str(row["name"]): dict(row)
            for row in db.fetch("SELECT id, project_id, name, dialect FROM project_gateways")
        }
        first_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, gateway_id, dialect, qualified_name, kind, "
                "config_start_line, config_end_line, description, snapshot_hash "
                "FROM models"
            )
        }
        first_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, query_name, from_table, name, qualified_name, "
                "data_type, line_start, line_end, context, description, snapshot_hash "
                "FROM columns"
            )
        }
        first_macros = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, kind, line_start, line_end, snapshot_hash FROM macros"
            )
        }
        first_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        first_audits = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, line_start, line_end, snapshot_hash FROM audits"
            )
        }
        first_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        first_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                int(row["ref_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_line, ref_kind, ref_context, snapshot_hash "
                "FROM column_lineage"
            )
        }
        first_tests = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, model_id, name, line_start, line_end, snapshot_hash FROM tests"
            )
        }
        first_test_references = {
            (int(row["test_id"]), str(row["qualified_name"]))
            for row in db.fetch(
                "SELECT tr.test_id, c.qualified_name FROM test_references tr "
                "JOIN columns c ON c.id = tr.column_id"
            )
        }
        ProjectProcessor(db, FIXTURE_PROJECT).process()
        second_projects = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name FROM projects")
        }
        second_gateways = {
            str(row["name"]): dict(row)
            for row in db.fetch("SELECT id, project_id, name, dialect FROM project_gateways")
        }
        second_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, gateway_id, dialect, qualified_name, kind, "
                "config_start_line, config_end_line, description, snapshot_hash "
                "FROM models"
            )
        }
        second_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, query_name, from_table, name, qualified_name, "
                "data_type, line_start, line_end, context, description, snapshot_hash "
                "FROM columns"
            )
        }
        second_macros = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, kind, line_start, line_end, snapshot_hash FROM macros"
            )
        }
        second_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        second_audits = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, line_start, line_end, snapshot_hash FROM audits"
            )
        }
        second_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        second_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                int(row["ref_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_line, ref_kind, ref_context, snapshot_hash "
                "FROM column_lineage"
            )
        }
        second_tests = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, model_id, name, line_start, line_end, snapshot_hash FROM tests"
            )
        }
        second_test_references = {
            (int(row["test_id"]), str(row["qualified_name"]))
            for row in db.fetch(
                "SELECT tr.test_id, c.qualified_name FROM test_references tr "
                "JOIN columns c ON c.id = tr.column_id"
            )
        }
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        config = db.fetch(
            "SELECT directory_id, language, normalized_path, is_test FROM files WHERE path = ?",
            ("config.yaml",),
        )[0]
        waiter = db.fetch(
            "SELECT id, language, normalized_path, is_test FROM files WHERE path = ?",
            ("models/waiters.py",),
        )[0]
        customer = db.fetch(
            "SELECT id, language, normalized_path, is_test FROM files WHERE path = ?",
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
            "SELECT id, is_test FROM files WHERE path = ?",
            ("external_models.yaml",),
        )[0]
        test_orders = db.fetch(
            "SELECT id, is_test FROM files WHERE path = ?",
            ("tests/test_orders.yaml",),
        )[0]
        jinja_macro_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("macros/cents_to_dollars.sql",),
        )[0]
        python_macro_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("macros/identity.py",),
        )[0]
        audit_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("audits/not_null_customer_id.sql",),
        )[0]
        file_count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        db.close()
    assert directories == ["audits", "macros", "models", "seeds", "tests"]
    assert config["directory_id"] is None
    assert config["language"] == "yaml"
    assert config["normalized_path"] == "config"
    assert config["is_test"] == 0
    assert waiter["language"] == "python"
    assert waiter["normalized_path"] == "models.waiters"
    assert waiter["is_test"] == 0
    assert customer["language"] == "sql"
    assert customer["normalized_path"] == "models/customers"
    assert customer["is_test"] == 0
    assert external["is_test"] == 0
    assert test_orders["is_test"] == 1
    assert file_count == 12
    assert set(first_projects) == {"sushi"}
    assert set(first_gateways) == {"local"}
    assert first_gateways["local"]["project_id"] == first_projects["sushi"]["id"]
    assert first_gateways["local"]["dialect"] is None
    assert second_projects == first_projects
    assert second_gateways == first_gateways
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
    assert first_models[CUSTOMERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[CUSTOMERS_FQN]["dialect"] == "duckdb"
    assert first_models[CUSTOMERS_FQN]["config_start_line"] == 1
    assert first_models[CUSTOMERS_FQN]["config_end_line"] == 6
    assert first_models[CUSTOMERS_FQN]["description"] == "Customer grain with order amounts"
    assert first_models[CUSTOMERS_FQN]["snapshot_hash"]
    assert first_models[ORDERS_FQN]["kind"] == "INCREMENTAL_BY_TIME_RANGE"
    assert first_models[ORDERS_FQN]["description"] is None
    assert first_models[ORDERS_FQN]["file_id"] == orders["id"]
    assert first_models[ORDERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[ORDERS_FQN]["dialect"] == "duckdb"
    assert first_models[ORDERS_FQN]["config_start_line"] == 1
    assert first_models[ORDERS_FQN]["config_end_line"] == 7
    assert first_models[WAITERS_FQN]["kind"] == "FULL"
    assert first_models[WAITERS_FQN]["file_id"] == waiter["id"]
    assert first_models[WAITERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[WAITERS_FQN]["dialect"] == "duckdb"
    assert first_models[WAITERS_FQN]["config_start_line"] == 4
    assert first_models[WAITERS_FQN]["config_end_line"] == 10
    assert first_models[RAW_SEED_FQN]["kind"] == "SEED"
    assert first_models[RAW_SEED_FQN]["file_id"] == raw_seed["id"]
    assert first_models[RAW_SEED_FQN]["config_start_line"] == 1
    assert first_models[RAW_SEED_FQN]["config_end_line"] == 6
    assert first_models[RAW_CUSTOMERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_CUSTOMERS_FQN]["file_id"] == external["id"]
    assert first_models[RAW_CUSTOMERS_FQN]["config_start_line"] == 1
    assert first_models[RAW_CUSTOMERS_FQN]["config_end_line"] == 4
    assert first_models[RAW_ORDERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_ORDERS_FQN]["file_id"] == external["id"]
    assert first_models[RAW_ORDERS_FQN]["config_start_line"] == 5
    assert first_models[RAW_ORDERS_FQN]["config_end_line"] == 9
    assert first_models[CUSTOMER_ORDERS_FQN]["config_start_line"] == 1
    assert first_models[CUSTOMER_ORDERS_FQN]["config_end_line"] == 4
    assert all(
        row["gateway_id"] == first_gateways["local"]["id"] and row["dialect"] == "duckdb"
        for row in first_models.values()
    )
    assert second_models == first_models
    assert first_columns["sushi.customers.customer_id"]["query_name"] == "sushi.customers"
    assert first_columns["sushi.customers.customer_id"]["name"] == "customer_id"
    assert first_columns["sushi.customers.customer_id"]["description"] == "Customer identifier"
    assert first_columns["sushi.customers.customer_id"]["data_type"] == "INT"
    assert first_columns["sushi.customers.customer_id"]["snapshot_hash"]
    assert first_columns["sushi.customers.amount"]["description"] == "Order amount in dollars"
    assert first_columns["sushi.customers.amount"]["data_type"] == "DOUBLE"
    assert first_columns["sushi.customers.status"]["description"] == "Customer status"
    assert first_columns["sushi.customers.status"]["data_type"] == "TEXT"
    assert first_columns["sushi.customers.cte.raw.customers.customer_id"]["description"] is None
    assert first_columns["sushi.customers.cte.raw.customers.customer_id"]["data_type"] == "INT"
    assert first_columns["sushi.customers.cte.raw.orders.amount_cents"]["data_type"] == "INT"
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
    assert set(first_macros) == {"cents_to_dollars", "identity"}
    assert first_macros["cents_to_dollars"]["kind"] == "jinja"
    assert first_macros["cents_to_dollars"]["file_id"] == jinja_macro_file["id"]
    assert first_macros["cents_to_dollars"]["line_start"] == 1
    assert first_macros["cents_to_dollars"]["line_end"] == 3
    assert first_macros["cents_to_dollars"]["snapshot_hash"]
    assert first_macros["identity"]["kind"] == "python"
    assert first_macros["identity"]["file_id"] == python_macro_file["id"]
    assert first_macros["identity"]["line_start"] == 4
    assert first_macros["identity"]["line_end"] == 6
    assert first_macros["identity"]["snapshot_hash"]
    assert "star" not in first_macros
    assert second_macros == first_macros
    assert first_model_macros == {("cents_to_dollars", first_models[CUSTOMERS_FQN]["id"])}
    assert second_model_macros == first_model_macros
    assert set(first_audits) == {"not_null_customer_id"}
    assert first_audits["not_null_customer_id"]["file_id"] == audit_file["id"]
    assert first_audits["not_null_customer_id"]["line_start"] == 1
    assert first_audits["not_null_customer_id"]["line_end"] == 7
    assert first_audits["not_null_customer_id"]["snapshot_hash"]
    assert second_audits == first_audits
    assert first_model_audits == {("not_null_customer_id", first_models[CUSTOMERS_FQN]["id"])}
    assert second_model_audits == first_model_audits
    assert set(first_tests) == {"test_orders_exist"}
    assert first_tests["test_orders_exist"]["file_id"] == test_orders["id"]
    assert first_tests["test_orders_exist"]["model_id"] == first_models[ORDERS_FQN]["id"]
    assert first_tests["test_orders_exist"]["line_start"] == 1
    assert first_tests["test_orders_exist"]["line_end"] == 12
    assert first_tests["test_orders_exist"]["snapshot_hash"]
    assert second_tests == first_tests
    test_orders_id = first_tests["test_orders_exist"]["id"]
    assert first_test_references == {
        (test_orders_id, "sushi.customers.customer_id"),
        (test_orders_id, "sushi.customers.status"),
        (test_orders_id, "sushi.orders.order_id"),
        (test_orders_id, "sushi.orders.customer_id"),
    }
    assert second_test_references == first_test_references
    customer_id_ref = first_references[
        (
            "sushi.customers.customer_id",
            "sushi.customers.cte.raw.customers.customer_id",
            3,
            12,
            "alias",
        )
    ]
    assert customer_id_ref["ref_column_query_name"] == "sushi.customers"
    assert customer_id_ref["source_query_name"] == "sushi.customers.cte"
    amount_ref = first_references[
        (
            "sushi.customers.amount",
            "sushi.customers.cte.raw.orders.amount_cents",
            6,
            15,
            "expression",
        )
    ]
    assert amount_ref["ref_column_query_name"] == "sushi.customers"
    assert amount_ref["source_query_name"] == "sushi.customers.cte"
    assert "/ 100" in str(amount_ref["ref_context"])
    cte_amount_ref = first_references[
        (
            "sushi.customers.cte.raw.orders.amount_cents",
            "raw.orders.amount_cents",
            6,
            6,
            "alias",
        )
    ]
    assert cte_amount_ref["ref_column_query_name"] == "sushi.customers.cte"
    assert cte_amount_ref["source_query_name"] == "raw.orders"
    cte_customer_ref = first_references[
        (
            "sushi.customers.cte.raw.customers.customer_id",
            "raw.customers.customer_id",
            3,
            3,
            "alias",
        )
    ]
    assert cte_customer_ref["ref_column_query_name"] == "sushi.customers.cte"
    assert cte_customer_ref["source_query_name"] == "raw.customers"
    cte_orders_customer_ref = first_references[
        (
            "sushi.customers.cte.raw.orders.customer_id",
            "raw.orders.customer_id",
            4,
            4,
            "alias",
        )
    ]
    assert cte_orders_customer_ref["ref_column_query_name"] == "sushi.customers.cte"
    assert cte_orders_customer_ref["source_query_name"] == "raw.orders"
    assert second_references == first_references
    assert all(
        row["ref_column_model_id"] == first_models[CUSTOMERS_FQN]["id"]
        for row in first_references.values()
        if str(row["ref_column_qualified_name"]).startswith("sushi.customers.")
    )
    assert all(row["source_column_id"] is not None for row in first_references.values())
    assert all("?" not in str(row["ref_context"]) for row in first_references.values())
    assert all(
        "?" not in str(row["source_column_qualified_name"]) for row in first_references.values()
    )
    customer_orders_customer_ref = first_references[
        (
            "sushi.customer_orders.customer_id",
            "sushi.customers.customer_id",
            10,
            7,
            "alias",
        )
    ]
    assert customer_orders_customer_ref["ref_column_query_name"] == "sushi.customer_orders"
    customer_orders_status_ref = first_references[
        (
            "sushi.customer_orders.status",
            "sushi.customers.status",
            10,
            8,
            "alias",
        )
    ]
    assert customer_orders_status_ref["ref_column_query_name"] == "sushi.customer_orders"
    customer_orders_order_ref = first_references[
        (
            "sushi.customer_orders.order_id",
            "sushi.orders.order_id",
            11,
            9,
            "alias",
        )
    ]
    assert customer_orders_order_ref["ref_column_query_name"] == "sushi.customer_orders"
    assert (
        first_columns["sushi.customer_orders.join.sushi.customers.customer_id"]["query_name"]
        == "sushi.customer_orders.join"
    )
    assert (
        first_columns["sushi.customer_orders.join.sushi.customers.customer_id"]["from_table"]
        == "sushi.customers"
    )
    assert (
        first_columns["sushi.customer_orders.where.sushi.customers.status"]["query_name"]
        == "sushi.customer_orders.where"
    )
    assert (
        first_columns["sushi.customer_orders.group.sushi.orders.order_id"]["from_table"]
        == "sushi.orders"
    )
    join_customers_ref = first_references[
        (
            "sushi.customer_orders.join.sushi.customers.customer_id",
            "sushi.customers.customer_id",
            12,
            12,
            "join",
        )
    ]
    assert join_customers_ref["ref_column_query_name"] == "sushi.customer_orders.join"
    join_orders_ref = first_references[
        (
            "sushi.customer_orders.join.sushi.orders.customer_id",
            "sushi.orders.customer_id",
            12,
            12,
            "join",
        )
    ]
    assert join_orders_ref["ref_column_query_name"] == "sushi.customer_orders.join"
    where_status_ref = first_references[
        (
            "sushi.customer_orders.where.sushi.customers.status",
            "sushi.customers.status",
            13,
            13,
            "where",
        )
    ]
    assert where_status_ref["ref_column_query_name"] == "sushi.customer_orders.where"
    group_customer_ref = first_references[
        (
            "sushi.customer_orders.group.sushi.customers.customer_id",
            "sushi.customers.customer_id",
            15,
            15,
            "group",
        )
    ]
    assert group_customer_ref["ref_column_query_name"] == "sushi.customer_orders.group"
    orders_join_ref = first_references[
        (
            "sushi.orders.join.sushi.customers.customer_id",
            "sushi.customers.customer_id",
            14,
            14,
            "join",
        )
    ]
    assert orders_join_ref["ref_column_query_name"] == "sushi.orders.join"
    cte_join_customers_ref = first_references[
        (
            "sushi.customers.cte.join.raw.customers.customer_id",
            "raw.customers.customer_id",
            9,
            9,
            "join",
        )
    ]
    assert cte_join_customers_ref["ref_column_query_name"] == "sushi.customers.cte.join"
    cte_join_orders_ref = first_references[
        (
            "sushi.customers.cte.join.raw.orders.customer_id",
            "raw.orders.customer_id",
            9,
            9,
            "join",
        )
    ]
    assert cte_join_orders_ref["ref_column_query_name"] == "sushi.customers.cte.join"


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
        before_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
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
        after_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
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
    assert ("not_null_customer_id", customers_model_id) in before_model_audits
    assert after_model_audits == set()
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
