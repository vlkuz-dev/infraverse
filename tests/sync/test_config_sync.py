"""Tests for config-to-DB synchronization."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from infraverse.config_file import (
    CloudAccountConfig,
    InfraverseConfig,
    TenantConfig,
)
from infraverse.db.models import Base
from infraverse.db.repository import Repository
from infraverse.sync.config_sync import sync_config_to_db


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def repo(session):
    return Repository(session)


def _make_config(tenants_dict=None):
    """Build an InfraverseConfig from a simple dict of tenant_name -> list of (acct_name, provider, creds)."""
    tenants = {}
    for tname, accounts in (tenants_dict or {}).items():
        accs = [
            CloudAccountConfig(name=a[0], provider=a[1], credentials=a[2] if len(a) > 2 else {})
            for a in accounts
        ]
        tenants[tname] = TenantConfig(name=tname, cloud_accounts=accs)
    return InfraverseConfig(tenants=tenants)


class TestSyncConfigToDb:
    def test_creates_new_tenants(self, session, repo):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud", {"token": "abc"})],
            "beta": [("beta-yc", "yandex_cloud", {"token": "xyz"})],
        })
        report = sync_config_to_db(config, session)

        tenants = repo.list_tenants()
        assert len(tenants) == 2
        names = {t.name for t in tenants}
        assert names == {"acme", "beta"}
        assert report.tenants_created == 2
        assert report.tenants_updated == 0

    def test_creates_cloud_accounts(self, session, repo):
        config = _make_config({
            "acme": [
                ("acme-yc", "yandex_cloud", {"token": "t1"}),
                ("acme-vc", "vcloud", {"url": "https://vcd.example.com"}),
            ],
        })
        report = sync_config_to_db(config, session)

        accounts = repo.list_cloud_accounts()
        assert len(accounts) == 2
        assert report.accounts_created == 2
        assert report.accounts_updated == 0

    def test_stores_credentials_in_config_json(self, session, repo):
        creds = {"token": "secret123", "folder_id": "abc"}
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud", creds)],
        })
        sync_config_to_db(config, session)

        account = repo.list_cloud_accounts()[0]
        assert account.config["token"] == "secret123"
        assert account.config["folder_id"] == "abc"

    def test_updates_existing_tenant_description(self, session, repo):
        # First sync
        config1 = InfraverseConfig(tenants={
            "acme": TenantConfig(
                name="acme",
                description="Old desc",
                cloud_accounts=[CloudAccountConfig(name="yc", provider="yandex_cloud")],
            ),
        })
        sync_config_to_db(config1, session)

        # Second sync with updated description
        config2 = InfraverseConfig(tenants={
            "acme": TenantConfig(
                name="acme",
                description="New desc",
                cloud_accounts=[CloudAccountConfig(name="yc", provider="yandex_cloud")],
            ),
        })
        report = sync_config_to_db(config2, session)

        tenant = repo.get_tenant_by_name("acme")
        assert tenant.description == "New desc"
        assert report.tenants_created == 0
        assert report.tenants_updated == 1

    def test_updates_existing_account_credentials(self, session, repo):
        config1 = _make_config({"acme": [("acme-yc", "yandex_cloud", {"token": "old"})]})
        sync_config_to_db(config1, session)

        config2 = _make_config({"acme": [("acme-yc", "yandex_cloud", {"token": "new"})]})
        report = sync_config_to_db(config2, session)

        account = repo.list_cloud_accounts()[0]
        assert account.config["token"] == "new"
        assert report.accounts_updated == 1
        assert report.accounts_created == 0

    def test_idempotent_no_changes(self, session, repo):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
        })
        sync_config_to_db(config, session)
        report2 = sync_config_to_db(config, session)

        # Second run should find existing records and not create new ones
        assert report2.tenants_created == 0
        assert report2.accounts_created == 0
        # Accounts are updated (credentials refreshed) even if same
        assert report2.accounts_updated == 1

        tenants = repo.list_tenants()
        accounts = repo.list_cloud_accounts()
        assert len(tenants) == 1
        assert len(accounts) == 1

    def test_idempotent_same_ids(self, session, repo):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        sync_config_to_db(config, session)
        tenant_id_1 = repo.get_tenant_by_name("acme").id
        account_id_1 = repo.list_cloud_accounts()[0].id

        sync_config_to_db(config, session)
        tenant_id_2 = repo.get_tenant_by_name("acme").id
        account_id_2 = repo.list_cloud_accounts()[0].id

        assert tenant_id_1 == tenant_id_2
        assert account_id_1 == account_id_2

    def test_deactivates_removed_account(self, session, repo):
        # First sync: two accounts
        config1 = _make_config({
            "acme": [
                ("acme-yc", "yandex_cloud", {"token": "t1"}),
                ("acme-vc", "vcloud", {"url": "https://vcd.example.com"}),
            ],
        })
        sync_config_to_db(config1, session)

        # Second sync: only one account remains
        config2 = _make_config({
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
        })
        report = sync_config_to_db(config2, session)

        accounts = repo.list_cloud_accounts()
        active = [a for a in accounts if a.is_active]
        inactive = [a for a in accounts if not a.is_active]
        assert len(active) == 1
        assert active[0].name == "acme-yc"
        assert len(inactive) == 1
        assert inactive[0].name == "acme-vc"
        assert report.accounts_deactivated == 1

    def test_reactivates_previously_deactivated_account(self, session, repo):
        # Sync with account
        config1 = _make_config({
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
        })
        sync_config_to_db(config1, session)

        # Remove account
        config2 = _make_config({
            "acme": [("acme-other", "vcloud", {"url": "x"})],
        })
        sync_config_to_db(config2, session)

        # Re-add the original account
        config3 = _make_config({
            "acme": [
                ("acme-other", "vcloud", {"url": "x"}),
                ("acme-yc", "yandex_cloud", {"token": "t2"}),
            ],
        })
        sync_config_to_db(config3, session)

        account = repo.get_cloud_account_by_name(
            repo.get_tenant_by_name("acme").id, "acme-yc"
        )
        assert account.is_active is True
        assert account.config["token"] == "t2"

    def test_new_accounts_are_active(self, session, repo):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        sync_config_to_db(config, session)

        account = repo.list_cloud_accounts()[0]
        assert account.is_active is True

    def test_multiple_tenants_multiple_accounts(self, session, repo):
        config = _make_config({
            "acme": [
                ("acme-yc", "yandex_cloud", {"token": "a1"}),
                ("acme-vc", "vcloud", {"url": "x"}),
            ],
            "beta": [
                ("beta-yc", "yandex_cloud", {"token": "b1"}),
            ],
        })
        report = sync_config_to_db(config, session)

        assert report.tenants_created == 2
        assert report.accounts_created == 3
        assert len(repo.list_tenants()) == 2
        assert len(repo.list_cloud_accounts()) == 3

        acme = repo.get_tenant_by_name("acme")
        beta = repo.get_tenant_by_name("beta")
        assert len(repo.list_cloud_accounts(tenant_id=acme.id)) == 2
        assert len(repo.list_cloud_accounts(tenant_id=beta.id)) == 1

    def test_provider_type_stored_correctly(self, session, repo):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        sync_config_to_db(config, session)

        account = repo.list_cloud_accounts()[0]
        assert account.provider_type == "yandex_cloud"

    def test_tenant_not_in_config_accounts_deactivated(self, session, repo):
        # Sync two tenants
        config1 = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
            "beta": [("beta-yc", "yandex_cloud")],
        })
        sync_config_to_db(config1, session)

        # Second sync has only one tenant — the other tenant's accounts should be deactivated
        config2 = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        report = sync_config_to_db(config2, session)

        beta = repo.get_tenant_by_name("beta")
        beta_accounts = repo.list_cloud_accounts(tenant_id=beta.id)
        assert all(not a.is_active for a in beta_accounts)
        assert report.accounts_deactivated == 1

    def test_empty_config_deactivates_all(self, session, repo):
        """Edge case: config with no tenants isn't possible (parser rejects it),
        but if a previously synced tenant is removed, its accounts should be deactivated."""
        config1 = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        sync_config_to_db(config1, session)

        # A new config with a different tenant
        config2 = _make_config({
            "newco": [("newco-yc", "yandex_cloud")],
        })
        sync_config_to_db(config2, session)

        acme_accounts = repo.list_cloud_accounts(
            tenant_id=repo.get_tenant_by_name("acme").id
        )
        assert all(not a.is_active for a in acme_accounts)


class TestSyncReport:
    def test_report_fields(self, session):
        config = _make_config({
            "acme": [("acme-yc", "yandex_cloud")],
        })
        report = sync_config_to_db(config, session)
        assert hasattr(report, "tenants_created")
        assert hasattr(report, "tenants_updated")
        assert hasattr(report, "accounts_created")
        assert hasattr(report, "accounts_updated")
        assert hasattr(report, "accounts_deactivated")
