import inspect
import io

from src.cli.progress import ProgressBar, render_bar
from src.parse.sqlmesh_parser import SQLMeshParser
from src.processor import ProjectProcessor


def test_progress_bar_renders_oldschool_meter() -> None:
    stream = io.StringIO()
    bar = ProgressBar(10, label="Indexing", width=10, stream=stream, enabled=True)
    bar.update(0)
    assert "0%" in stream.getvalue()
    bar.update(5)
    bar.finish()
    output = stream.getvalue()
    assert "Indexing" in output
    assert "[█████     ]" in output
    assert "50%" in output
    assert "5/10" not in output
    assert output.endswith("\n")


def test_render_bar_moves_with_small_percent_steps() -> None:
    assert render_bar(0, 100, 10) == "          "
    assert render_bar(1, 100, 10) == "▏         "
    assert render_bar(5, 100, 10) != render_bar(1, 100, 10)
    assert render_bar(100, 100, 10) == "██████████"


def test_progress_bar_silent_when_disabled() -> None:
    stream = io.StringIO()
    bar = ProgressBar(4, label="Indexing", stream=stream, enabled=False)
    bar.update(2)
    bar.finish()
    assert stream.getvalue() == ""


def test_progress_bar_handles_empty_total() -> None:
    stream = io.StringIO()
    bar = ProgressBar(0, label="Indexing", stream=stream, enabled=True)
    bar.update(0)
    bar.finish()
    assert stream.getvalue() == ""


def test_sync_progress_defaults_off_and_full_reload_enables_it() -> None:
    assert inspect.signature(SQLMeshParser.sync).parameters["show_progress"].default is False
    source = inspect.getsource(ProjectProcessor._process_unlocked)
    assert "show_progress=full" in source
