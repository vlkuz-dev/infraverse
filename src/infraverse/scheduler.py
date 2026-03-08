"""Scheduled data ingestion service using APScheduler."""

import logging
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from infraverse.config import Config
from infraverse.db.repository import Repository
from infraverse.sync.ingest import DataIngestor
from infraverse.sync.orchestrator import run_ingestion_cycle

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages periodic data ingestion from cloud providers and monitoring systems.

    Wraps APScheduler's BackgroundScheduler to run DataIngestor on a configurable
    interval. Supports on-demand triggering and status reporting.

    When infraverse_config (from YAML config file) is provided, reads cloud
    credentials from CloudAccount.config JSON and monitoring config from the
    InfraverseConfig. Otherwise falls back to env-var-based Config.
    """

    def __init__(self, session_factory, config, infraverse_config=None):
        self._scheduler = BackgroundScheduler()
        self._session_factory = session_factory
        self._config = config
        self._infraverse_config = infraverse_config
        self._last_result: dict | None = None
        self._last_run_time: datetime | None = None
        self._running = False
        self._job_lock = threading.Lock()

    def start(self, interval_minutes: int) -> None:
        """Start the scheduler with the given interval.

        Args:
            interval_minutes: Minutes between ingestion runs.
        """
        self._scheduler.add_job(
            self._run_ingestion,
            "interval",
            minutes=interval_minutes,
            id="ingestion",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler started with interval=%d minutes", interval_minutes)

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    def trigger_now(self) -> str:
        """Trigger an immediate ingestion run outside the regular schedule.

        Starts _run_ingestion in a daemon thread. The lock inside
        _run_ingestion guarantees that a concurrent interval run and this
        manual trigger never overlap — the second call is skipped.

        Note: there is a small TOCTOU window between the locked() check
        and the thread acquiring the lock. In the unlikely event an
        interval run starts in that window, the manual run is silently
        skipped while this method still returns "triggered". This is
        acceptable because the interval run performs the same work.

        Returns:
            Status message: "triggered" on success, "already_running" if skipped.
        """
        if self._job_lock.locked():
            logger.warning("Ingestion already running, skipping manual trigger")
            return "already_running"

        threading.Thread(target=self._run_ingestion, daemon=True).start()
        logger.info("Ingestion triggered manually")
        return "triggered"

    def get_status(self) -> dict:
        """Return current scheduler state.

        Returns:
            Dict with keys: running, next_run_time, last_run_time, last_result.
        """
        next_run_time = None
        job = self._scheduler.get_job("ingestion")
        if job is not None and job.next_run_time is not None:
            next_run_time = job.next_run_time.isoformat()

        return {
            "running": self._running,
            "next_run_time": next_run_time,
            "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
            "last_result": self._last_result,
        }

    def _run_ingestion(self) -> None:
        """Execute a full ingestion cycle using shared orchestrator."""
        if not self._job_lock.acquire(blocking=False):
            logger.warning("Ingestion already running, skipping this execution")
            return

        logger.info("Starting scheduled ingestion")
        session = None
        try:
            session = self._session_factory()
            results = run_ingestion_cycle(
                session,
                infraverse_config=self._infraverse_config,
                legacy_config=self._config,
            )

            # Post-ingestion steps (scheduler-specific)
            ingestor = DataIngestor(session)
            self._run_netbox_ingestion(ingestor, results)

            repo = Repository(session)
            accounts = repo.list_cloud_accounts()

            netbox_stats = self._run_netbox_sync(accounts=accounts)
            if netbox_stats is not None:
                results["netbox_sync"] = netbox_stats
                self._store_vm_sync_errors(repo, netbox_stats)
                session.commit()

            self._last_result = results
            self._last_run_time = datetime.now(timezone.utc)
            logger.info("Scheduled ingestion completed: %s", results)
        except Exception as exc:
            self._last_result = {"error": str(exc)}
            self._last_run_time = datetime.now(timezone.utc)
            logger.error("Scheduled ingestion failed: %s", exc)
        finally:
            if session is not None:
                session.close()
            self._job_lock.release()

    def _run_netbox_ingestion(self, ingestor, results: dict) -> None:
        """Ingest NetBox VMs into local DB if NetBox is configured."""
        netbox_url, netbox_token, _ = self._resolve_netbox_config()
        if not netbox_url or not netbox_token:
            return

        try:
            from infraverse.providers.netbox import NetBoxClient

            client = NetBoxClient(url=netbox_url, token=netbox_token)
            count = ingestor.ingest_netbox_hosts(client)
            results["netbox_ingestion"] = "success"
            logger.info("NetBox ingestion: %d VMs ingested", count)
        except Exception as exc:
            results["netbox_ingestion"] = f"error: {exc}"
            logger.error("NetBox ingestion failed: %s", exc)

    @staticmethod
    def _store_vm_sync_errors(repo: Repository, netbox_stats: dict) -> None:
        """Write per-VM sync errors from SyncEngine results to DB."""
        all_errors: dict[str, str] = {}
        all_synced: set[str] = set()
        for provider_key, provider_stats in netbox_stats.items():
            if not isinstance(provider_stats, dict):
                continue
            all_errors.update(provider_stats.get("vm_errors", {}))
            all_synced.update(provider_stats.get("synced_vms", set()))
        if all_errors or all_synced:
            repo.update_vm_sync_errors(all_errors, all_synced)

    def _run_netbox_sync(self, accounts=None) -> dict | None:
        """Run NetBox sync (Cloud -> NetBox push) using SyncEngine.

        Builds providers from accounts and delegates to SyncEngine for both
        env-var and config-file modes.

        Args:
            accounts: List of CloudAccount DB objects.

        Returns:
            Stats dict keyed by provider key, or None if skipped/failed.
        """
        netbox_url, netbox_token, dry_run = self._resolve_netbox_config()
        if not netbox_url or not netbox_token:
            logger.info("NetBox sync skipped: no NETBOX_URL/NETBOX_TOKEN configured")
            return None

        try:
            from infraverse.providers.netbox import NetBoxClient
            from infraverse.sync.engine import SyncEngine
            from infraverse.sync.providers import build_providers_from_accounts

            netbox = NetBoxClient(url=netbox_url, token=netbox_token, dry_run=dry_run)
            providers = build_providers_from_accounts(accounts or [])
            logger.info("Starting NetBox sync after ingestion")
            engine = SyncEngine(netbox, providers, dry_run=dry_run)
            stats = engine.run()
            logger.info("NetBox sync completed: %s", stats)
            return stats
        except Exception as exc:
            logger.error("NetBox sync failed: %s", exc)
            return {"error": str(exc)}

    def _resolve_netbox_config(self) -> tuple:
        """Resolve NetBox URL, token, and dry_run from available configs.

        Returns:
            Tuple of (netbox_url, netbox_token, dry_run).
        """
        # Config-file mode
        if self._infraverse_config is not None and self._infraverse_config.netbox_configured:
            return (
                self._infraverse_config.netbox.url,
                self._infraverse_config.netbox.token,
                False,
            )

        # Env-var mode with real Config
        if isinstance(self._config, Config):
            return (
                self._config.netbox_url,
                self._config.netbox_token,
                self._config.dry_run,
            )

        # Fallback: SimpleNamespace or mock
        return (
            getattr(self._config, "netbox_url", None),
            getattr(self._config, "netbox_token", None),
            False,
        )
