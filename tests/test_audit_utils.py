from sqlmesh.core.context import Context

from src.parse.audit_utils import not_null_column_names, unique_values_column_names
from tests.conftest import FIXTURE_PROJECT


def test_not_null_column_names_from_custom_audit_query() -> None:
    context = Context(paths=FIXTURE_PROJECT, load=False)
    context.load(update_schemas=True)
    model = context.get_model("sushi.customers")
    assert model is not None
    names = not_null_column_names(model, context._audits)
    assert names == {"customer_id"}


def test_unique_values_column_names_from_builtin_audit() -> None:
    context = Context(paths=FIXTURE_PROJECT, load=False)
    context.load(update_schemas=True)
    model = context.get_model("sushi.customers")
    assert model is not None
    names = unique_values_column_names(model)
    assert names == {"customer_id"}
