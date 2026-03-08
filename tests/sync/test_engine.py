"""Tests for infraverse.sync.engine module."""

from unittest.mock import patch

import pytest

from infraverse.config import Config
from infraverse.sync.engine import SyncEngine
from infraverse.sync.provider_profile import YC_PROFILE


@pytest.fixture
def config():
    return Config(
        yc_token="test-yc-token",
        netbox_url="https://netbox.test",
        netbox_token="test-nb-token",
        dry_run=False,
    )


@pytest.fixture
def yc_data():
    return {
        "zones": [{"id": "ru-central1-a", "name": "ru-central1-a"}],
        "clouds": [{"id": "cloud-1", "name": "my-cloud"}],
        "folders": [{"id": "folder-1", "name": "default", "cloud_name": "my-cloud"}],
        "vpcs": [],
        "subnets": [],
        "vms": [{"id": "vm-1", "name": "test-vm", "folder_id": "folder-1"}],
    }


@pytest.fixture
def id_mapping():
    return {
        "zones": {"ru-central1-a": 10},
        "folders": {"folder-1": 20},
    }


@pytest.fixture
def batch_stats():
    return {
        "created": 1,
        "updated": 0,
        "skipped": 0,
        "deleted": 0,
        "errors": 0,
    }


class TestSyncEngineInit:
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_creates_clients(self, mock_yc_cls, mock_nb_cls, config):
        engine = SyncEngine(config)

        mock_yc_cls.assert_called_once()
        call_kwargs = mock_yc_cls.call_args.kwargs
        assert "token_provider" in call_kwargs
        assert call_kwargs["token_provider"].get_token() == "test-yc-token"
        mock_nb_cls.assert_called_once_with(
            url="https://netbox.test",
            token="test-nb-token",
            dry_run=False,
        )
        assert engine.config is config

    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_passes_dry_run(self, mock_yc_cls, mock_nb_cls):
        cfg = Config(
            yc_token="t", netbox_url="u", netbox_token="n", dry_run=True
        )
        SyncEngine(cfg)
        mock_nb_cls.assert_called_once_with(url="u", token="n", dry_run=True)

    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_uses_sa_key_file_when_configured(self, mock_yc_cls, mock_nb_cls, tmp_path):
        import json

        sa_key = {
            "id": "key-id",
            "service_account_id": "sa-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        }
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(sa_key))

        cfg = Config(
            yc_token="", netbox_url="u", netbox_token="n",
            yc_sa_key_file=str(key_file),
        )
        SyncEngine(cfg)

        call_kwargs = mock_yc_cls.call_args.kwargs
        from infraverse.providers.yc_auth import ServiceAccountKeyProvider
        assert isinstance(call_kwargs["token_provider"], ServiceAccountKeyProvider)

    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_yc_only_provider_by_default(self, mock_yc_cls, mock_nb_cls, config):
        engine = SyncEngine(config)
        assert len(engine._providers) == 1
        assert engine._providers[0][1] is YC_PROFILE

    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_adds_vcloud_when_configured(self, mock_yc_cls, mock_nb_cls):
        from infraverse.sync.provider_profile import VCLOUD_PROFILE

        cfg = Config(
            yc_token="t", netbox_url="u", netbox_token="n",
            vcd_url="https://vcd.test", vcd_user="admin", vcd_password="pass",
        )
        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            engine = SyncEngine(cfg)

        assert len(engine._providers) == 2
        assert engine._providers[1][1] is VCLOUD_PROFILE


class TestSyncEngineRunBatch:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_batch_sync_flow(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, yc_data, id_mapping, batch_stats,
    ):
        mock_yc = mock_yc_cls.return_value
        mock_nb = mock_nb_cls.return_value
        mock_yc.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        result = engine.run(use_batch=True, cleanup=True)

        mock_yc.fetch_all_data.assert_called_once()
        mock_nb.ensure_sync_tag.assert_called_once()
        mock_infra.assert_called_once_with(
            yc_data, mock_nb, cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data, mock_nb, id_mapping,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        assert result == {"yandex_cloud": batch_stats}

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_batch_no_cleanup(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, yc_data, id_mapping, batch_stats,
    ):
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        engine.run(use_batch=True, cleanup=False)

        mock_infra.assert_called_once_with(
            yc_data, mock_nb_cls.return_value,
            cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data, mock_nb_cls.return_value, id_mapping,
            cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )


class TestSyncEngineRunStandard:
    @patch("infraverse.sync.engine.sync_vms")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_standard_sync_flow(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_vms,
        config, yc_data, id_mapping,
    ):
        mock_yc = mock_yc_cls.return_value
        mock_nb = mock_nb_cls.return_value
        mock_yc.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_vms.return_value = {"created": 1, "updated": 0, "skipped": 0, "errors": 0}

        engine = SyncEngine(config)
        result = engine.run(use_batch=False, cleanup=True)

        mock_vms.assert_called_once_with(
            yc_data, mock_nb, id_mapping,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        assert result == {"yandex_cloud": {"created": 1, "updated": 0, "skipped": 0, "errors": 0}}

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_vms")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_standard_does_not_call_batch(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_vms, mock_batch,
        config, yc_data, id_mapping,
    ):
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping

        engine = SyncEngine(config)
        engine.run(use_batch=False)

        mock_batch.assert_not_called()


class TestSyncEngineFetchErrors:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_skips_cleanup_on_fetch_errors(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, id_mapping, batch_stats,
    ):
        yc_data_with_errors = {
            "zones": [{"id": "ru-central1-a", "name": "ru-central1-a"}],
            "clouds": [{"id": "cloud-1", "name": "my-cloud"}],
            "folders": [{"id": "folder-1", "name": "default", "cloud_name": "my-cloud"}],
            "vpcs": [],
            "subnets": [],
            "vms": [],
            "_has_fetch_errors": True,
        }
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data_with_errors
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        engine.run(use_batch=True, cleanup=True)

        mock_infra.assert_called_once_with(
            yc_data_with_errors, mock_nb_cls.return_value,
            cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data_with_errors, mock_nb_cls.return_value, id_mapping,
            cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_allows_cleanup_without_fetch_errors(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, yc_data, id_mapping, batch_stats,
    ):
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        engine.run(use_batch=True, cleanup=True)

        mock_infra.assert_called_once_with(
            yc_data, mock_nb_cls.return_value,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )


class TestSyncEngineDefaults:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_defaults_to_batch_with_cleanup(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, yc_data, id_mapping, batch_stats,
    ):
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        engine.run()

        mock_infra.assert_called_once_with(
            yc_data, mock_nb_cls.return_value,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data, mock_nb_cls.return_value, id_mapping,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )


class TestSyncEngineMultiProvider:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_returns_keyed_stats(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, yc_data, id_mapping, batch_stats,
    ):
        mock_yc_cls.return_value.fetch_all_data.return_value = yc_data
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        result = engine.run()

        assert "yandex_cloud" in result
        assert result["yandex_cloud"] == batch_stats

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    @patch("infraverse.sync.engine.NetBoxClient")
    @patch("infraverse.sync.engine.YandexCloudClient")
    def test_provider_failure_isolated(
        self, mock_yc_cls, mock_nb_cls, mock_infra, mock_batch,
        config, id_mapping, batch_stats,
    ):
        """If YC fetch fails, the error is captured but engine doesn't crash."""
        mock_yc_cls.return_value.fetch_all_data.side_effect = RuntimeError("API down")
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(config)
        result = engine.run()

        assert "yandex_cloud" in result
        assert result["yandex_cloud"]["error"] == "sync failed"
