from pathlib import Path


def test_nuitka_build_includes_dateparser_translation_data() -> None:
    script = Path(".github/nuitka_build.sh").read_text(encoding="utf-8")
    assert "--include-package=dateparser.data.date_translation_data" in script


def test_nuitka_build_excludes_certifi_tests() -> None:
    script = Path(".github/nuitka_build.sh").read_text(encoding="utf-8")
    assert "--nofollow-import-to=certifi.tests" in script


def test_nuitka_build_excludes_sqlmesh_magics_and_ipython() -> None:
    script = Path(".github/nuitka_build.sh").read_text(encoding="utf-8")
    assert "--nofollow-import-to=sqlmesh.magics" in script
    assert "--nofollow-import-to=ipywidgets" in script
    assert "--noinclude-IPython-mode=nofollow" in script
    assert "--noinclude-unittest-mode=warning" in script


def test_nuitka_build_excludes_tkinter() -> None:
    script = Path(".github/nuitka_build.sh").read_text(encoding="utf-8")
    assert "--nofollow-import-to=tkinter" in script
    assert "--nofollow-import-to=_tkinter" in script
    assert "--disable-plugin=tk-inter" in script
