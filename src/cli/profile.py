import sys
import time
from collections.abc import Callable
from pathlib import Path

from src.utils import get_version, is_compiled


def _wrap_accumulate(
    target: object,
    name: str,
    label: str,
    totals: dict[str, float],
    counts: dict[str, int],
) -> tuple[object, str, Callable[..., object]]:
    original: Callable[..., object] = getattr(target, name)

    def wrapped(*args: object, **kwargs: object) -> object:
        started = time.perf_counter()
        result = original(*args, **kwargs)
        totals[label] = totals.get(label, 0.0) + (time.perf_counter() - started)
        counts[label] = counts.get(label, 0) + 1
        return result

    setattr(target, name, wrapped)
    return target, name, original


def format_profile_report(
    root: Path,
    wall_s: float,
    totals: dict[str, float],
    counts: dict[str, int],
) -> str:
    lines = [
        f"sqlparse profile  version={get_version()}  compiled={is_compiled()}",
        f"Root: {root}",
        f"Wall time: {wall_s * 1000:.1f}ms",
        "",
        f"{'phase':<40} {'calls':>7} {'ms':>10} {'%wall':>7}",
        "-" * 68,
    ]
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    for label, seconds in ranked:
        pct = (seconds / wall_s * 100.0) if wall_s > 0 else 0.0
        lines.append(f"{label:<40} {counts.get(label, 0):>7} {seconds * 1000:>10.1f} {pct:>6.1f}%")
    lines.append("")
    lines.append("Phase times are inclusive of nested work; child phases can sum above a parent.")
    lines.append("")
    return "\n".join(lines)


def run_profile(root: Path, out: Path | None) -> int:
    from src.db import ProjectDB
    from src.parse import sqlmesh_parser
    from src.processor import ProjectProcessor

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    restores = [
        _wrap_accumulate(ProjectDB, "recreate_schema", "db.recreate_schema", totals, counts),
        _wrap_accumulate(ProjectDB, "bulk_insert", "db.bulk_insert", totals, counts),
        _wrap_accumulate(ProjectProcessor, "__init__", "ProjectProcessor.__init__", totals, counts),
        _wrap_accumulate(ProjectProcessor, "process", "ProjectProcessor.process", totals, counts),
        _wrap_accumulate(sqlmesh_parser.SQLMeshParser, "sync", "parser.sync", totals, counts),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_extract_models",
            "parser._extract_models",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_projects",
            "parser._sync_projects",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_macros",
            "parser._sync_macros",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_audits",
            "parser._sync_audits",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_model",
            "parser._sync_model",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_queries",
            "parser._sync_queries",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_columns",
            "parser._sync_columns",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_model_macros",
            "parser._sync_model_macros",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_column_lineage",
            "parser._sync_column_lineage",
            totals,
            counts,
        ),
        _wrap_accumulate(
            sqlmesh_parser.SQLMeshParser,
            "_sync_tests",
            "parser._sync_tests",
            totals,
            counts,
        ),
        _wrap_accumulate(sqlmesh_parser.SQLMeshParser, "_flush", "parser._flush", totals, counts),
        _wrap_accumulate(
            sqlmesh_parser,
            "extract_model_bundle",
            "column_lineage.extract_model_bundle",
            totals,
            counts,
        ),
    ]

    db = ProjectDB(root, apply_schema=False)
    processor: ProjectProcessor | None = None
    wall_s = 0.0
    try:
        started = time.perf_counter()
        db.recreate_schema()
        processor = ProjectProcessor(db, root)
        processor.process(full=True)
        wall_s = time.perf_counter() - started
    finally:
        if processor is not None:
            processor.close()
        db.close()
        for target, name, original in restores:
            setattr(target, name, original)

    report = format_profile_report(root, wall_s, totals, counts)
    print(f"\n{report}", end="")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Wrote report: {out}", file=sys.stderr)
    return 0
