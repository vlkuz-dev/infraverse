"""Tests for infraverse.sync.engine module."""

from unittest.mock import MagicMock, patch

from infraverse.sync.engine import SyncEngine
from infraverse.sync.provider_profile import YC_PROFILE, VCLOUD_PROFILE


def _make_mock_netbox():
    nb = MagicMock()
    nb.ensure_sync_tag.return_value = 1
    return nb


def _make_mock_yc_client(data=None):
    client = MagicMock()
    client.fetch_all_data.return_value = data or {
        "zones": [{"id": "ru-central1-a", "name": "ru-central1-a"}],
        "clouds": [{"id": "cloud-1", "name": "my-cloud"}],
        "folders": [{"id": "folder-1", "name": "default", "cloud_name": "my-cloud"}],
        "vpcs": [],
        "subnets": [],
        "vms": [{"id": "vm-1", "name": "test-vm", "folder_id": "folder-1"}],
    }
    return client


class TestSyncEngineInit:
    def test_stores_netbox_and_providers(self):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        providers = [(yc, YC_PROFILE)]

        engine = SyncEngine(nb, providers, dry_run=True)

        assert engine.nb is nb
        assert engine._providers == providers
        assert engine.dry_run is True

    def test_empty_providers(self):
        nb = _make_mock_netbox()
        engine = SyncEngine(nb, [], dry_run=False)

        assert engine._providers == []
        assert engine.dry_run is False

    def test_multiple_providers(self):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        vcd = MagicMock()
        providers = [(yc, YC_PROFILE), (vcd, VCLOUD_PROFILE)]

        engine = SyncEngine(nb, providers)

        assert len(engine._providers) == 2
        assert engine._providers[0][1] is YC_PROFILE
        assert engine._providers[1][1] is VCLOUD_PROFILE


class TestSyncEngineRunBatch:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_batch_sync_flow(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        yc_data = yc.fetch_all_data.return_value
        id_mapping = {"zones": {"ru-central1-a": 10}, "folders": {"folder-1": 20}}
        batch_stats = {"created": 1, "updated": 0, "skipped": 0, "deleted": 0, "errors": 0}
        mock_infra.return_value = id_mapping
        mock_batch.return_value = batch_stats

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        result = engine.run(use_batch=True, cleanup=True)

        yc.fetch_all_data.assert_called_once()
        nb.ensure_sync_tag.assert_called_once()
        mock_infra.assert_called_once_with(
            yc_data, nb, cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data, nb, id_mapping,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        assert result == {"yandex_cloud": batch_stats}

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_batch_no_cleanup(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        yc_data = yc.fetch_all_data.return_value
        id_mapping = {"zones": {}, "folders": {}}
        mock_infra.return_value = id_mapping
        mock_batch.return_value = {}

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        engine.run(use_batch=True, cleanup=False)

        mock_infra.assert_called_once_with(
            yc_data, nb, cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )
        mock_batch.assert_called_once_with(
            yc_data, nb, id_mapping,
            cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )


class TestSyncEngineRunStandard:
    @patch("infraverse.sync.engine.sync_vms")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_standard_sync_flow(self, mock_infra, mock_vms):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        yc_data = yc.fetch_all_data.return_value
        id_mapping = {"zones": {"ru-central1-a": 10}, "folders": {"folder-1": 20}}
        vm_stats = {"created": 1, "updated": 0, "skipped": 0, "errors": 0}
        mock_infra.return_value = id_mapping
        mock_vms.return_value = vm_stats

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        result = engine.run(use_batch=False, cleanup=True)

        mock_vms.assert_called_once_with(
            yc_data, nb, id_mapping,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )
        assert result == {"yandex_cloud": vm_stats}

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_vms")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_standard_does_not_call_batch(self, mock_infra, mock_vms, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        mock_infra.return_value = {}

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        engine.run(use_batch=False)

        mock_batch.assert_not_called()


class TestSyncEngineFetchErrors:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_skips_cleanup_on_fetch_errors(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        data_with_errors = {
            "zones": [], "clouds": [], "folders": [],
            "vpcs": [], "subnets": [], "vms": [],
            "_has_fetch_errors": True,
        }
        yc = _make_mock_yc_client(data_with_errors)
        mock_infra.return_value = {}
        mock_batch.return_value = {}

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        engine.run(use_batch=True, cleanup=True)

        mock_infra.assert_called_once_with(
            data_with_errors, nb, cleanup_orphaned=False, provider_profile=YC_PROFILE,
        )

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_allows_cleanup_without_fetch_errors(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        mock_infra.return_value = {}
        mock_batch.return_value = {}

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        engine.run(use_batch=True, cleanup=True)

        mock_infra.assert_called_once_with(
            yc.fetch_all_data.return_value, nb,
            cleanup_orphaned=True, provider_profile=YC_PROFILE,
        )


class TestSyncEngineDefaults:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_defaults_to_batch_with_cleanup(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        mock_infra.return_value = {}
        mock_batch.return_value = {}

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        engine.run()

        mock_batch.assert_called_once()
        mock_infra.assert_called_once()


class TestSyncEngineMultiProvider:
    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_returns_keyed_stats(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        batch_stats = {"created": 1}
        mock_infra.return_value = {}
        mock_batch.return_value = batch_stats

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        result = engine.run()

        assert "yandex_cloud" in result
        assert result["yandex_cloud"] == batch_stats

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_provider_failure_isolated(self, mock_infra, mock_batch):
        """If YC fetch fails, the error is captured but engine doesn't crash."""
        nb = _make_mock_netbox()
        yc = MagicMock()
        yc.fetch_all_data.side_effect = RuntimeError("API down")

        engine = SyncEngine(nb, [(yc, YC_PROFILE)])
        result = engine.run()

        assert "yandex_cloud" in result
        assert result["yandex_cloud"]["error"] == "sync failed"

    @patch("infraverse.sync.engine.sync_vms_optimized")
    @patch("infraverse.sync.engine.sync_infrastructure")
    def test_two_providers_both_synced(self, mock_infra, mock_batch):
        nb = _make_mock_netbox()
        yc = _make_mock_yc_client()
        vcd = _make_mock_yc_client()  # reuse helper, different profile
        mock_infra.return_value = {}
        mock_batch.return_value = {"created": 0}

        engine = SyncEngine(nb, [(yc, YC_PROFILE), (vcd, VCLOUD_PROFILE)])
        result = engine.run()

        assert "yandex_cloud" in result
        assert "vcloud" in result
        assert mock_batch.call_count == 2

    def test_empty_providers_returns_empty_stats(self):
        nb = _make_mock_netbox()
        engine = SyncEngine(nb, [])
        result = engine.run()

        assert result == {}
