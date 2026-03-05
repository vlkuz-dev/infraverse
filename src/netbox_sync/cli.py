"""CLI entry point for netbox-sync."""

import argparse
import logging
import sys

from dotenv import load_dotenv

from netbox_sync import __version__
from netbox_sync.config import Config
from netbox_sync.sync.engine import SyncEngine

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Argument list to parse (defaults to sys.argv[1:]).
    """
    parser = argparse.ArgumentParser(
        prog="netbox-sync",
        description="Sync Yandex Cloud resources to NetBox",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # sync subcommand (also the default when no subcommand given)
    sync_parser = subparsers.add_parser("sync", help="Run sync (default)")
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no changes will be made)",
    )
    sync_parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip cleanup of orphaned objects",
    )
    sync_parser.add_argument(
        "--standard",
        action="store_true",
        help="Use standard sync instead of optimized batch operations",
    )

    # serve subcommand
    serve_parser = subparsers.add_parser("serve", help="Start web UI server")
    serve_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )

    args, remaining = parser.parse_known_args(argv)

    # Default to sync when no subcommand given — re-parse with sync flags
    if args.command is None:
        args = sync_parser.parse_args(remaining)
        args.command = "sync"
    elif remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    return args


def _run_sync(args: argparse.Namespace) -> None:
    """Run the sync engine."""
    try:
        config = Config.from_env(dry_run=args.dry_run)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    config.setup_logging()
    logger.debug("Config: %s", config)

    engine = SyncEngine(config)

    try:
        stats = engine.run(
            use_batch=not args.standard,
            cleanup=not args.no_cleanup,
        )
        if stats:
            logger.info("Sync stats: %s", stats)
    except Exception:
        logger.exception("Sync failed")
        sys.exit(1)


def _run_serve(args: argparse.Namespace) -> None:
    """Start the FastAPI web server."""
    import uvicorn

    from netbox_sync.web.app import create_app

    load_dotenv()

    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    config.setup_logging()

    app = create_app(config=config)
    uvicorn.run(app, host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    """Main entry point for netbox-sync CLI."""
    args = parse_args(argv)

    load_dotenv()

    if args.command == "serve":
        _run_serve(args)
    else:
        _run_sync(args)
