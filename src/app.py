import os
import sys
from pathlib import Path

from src.cli.commands import build_arg_parser, make_parser
from src.db import cleanup_orphan_indexes, remove_index_files
from src.git_utils import is_git_controlled
from src.utils import get_sqlparse_config_dir, get_version


def _require_dir(path: Path) -> Path | None:
    resolved = path.resolve()
    if not resolved.is_dir():
        print(f"Not a directory: {resolved}", file=sys.stderr)
        return None
    return resolved


def _require_indexable_root(path: Path) -> Path | None:
    root = _require_dir(path)
    if root is not None and not is_git_controlled(root):
        print(
            f"{root} is not a git repository; are you in a git repository?",
            file=sys.stderr,
        )
        root = None
    return root


def _run_reload(root: Path) -> int:
    from src.db import ProjectDB
    from src.processor import ProjectProcessor

    db = ProjectDB(root, apply_schema=False)
    processor: ProjectProcessor | None = None
    try:
        db.recreate_schema()
        processor = ProjectProcessor(db, root)
        processor.process(full=True)
    finally:
        if processor is not None:
            processor.close()
        db.close()
    return 0


def _run_mcp(root: Path) -> int:
    os.environ["SQLPARSE_WORKSPACE"] = str(root)
    os.chdir(root)
    from src.sqlparse_mcp.server import mcp

    mcp.run(transport="stdio", show_banner=False)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        from src.sqlparse_mcp.skill import sync_skill

        sync_skill()
        return 0
    args = build_arg_parser()
    if args.info:
        cli_path = Path(sys.argv[0]).resolve()
        print(f"Binary path: {cli_path}")
        print(f"Config directory: {get_sqlparse_config_dir()}")
        return 0
    if args.version:
        print(f"sqlparse version: {get_version()}")
        return 0
    if args.command == "reload":
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_reload(root)
    if args.command == "install":
        from src.cli.install_mcp import install_mcp
        from src.sqlparse_mcp.skill import sync_skill

        installed = install_mcp()
        sync_skill()
        if installed is None:
            print("No MCP clients found.")
            return 0
        if not installed:
            return 1
        print("Restart the client (or reload MCP) to pick up the change.")
        return 0
    if args.command == "uninstall":
        from src.cli.install_mcp import uninstall_mcp
        from src.sqlparse_mcp.skill import remove_skill

        ok = uninstall_mcp()
        remove_skill()
        remove_index_files()
        return 0 if ok else 1
    if args.command == "cleanup":
        cleanup_orphan_indexes()
        return 0
    if args.command == "update":
        from src.cli.upgrade import upgrade

        return upgrade(version=args.release_version)
    if args.command == "mcp":
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_mcp(root)

    make_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
