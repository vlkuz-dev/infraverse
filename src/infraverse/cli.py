"""CLI entry point for infraverse."""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _load_infraverse_config(args):
    """Load YAML config if --config was provided, or return None."""
    if not getattr(args, "config", None):
        return None
    from infraverse.config_file import load_config

    try:
        return load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Config file error: {exc}", file=sys.stderr)
        sys.exit(1)


def _setup_logging(infraverse_config=None) -> None:
    """Configure logging, preferring YAML config log_level if available."""
    from infraverse.config import setup_logging

    log_level = infraverse_config.log_level if infraverse_config else None
    setup_logging(log_level=log_level)


def _get_database_url(infraverse_config=None) -> str:
    """Get database URL from YAML config or environment with default."""
    if infraverse_config is not None:
        return infraverse_config.database_url
    return os.getenv("DATABASE_URL", "sqlite:///infraverse.db")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="infraverse",
        description="Infrastructure visibility platform",
    )
    subparsers = parser.add_subparsers(dest="command")

    # sync command
    sync_parser = subparsers.add_parser("sync", help="Sync cloud data to NetBox")
    sync_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file for multi-tenant setup",
    )
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying"
    )
    sync_parser.add_argument(
        "--no-batch",
        action="store_true",
        help="Use sequential sync instead of optimized batch",
    )
    sync_parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip orphaned object cleanup",
    )

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the web UI")
    serve_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file for multi-tenant setup",
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)"
    )

    # db command group
    db_parser = subparsers.add_parser("db", help="Database management")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_init_parser = db_sub.add_parser("init", help="Initialize database tables")
    db_init_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file",
    )
    db_seed_parser = db_sub.add_parser("seed", help="Create default tenant")
    db_seed_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file",
    )
    db_migrate_parser = db_sub.add_parser(
        "migrate", help="Generate a new migration from model changes",
    )
    db_migrate_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file",
    )
    db_migrate_parser.add_argument(
        "-m", "--message", required=True,
        help="Migration description message",
    )
    db_upgrade_parser = db_sub.add_parser(
        "upgrade", help="Apply all pending migrations",
    )
    db_upgrade_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file",
    )
    db_downgrade_parser = db_sub.add_parser(
        "downgrade", help="Roll back the last migration",
    )
    db_downgrade_parser.add_argument(
        "--config", "-c", default=None,
        help="Path to YAML config file",
    )

    return parser



def _ensure_cloud_account(repo, session, tenant_id, provider_type, name):
    """Get or create a CloudAccount for the given provider."""
    accounts = repo.list_cloud_accounts_by_tenant(tenant_id)
    account = next(
        (a for a in accounts if a.provider_type == provider_type and a.name == name),
        None,
    )
    if not account:
        account = repo.create_cloud_account(
            tenant_id=tenant_id, provider_type=provider_type, name=name,
        )
        session.commit()
    return account


def _ingest_to_db(config) -> None:
    """Populate database with data from configured providers."""
    from infraverse.db.engine import create_engine, create_session_factory, init_db
    from infraverse.db.repository import Repository
    from infraverse.sync.ingest import DataIngestor
    from infraverse.providers.yandex import YandexCloudClient

    engine = create_engine(config.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = Repository(session)

        # If config-file tenants already exist, refuse to create a "Default"
        # tenant to avoid duplicating VMs under a separate cloud account.
        existing_tenants = repo.list_tenants()
        non_default = [t for t in existing_tenants if t.name != "Default"]
        if non_default:
            logger.error(
                "Database already contains tenants from config file (%s). "
                "Use --config to run in config-file mode instead of env-var mode.",
                ", ".join(t.name for t in non_default),
            )
            return

        tenant = repo.get_tenant_by_name("Default")
        if not tenant:
            tenant = repo.create_tenant(name="Default")
            session.commit()

        ingestor = DataIngestor(session)
        providers = {}

        yc_account = _ensure_cloud_account(
            repo, session, tenant.id, "yandex_cloud", "Yandex Cloud",
        )
        from infraverse.providers.yc_auth import resolve_token_provider

        yc_creds: dict = {}
        if config.yc_sa_key_file:
            yc_creds["sa_key_file"] = config.yc_sa_key_file
        else:
            yc_creds["token"] = config.yc_token
        yc_client = YandexCloudClient(token_provider=resolve_token_provider(yc_creds))
        providers[yc_account.id] = yc_client

        if config.vcd_configured:
            from infraverse.providers.vcloud import VCloudDirectorClient

            vcd_account = _ensure_cloud_account(
                repo, session, tenant.id, "vcloud", "vCloud Director",
            )
            vcd_client = VCloudDirectorClient(
                url=config.vcd_url,
                username=config.vcd_user,
                password=config.vcd_password,
                org=config.vcd_org or "System",
            )
            providers[vcd_account.id] = vcd_client

        from infraverse.sync.providers import build_zabbix_client

        zabbix_client = build_zabbix_client(legacy_config=config)

        ingestor.ingest_all(providers, zabbix_client)


def _ingest_to_db_with_config(infraverse_config, database_url=None) -> None:
    """Populate database from YAML config-file-driven providers."""
    from infraverse.db.engine import create_engine, create_session_factory, init_db
    from infraverse.sync.orchestrator import run_ingestion_cycle

    if database_url is None:
        database_url = _get_database_url(infraverse_config)

    engine = create_engine(database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        run_ingestion_cycle(session, infraverse_config=infraverse_config)


def cmd_sync(args: argparse.Namespace) -> None:
    """Execute sync command: fetch from providers, store in DB, sync to NetBox."""
    infraverse_config = _load_infraverse_config(args)
    if not infraverse_config:
        print("Error: --config is required for sync command.", file=sys.stderr)
        sys.exit(1)
    _setup_logging(infraverse_config)

    # Populate database with provider data
    try:
        _ingest_to_db_with_config(
            infraverse_config,
            database_url=infraverse_config.database_url,
        )
        logger.info("Database ingestion complete")
    except Exception:
        logger.exception("Database ingestion had errors, continuing with NetBox sync")

    # Sync to NetBox using per-account credentials
    if infraverse_config and infraverse_config.netbox_configured:
        from infraverse.db.engine import create_engine as create_db_engine
        from infraverse.db.engine import create_session_factory
        from infraverse.db.repository import Repository
        from infraverse.providers.netbox import NetBoxClient
        from infraverse.sync.engine import SyncEngine
        from infraverse.sync.providers import build_providers_from_accounts

        nb_cfg = infraverse_config.netbox
        try:
            netbox = NetBoxClient(
                url=nb_cfg.url, token=nb_cfg.token, dry_run=args.dry_run,
            )

            db_engine = create_db_engine(infraverse_config.database_url)
            session_factory = create_session_factory(db_engine)
            with session_factory() as session:
                accounts = Repository(session).list_cloud_accounts()

            providers = build_providers_from_accounts(accounts)
            engine = SyncEngine(netbox, providers, dry_run=args.dry_run)
            stats = engine.run(use_batch=not args.no_batch, cleanup=not args.no_cleanup)
            for provider, provider_stats in stats.items():
                logger.info("Sync complete for %s: %s", provider, provider_stats)
        except Exception:
            logger.exception("Sync failed")
            sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Execute serve command: start web UI."""
    import uvicorn

    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    config = None

    if infraverse_config is not None:
        # Config-file mode: build SimpleNamespace from YAML settings
        import types

        ext = infraverse_config.external_links
        nb = infraverse_config.netbox
        config = types.SimpleNamespace(
            yc_console_url=ext.yc_console_url if ext else None,
            zabbix_host_url=ext.zabbix_host_url if ext else None,
            netbox_vm_url=ext.netbox_vm_url if ext else None,
            zabbix_url=(
                infraverse_config.monitoring.zabbix_url
                if infraverse_config.monitoring_configured
                else None
            ),
            netbox_url=nb.url if nb else None,
            netbox_token=nb.token if nb else None,
            sync_interval_minutes=infraverse_config.sync_interval_minutes,
        )
    else:
        # Env-var mode: try full Config, fall back to SimpleNamespace
        try:
            sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "0"))
        except ValueError:
            sync_interval = 0
        if sync_interval > 0:
            from infraverse.config import Config

            try:
                config = Config.from_env()
            except ValueError as exc:
                logger.warning(
                    "Scheduler disabled - config incomplete: %s", exc,
                )
                config = None

        if config is None:
            import types

            config = types.SimpleNamespace(
                yc_console_url=os.getenv("YC_CONSOLE_URL") or None,
                zabbix_host_url=os.getenv("ZABBIX_HOST_URL") or None,
                netbox_vm_url=os.getenv("NETBOX_VM_URL") or None,
                zabbix_url=os.getenv("ZABBIX_URL") or None,
                netbox_url=os.getenv("NETBOX_URL") or None,
                netbox_token=os.getenv("NETBOX_TOKEN") or None,
                sync_interval_minutes=sync_interval,
            )

    # Sync YAML config to DB on startup so data is available immediately
    if infraverse_config is not None:
        from infraverse.db.engine import create_engine, create_session_factory, init_db
        from infraverse.sync.config_sync import sync_config_to_db

        engine = create_engine(database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            sync_config_to_db(infraverse_config, session)
            session.commit()
        logger.info("Config synced to database")

    from infraverse.web.app import create_app

    app = create_app(
        database_url=database_url,
        config=config,
        infraverse_config=infraverse_config,
    )
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_db_init(args: argparse.Namespace) -> None:
    """Execute db init command: create all database tables via Alembic migrations."""
    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    from infraverse.db.migrate import upgrade_head

    upgrade_head(database_url)
    logger.info("Database initialized")
    print("Database initialized")


def cmd_db_migrate(args: argparse.Namespace) -> None:
    """Execute db migrate command: generate a new Alembic migration."""
    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    from infraverse.db.migrate import generate_revision

    generate_revision(args.message, database_url)
    print(f"Migration created: {args.message}")


def cmd_db_upgrade(args: argparse.Namespace) -> None:
    """Execute db upgrade command: apply all pending Alembic migrations."""
    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    from infraverse.db.migrate import upgrade_head

    upgrade_head(database_url)
    print("Database upgraded to latest migration")


def cmd_db_downgrade(args: argparse.Namespace) -> None:
    """Execute db downgrade command: roll back the last Alembic migration."""
    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    from infraverse.db.migrate import downgrade_one

    downgrade_one(database_url)
    print("Database downgraded by one migration")


def cmd_db_seed(args: argparse.Namespace) -> None:
    """Execute db seed command: create default tenant."""
    infraverse_config = _load_infraverse_config(args)
    _setup_logging(infraverse_config)
    database_url = _get_database_url(infraverse_config)

    from infraverse.db.engine import create_engine, create_session_factory
    from infraverse.db.migrate import upgrade_head
    from infraverse.db.repository import Repository

    upgrade_head(database_url)
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = Repository(session)
        existing = repo.get_tenant_by_name("Default")
        if existing:
            print("Default tenant already exists (id=%d)" % existing.id)
            return
        tenant = repo.create_tenant(name="Default", description="Default tenant")
        session.commit()
        print(f"Created default tenant (id={tenant.id})")


def main() -> None:
    """Main entry point for infraverse CLI."""
    from dotenv import load_dotenv

    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "sync": cmd_sync,
        "serve": cmd_serve,
    }

    if args.command == "db":
        if args.db_command is None:
            parser.parse_args(["db", "--help"])
            sys.exit(1)
        db_commands = {
            "init": cmd_db_init,
            "seed": cmd_db_seed,
            "migrate": cmd_db_migrate,
            "upgrade": cmd_db_upgrade,
            "downgrade": cmd_db_downgrade,
        }
        db_commands[args.db_command](args)
    else:
        commands[args.command](args)
