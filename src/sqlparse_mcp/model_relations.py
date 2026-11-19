from typing import Literal

from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import tree_glyphs

_MAX_NODES = 100

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


def _relation_lines(
    children: dict[str, list[str]],
    parent: str,
    branch_prefix: str,
    *,
    seen: set[str],
    budget: list[int],
) -> list[str]:
    lines: list[str] = []
    siblings = [child for child in children.get(parent, ()) if child not in seen]
    last_index = len(siblings) - 1
    for index, child in enumerate(siblings):
        if budget[0] < 0:
            break
        if budget[0] == 0:
            lines.append(f"{branch_prefix}...[truncated]")
            budget[0] = -1
            break
        budget[0] -= 1
        seen.add(child)
        connector, continuation = tree_glyphs(index == last_index, wide=True)
        lines.append(f"{branch_prefix}{connector}{child}")
        lines.extend(
            _relation_lines(
                children,
                child,
                branch_prefix + continuation,
                seen=seen,
                budget=budget,
            )
        )
    return lines


def get_model_relations(
    db: ProjectDB,
    model_name: str,
    relation: Literal["dependents", "dependencies"],
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
            budget = [_MAX_NODES]
            lines = [key]
            lines.extend(
                _relation_lines(
                    children,
                    key,
                    "",
                    seen={key},
                    budget=budget,
                )
            )
            result = "\n".join(lines) + "\n"
    return result
