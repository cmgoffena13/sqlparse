from typing import Literal

from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import tree_glyphs

_MAX_NODES = 100

_MODEL_TESTS_SQL = """
SELECT
    models.qualified_name,
    files.path AS file_path,
    tests.name AS test_name,
    tests.line_start,
    tests.line_end
FROM tests
INNER JOIN files
    ON files.id = tests.file_id
INNER JOIN models
    ON models.id = tests.model_id
ORDER BY models.qualified_name, file_path, tests.line_start, test_name
"""

_EDGES_SQL = """
SELECT DISTINCT
    ref_models.qualified_name AS dependent_name,
    source_models.qualified_name AS dependency_name
FROM column_lineage AS lineage
INNER JOIN models AS ref_models
    ON ref_models.id = lineage.ref_column_model_id
INNER JOIN models AS source_models
    ON source_models.id = lineage.source_models_id
WHERE lineage.ref_column_model_id != lineage.source_models_id
"""


def _load_graph(
    db: ProjectDB,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    dependencies: dict[str, list[str]] = {}
    dependents: dict[str, list[str]] = {}
    for row in db.connection.execute(_EDGES_SQL):
        dependent_name = str(row["dependent_name"])
        dependency_name = str(row["dependency_name"])
        deps = dependencies.setdefault(dependent_name, [])
        if dependency_name not in deps:
            deps.append(dependency_name)
        kids = dependents.setdefault(dependency_name, [])
        if dependent_name not in kids:
            kids.append(dependent_name)
    for names in dependencies.values():
        names.sort()
    for names in dependents.values():
        names.sort()
    return dependencies, dependents


def _model_kinds(db: ProjectDB) -> dict[str, str]:
    return {
        str(row["qualified_name"]): str(row["kind"])
        for row in db.connection.execute("SELECT qualified_name, kind FROM models")
    }


def _labeled_model(name: str, kinds: dict[str, str], mark_external: bool) -> str:
    label = name
    if mark_external and kinds.get(name) == "EXTERNAL":
        label = f"{name} (EXTERNAL)"
    return label


def _relation_lines(
    children: dict[str, list[str]],
    parent: str,
    branch_prefix: str,
    *,
    seen: set[str],
    budget: list[int],
    kinds: dict[str, str],
    mark_external: bool,
    nested: bool,
    tests: dict[str, dict[str, list[str]]],
) -> list[str]:
    lines: list[str] = []
    files = list(tests.get(parent, {}).items()) if nested else []
    siblings = [child for child in children.get(parent, ()) if child not in seen]
    last_index = len(files) + len(siblings) - 1
    index = 0
    for file_path, names in files:
        prefix, continuation = tree_glyphs(index == last_index, wide=True)
        lines.append(f"{branch_prefix}{prefix}{file_path}")
        lines.extend(f"{branch_prefix}{continuation}• {name}" for name in names)
        index += 1
    for child in siblings:
        if budget[0] < 0:
            break
        if budget[0] == 0:
            lines.append(f"{branch_prefix}...[truncated]")
            budget[0] = -1
            break
        budget[0] -= 1
        seen.add(child)
        label = _labeled_model(child, kinds, mark_external)
        prefix = ""
        continuation = ""
        if nested:
            prefix, continuation = tree_glyphs(index == last_index, wide=True)
        elif lines:
            lines.append("")
        lines.append(f"{branch_prefix}{prefix}{label}")
        lines.extend(
            _relation_lines(
                children,
                child,
                branch_prefix + continuation,
                seen=seen,
                budget=budget,
                kinds=kinds,
                mark_external=mark_external,
                nested=True,
                tests=tests,
            )
        )
        seen.remove(child)
        index += 1
    return lines


def _model_tests(db: ProjectDB) -> dict[str, dict[str, list[str]]]:
    tests: dict[str, dict[str, list[str]]] = {}
    for row in db.connection.execute(_MODEL_TESTS_SQL):
        files = tests.setdefault(str(row["qualified_name"]), {})
        item = str(row["test_name"])
        files.setdefault(str(row["file_path"]), []).append(item)
    return tests


def get_model_relations(
    db: ProjectDB,
    model_name: str,
    relation: Literal["dependents", "dependencies"],
    include_tests: bool = False,
) -> str:
    key = model_name.strip()
    result = "No model name given; pass a non-empty model name."
    if key:
        exists = db.connection.execute(
            "SELECT 1 AS ok FROM models WHERE qualified_name = ?",
            (key,),
        ).fetchone()
        if exists is None:
            result = "No model found."
        else:
            dependencies, dependents = _load_graph(db)
            children = dependents if relation == "dependents" else dependencies
            kinds = _model_kinds(db)
            mark_external = relation == "dependencies"
            tests = _model_tests(db) if include_tests and relation == "dependents" else {}
            budget = [_MAX_NODES]
            lines = _relation_lines(
                children,
                key,
                "",
                seen={key},
                budget=budget,
                kinds=kinds,
                mark_external=mark_external,
                nested=False,
                tests=tests,
            )
            result = "No relations."
            if lines:
                result = "\n".join(lines) + "\n"
    return result
