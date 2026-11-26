import argparse
from pathlib import Path

_HELP_BANNER = """\
 ____   ___  _     ____                     
/ ___| / _ \\| |   |  _ \\ __ _ _ __ ___  ___ 
\\___ \\| | | | |   | |_) / _` | '__/ __|/ _ \\
 ___) | |_| | |___|  __/ (_| | |  \\__ \\  __/
|____/ \\__\\_\\_____|_|   \\__,_|_|  |___/\\___|
""".replace("`", "'")


def help_banner() -> str:
    return _HELP_BANNER


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqlparse",
        description=help_banner(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the version and exit",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show config info and exit",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "install",
        help="Register sqlparse in installed MCP clients and write the skill",
    )
    subparsers.add_parser(
        "uninstall",
        help="Remove the sqlparse MCP server, skill, and indexes",
    )
    subparsers.add_parser(
        "cleanup",
        help="Remove indexes whose workspace directories no longer exist",
    )
    update_parser = subparsers.add_parser(
        "update",
        help="Replace this binary with a GitHub release and update the skill",
    )
    update_parser.add_argument(
        "--version",
        dest="release_version",
        default=None,
        help="Release to install (e.g. 0.12.0 or v0.12.0); default is latest",
    )
    mcp_parser = subparsers.add_parser("mcp", help="Start the MCP server")
    mcp_parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="SQLMesh project root to index (default: current directory)",
    )
    reload_parser = subparsers.add_parser(
        "reload",
        help="Drop the index and reprocess the SQLMesh project",
    )
    reload_parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="SQLMesh project root to index (default: current directory)",
    )
    profile_parser = subparsers.add_parser(
        "profile",
        help="Full-index with phase timings",
    )
    profile_parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="SQLMesh project root to index (default: current directory)",
    )
    profile_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the text report to a file (optional)",
    )
    return parser


def build_arg_parser(argv: list[str] | None = None) -> argparse.Namespace:
    return make_parser().parse_args(argv)
