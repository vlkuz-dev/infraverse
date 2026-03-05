"""CLI entry point for infraverse."""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging from LOG_LEVEL env var."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in ("urllib3", "requests", "httpx", "httpcore", "pynetbox"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _get_database_url() -> str:
    """Get database URL from environment with default."""
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
        "--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)"
    )

    # db command group
    db_parser = subparsers.add_parser("db", help="Database management")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("init", help="Initialize database tables")
    db_sub.add_parser("seed", help="Create default tenant")

    return parser


def cmd_sync(args: argparse.Namespace) -> None:
    """Execute sync command: fetch from providers, sync to NetBox."""
    from infraverse.config import Config

    try:
        config = Config.from_env(dry_run=args.dry_run)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    config.setup_logging()

    from infraverse.sync.engine import SyncEngine

    try:
        engine = SyncEngine(config)
        stats = engine.run(use_batch=not args.no_batch, cleanup=not args.no_cleanup)
        logger.info("Sync complete: %s", stats)
    except Exception:
        logger.exception("Sync failed")
        sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Execute serve command: start web UI."""
    import uvicorn

    _setup_logging()
    database_url = _get_database_url()

    from infraverse.web.app import create_app

    app = create_app(database_url=database_url)
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_db_init(args: argparse.Namespace) -> None:
    """Execute db init command: create all database tables."""
    _setup_logging()
    database_url = _get_database_url()

    from infraverse.db.engine import create_engine, init_db

    engine = create_engine(database_url)
    init_db(engine)
    logger.info("Database initialized")
    print("Database initialized")


def cmd_db_seed(args: argparse.Namespace) -> None:
    """Execute db seed command: create default tenant."""
    _setup_logging()
    database_url = _get_database_url()

    from infraverse.db.engine import create_engine, create_session_factory, init_db
    from infraverse.db.repository import Repository

    engine = create_engine(database_url)
    init_db(engine)
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
        }
        db_commands[args.db_command](args)
    else:
        commands[args.command](args)
