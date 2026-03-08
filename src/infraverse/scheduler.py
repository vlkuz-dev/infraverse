"""Scheduled data ingestion service using APScheduler."""

import logging
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

    def trigger_now(self) -> None:
        """Trigger an immediate ingestion run outside the regular schedule."""
        job = self._scheduler.get_job("ingestion")
        if job is not None:
            job.modify(next_run_time=datetime.now(timezone.utc))
        else:
            self._scheduler.add_job(
                self._run_ingestion,
                id="ingestion_manual",
                replace_existing=True,
            )
        logger.info("Ingestion triggered manually")

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
        logger.info("Starting scheduled ingestion")
        session = self._session_factory()
        try:
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
            if self._infraverse_config is not None:
                accounts = [a for a in accounts if a.is_active]

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
            session.close()

    def _build_providers(self, accounts) -> dict:
        """Build provider instances from cloud accounts.

        When infraverse_config is set, reads credentials from account.config dict
        via build_provider(). Otherwise uses env-var-based self._config.

        Returns:
            Dict mapping account ID -> CloudProvider instance.
        """
        from infraverse.sync.providers import build_provider

        providers = {}
        for account in accounts:
            try:
                if self._infraverse_config is not None:
                    # Config-file mode: read credentials from account.config
                    result = build_provider(account)
                    if result is not None:
                        providers[account.id] = result[0]
                else:
                    # Env-var mode: read credentials from self._config
                    from infraverse.providers.yandex import YandexCloudClient
                    from infraverse.providers.vcloud import VCloudDirectorClient

                    if account.provider_type == "yandex_cloud":
                        from infraverse.providers.yc_auth import resolve_token_provider as _resolve

                        yc_creds = {}
                        if getattr(self._config, "yc_sa_key_file", None):
                            yc_creds["sa_key_file"] = self._config.yc_sa_key_file
                        else:
                            yc_creds["token"] = self._config.yc_token
                        provider = _resolve(yc_creds)
                        providers[account.id] = YandexCloudClient(
                            token_provider=provider,
                        )
                    elif account.provider_type == "vcloud" and self._config.vcd_configured:
                        providers[account.id] = VCloudDirectorClient(
                            url=self._config.vcd_url,
                            username=self._config.vcd_user,
                            password=self._config.vcd_password,
                            org=(account.config or {}).get("org", self._config.vcd_org or "System"),
                        )
            except Exception as exc:
                logger.error("Failed to build provider for account %s: %s", account.name, exc)
        return providers

    def _build_zabbix_client(self):
        """Build a ZabbixClient if configured, otherwise return None.

        Delegates to sync.providers.build_zabbix_client().
        """
        from infraverse.sync.providers import build_zabbix_client

        return build_zabbix_client(
            infraverse_config=self._infraverse_config,
            legacy_config=self._config,
        )

    def _run_netbox_ingestion(self, ingestor, results: dict) -> None:
        """Ingest NetBox VMs into local DB if NetBox is configured."""
        netbox_url = None
        netbox_token = None

        if self._infraverse_config is not None and self._infraverse_config.netbox_configured:
            netbox_url = self._infraverse_config.netbox.url
            netbox_token = self._infraverse_config.netbox.token

        if not netbox_url:
            # Env-var / SimpleNamespace mode
            netbox_url = getattr(self._config, "netbox_url", None)
            netbox_token = getattr(self._config, "netbox_token", None)

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
        """Run NetBox sync (Cloud → NetBox push).

        In env-var mode, delegates to SyncEngine.
        In config-file mode, iterates over active accounts and syncs each
        using sync_infrastructure + sync_vms_optimized directly.

        Args:
            accounts: List of CloudAccount DB objects (used in config-file mode).

        Returns:
            Stats dict keyed by provider/account, or None if skipped/failed.
        """
        # Env-var mode: use SyncEngine with legacy Config
        if isinstance(self._config, Config):
            try:
                from infraverse.providers.netbox import NetBoxClient
                from infraverse.sync.engine import SyncEngine
                from infraverse.sync.providers import build_providers_from_accounts

                netbox_url = self._config.netbox_url
                netbox_token = self._config.netbox_token
                if not netbox_url or not netbox_token:
                    logger.info("NetBox sync skipped: no NETBOX_URL/NETBOX_TOKEN configured")
                    return None

                netbox = NetBoxClient(
                    url=netbox_url, token=netbox_token,
                    dry_run=self._config.dry_run,
                )
                providers = build_providers_from_accounts(accounts or [])
                logger.info("Starting NetBox sync after ingestion")
                engine = SyncEngine(netbox, providers, dry_run=self._config.dry_run)
                stats = engine.run()
                logger.info("NetBox sync completed: %s", stats)
                return stats
            except Exception as exc:
                logger.error("NetBox sync failed: %s", exc)
                return {"error": str(exc)}

        # Config-file mode: sync per-account
        if self._infraverse_config is None or not accounts:
            return None

        netbox_url = None
        netbox_token = None
        if self._infraverse_config.netbox_configured:
            netbox_url = self._infraverse_config.netbox.url
            netbox_token = self._infraverse_config.netbox.token
        if not netbox_url:
            netbox_url = getattr(self._config, "netbox_url", None)
            netbox_token = getattr(self._config, "netbox_token", None)
        if not netbox_url or not netbox_token:
            logger.info("NetBox sync skipped: no NETBOX_URL/NETBOX_TOKEN configured")
            return None

        return self._run_netbox_sync_per_account(accounts, netbox_url, netbox_token)

    def _run_netbox_sync_per_account(
        self, accounts, netbox_url: str, netbox_token: str,
    ) -> dict:
        """Sync each active cloud account to NetBox individually.

        Returns:
            Stats dict keyed by account name.
        """
        from infraverse.providers.netbox import NetBoxClient
        from infraverse.sync.infrastructure import sync_infrastructure
        from infraverse.sync.batch import sync_vms_optimized
        from infraverse.sync.provider_profile import get_profile
        from infraverse.sync.providers import build_provider

        netbox = NetBoxClient(url=netbox_url, token=netbox_token)
        all_stats: dict = {}

        for account in accounts:
            if not account.is_active:
                continue

            try:
                profile = get_profile(account.provider_type)
            except KeyError:
                logger.warning(
                    "No provider profile for '%s', skipping NetBox sync for %s",
                    account.provider_type, account.name,
                )
                continue

            try:
                result = build_provider(account)
                if result is None:
                    logger.warning("Could not build provider for account %s", account.name)
                    continue
                client = result[0]

                logger.info(
                    "NetBox sync: fetching data from %s (%s)",
                    account.name, profile.display_name,
                )
                data = client.fetch_all_data()
                if not data or not isinstance(data, dict):
                    logger.error("Failed to fetch data from %s", account.name)
                    all_stats[account.name] = {"error": "failed to fetch cloud data"}
                    continue

                do_cleanup = not data.get("_has_fetch_errors", False)

                netbox.ensure_sync_tag(
                    tag_name=profile.tag_name,
                    tag_slug=profile.tag_slug,
                    tag_color=profile.tag_color,
                    tag_description=profile.tag_description,
                )

                id_mapping = sync_infrastructure(
                    data, netbox, cleanup_orphaned=do_cleanup,
                    provider_profile=profile,
                )

                stats = sync_vms_optimized(
                    data, netbox, id_mapping,
                    cleanup_orphaned=do_cleanup,
                    provider_profile=profile,
                )
                all_stats[account.name] = stats
                logger.info("NetBox sync for %s completed: %s", account.name, stats)

            except Exception as exc:
                logger.error("NetBox sync failed for account %s: %s", account.name, exc)
                all_stats[account.name] = {"error": str(exc)}

        logger.info("NetBox sync (config-file mode) completed: %s", all_stats)
        return all_stats
