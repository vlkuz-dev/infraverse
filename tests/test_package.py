import infraverse


def test_version():
    assert infraverse.__version__ == "0.0.2"


def test_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == infraverse.__version__


def test_version_is_string():
    assert isinstance(infraverse.__version__, str)


def test_subpackages_importable():
    from infraverse import db  # noqa: F401
    from infraverse import providers  # noqa: F401
    from infraverse import sync  # noqa: F401
    from infraverse import comparison  # noqa: F401
    from infraverse import ip  # noqa: F401
    from infraverse import web  # noqa: F401


def test_web_routes_importable():
    from infraverse.web import routes  # noqa: F401


def test_main_module_importable():
    from infraverse import cli  # noqa: F401
    assert callable(cli.main)


def test_main_entry_point():
    from infraverse.__main__ import main  # noqa: F401
    assert callable(main)
