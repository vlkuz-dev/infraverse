"""Tests for Alembic migration infrastructure and initial migration."""

import os
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect

from infraverse.db.migrate import upgrade_head, stamp_head, downgrade_one, current

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS_DIR = PROJECT_ROOT / "src" / "infraverse" / "db" / "migrations"

EXPECTED_TABLES = {
    "tenants", "cloud_accounts", "vms",
    "monitoring_hosts", "netbox_hosts", "sync_runs",
}


class TestNoManualMigrations:
    """Verify no ALTER TABLE statements exist outside Alembic migrations."""

    def test_no_alter_table_in_source(self):
        """Source code should not contain ALTER TABLE (only Alembic migrations may)."""
        src_dir = PROJECT_ROOT / "src" / "infraverse"
        migrations_dir = src_dir / "db" / "migrations"

        for py_file in src_dir.rglob("*.py"):
            # Skip Alembic migration files
            if migrations_dir in py_file.parents or py_file == migrations_dir:
                continue
            content = py_file.read_text()
            assert "ALTER TABLE" not in content, \
                f"Found ALTER TABLE in {py_file.relative_to(PROJECT_ROOT)}"


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
        command.current(cfg)

    def test_alembic_config_with_database_url_env(self, tmp_path):
        db_path = tmp_path / "env_test.db"
        with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{db_path}"}):
            cfg = Config(str(ALEMBIC_INI))
            command.current(cfg)

    def test_initial_migration_file_exists(self):
        versions_dir = MIGRATIONS_DIR / "versions"
        migration_files = list(versions_dir.glob("*_initial_schema.py"))
        assert len(migration_files) == 1


class TestUpgradeHead:
    """Test alembic upgrade head on a fresh database."""

    def test_upgrade_head_creates_all_tables(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        db_url = f"sqlite:///{db_path}"
        upgrade_head(db_url)

        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        # All 6 app tables should exist
        assert EXPECTED_TABLES.issubset(tables)
        # Alembic version table should exist
        assert "alembic_version" in tables

    def test_upgrade_head_creates_correct_columns(self, tmp_path):
        db_path = tmp_path / "columns.db"
        db_url = f"sqlite:///{db_path}"
        upgrade_head(db_url)

        engine = create_engine(db_url)
        inspector = inspect(engine)

        # Verify columns that were previously added by _migrate_schema
        vm_cols = {c["name"] for c in inspector.get_columns("vms")}
        assert "last_sync_error" in vm_cols
        assert "monitoring_exempt" in vm_cols
        assert "monitoring_exempt_reason" in vm_cols

        nb_cols = {c["name"] for c in inspector.get_columns("netbox_hosts")}
        assert "tenant_id" in nb_cols

    def test_upgrade_head_sets_revision(self, tmp_path):
        db_path = tmp_path / "revision.db"
        db_url = f"sqlite:///{db_path}"
        upgrade_head(db_url)

        rev = current(db_url)
        assert rev is not None

    def test_upgrade_head_idempotent(self, tmp_path):
        db_path = tmp_path / "idempotent.db"
        db_url = f"sqlite:///{db_path}"
        upgrade_head(db_url)
        # Running again should not raise
        upgrade_head(db_url)

        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)


class TestStampHead:
    """Test alembic stamp head for existing databases."""

    def test_stamp_head_on_existing_db(self, tmp_path):
        """Stamp head marks an existing DB as current without running migrations."""
        db_path = tmp_path / "existing.db"
        db_url = f"sqlite:///{db_path}"

        # Simulate existing DB created by Base.metadata.create_all
        from infraverse.db.models import Base
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)

        # Verify no alembic version yet
        assert current(db_url) is None

        # Stamp marks it as current
        stamp_head(db_url)
        rev = current(db_url)
        assert rev is not None

    def test_stamp_then_upgrade_is_noop(self, tmp_path):
        """After stamp head, upgrade head should be a no-op (no errors)."""
        db_path = tmp_path / "stamp_upgrade.db"
        db_url = f"sqlite:///{db_path}"

        from infraverse.db.models import Base
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)

        stamp_head(db_url)
        rev_before = current(db_url)

        # Upgrade after stamp should succeed and not change revision
        upgrade_head(db_url)
        rev_after = current(db_url)
        assert rev_before == rev_after

        # Tables should still be intact
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)


class TestDowngradeOne:
    """Test alembic downgrade -1 rolls back the last migration."""

    def test_downgrade_removes_tables(self, tmp_path):
        """After upgrade head, downgrade -1 should drop all tables."""
        db_path = tmp_path / "downgrade.db"
        db_url = f"sqlite:///{db_path}"

        # First upgrade to head
        upgrade_head(db_url)
        engine = create_engine(db_url)
        inspector = inspect(engine)
        assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))

        # Downgrade -1 should remove all app tables (initial migration is the only one)
        downgrade_one(db_url)
        inspector = inspect(engine)
        remaining = set(inspector.get_table_names())
        assert not EXPECTED_TABLES.intersection(remaining), \
            f"App tables should be removed after downgrade: {EXPECTED_TABLES.intersection(remaining)}"
        # alembic_version should still exist
        assert "alembic_version" in remaining

    def test_downgrade_sets_revision_to_none(self, tmp_path):
        """After downgrading the only migration, revision should be None."""
        db_path = tmp_path / "downgrade_rev.db"
        db_url = f"sqlite:///{db_path}"

        upgrade_head(db_url)
        assert current(db_url) is not None

        downgrade_one(db_url)
        assert current(db_url) is None

    def test_upgrade_after_downgrade_restores_tables(self, tmp_path):
        """Upgrade after downgrade should restore all tables."""
        db_path = tmp_path / "roundtrip.db"
        db_url = f"sqlite:///{db_path}"

        upgrade_head(db_url)
        downgrade_one(db_url)
        upgrade_head(db_url)

        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)
        assert current(db_url) is not None


class TestMigrateHelpers:
    """Test the programmatic migrate helper functions."""

    def test_current_returns_none_for_empty_db(self, tmp_path):
        db_path = tmp_path / "empty.db"
        db_url = f"sqlite:///{db_path}"
        # Create the database file
        create_engine(db_url).dispose()
        rev = current(db_url)
        assert rev is None

    def test_current_returns_revision_after_upgrade(self, tmp_path):
        db_path = tmp_path / "upgraded.db"
        db_url = f"sqlite:///{db_path}"
        upgrade_head(db_url)
        rev = current(db_url)
        assert rev is not None
        assert isinstance(rev, str)
        assert len(rev) > 0
