"""Tests for Alembic migration infrastructure setup."""

import os
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS_DIR = PROJECT_ROOT / "src" / "infraverse" / "db" / "migrations"


class TestAlembicSetup:
    def test_alembic_ini_exists(self):
        assert ALEMBIC_INI.exists()

    def test_migrations_directory_exists(self):
        assert MIGRATIONS_DIR.exists()
        assert (MIGRATIONS_DIR / "env.py").exists()
        assert (MIGRATIONS_DIR / "versions").exists()
        assert (MIGRATIONS_DIR / "script.py.mako").exists()

    def test_alembic_ini_script_location(self):
        cfg = Config(str(ALEMBIC_INI))
        script_location = cfg.get_main_option("script_location")
        # The %(here)s token gets resolved, so check it ends with the right path
        assert script_location.endswith("src/infraverse/db/migrations")

    def test_alembic_ini_default_url(self):
        cfg = Config(str(ALEMBIC_INI))
        url = cfg.get_main_option("sqlalchemy.url")
        assert url == "sqlite:///infraverse.db"

    def test_env_py_imports_base_metadata(self):
        env_py = (MIGRATIONS_DIR / "env.py").read_text()
        assert "from infraverse.db.models import Base" in env_py
        assert "target_metadata = Base.metadata" in env_py

    def test_env_py_database_url_override(self):
        env_py = (MIGRATIONS_DIR / "env.py").read_text()
        assert 'os.environ.get("DATABASE_URL")' in env_py

    def test_alembic_current_on_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        # Should not raise - empty DB with no migrations is valid
        command.current(cfg)

    def test_alembic_config_with_database_url_env(self, tmp_path):
        db_path = tmp_path / "env_test.db"
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{db_path}"}):
            cfg = Config(str(ALEMBIC_INI))
            # Trigger env.py to run by calling current
            command.current(cfg)
