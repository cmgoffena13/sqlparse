from src.db import ProjectDB
from src.parse.sqlmesh_utils import install_parse_only_engine_support, normalized_model_name
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model import get_model
from src.sqlparse_mcp.model_relations import get_model_relations
from src.sqlparse_mcp.model_utils import model_not_found_message
from tests.test_model_utils import QUOTED_EXTERNAL_FIXTURE

PUBLICATIONS = normalized_model_name("beehiiv.publications", "fake-gcp-project-123456", "bigquery")
DEMO_X = normalized_model_name("demo.x", "fake-gcp-project-123456", "bigquery")


def test_quoted_external_lineage_and_short_name_lookup() -> None:
    install_parse_only_engine_support()
    db = ProjectDB(QUOTED_EXTERNAL_FIXTURE)
    try:
        ProjectProcessor(db, QUOTED_EXTERNAL_FIXTURE).process(full=True)
        names = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM models")
        }
        assert PUBLICATIONS in names
        assert DEMO_X in names
        edges = {
            (str(row["dependent_name"]), str(row["dependency_name"]))
            for row in db.fetch(
                """
                SELECT
                    ref_models.qualified_name AS dependent_name,
                    source_models.qualified_name AS dependency_name
                FROM column_lineage AS lineage
                INNER JOIN models AS ref_models
                    ON ref_models.id = lineage.ref_column_model_id
                INNER JOIN models AS source_models
                    ON source_models.id = lineage.source_models_id
                """
            )
        }
        assert (DEMO_X, PUBLICATIONS) in edges
        assert "Kind: EXTERNAL" in get_model(db, "beehiiv.publications")
        assert "external_models.yaml" in get_model(db, "beehiiv.publications")
        dependents = get_model_relations(db, "beehiiv.publications", "dependents")
        assert DEMO_X in dependents
        assert get_model(db, "missing.table") == model_not_found_message()
    finally:
        db.close()
