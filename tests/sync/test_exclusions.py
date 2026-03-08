"""Tests for monitoring exclusion matching logic."""

from infraverse.config_file import MonitoringExclusionRule
from infraverse.sync.exclusions import check_monitoring_exclusion


class TestCheckMonitoringExclusion:
    """Tests for check_monitoring_exclusion."""

    def test_no_rules_returns_not_exempt(self):
        exempt, reason = check_monitoring_exclusion("web-server", "active", [])
        assert exempt is False
        assert reason is None

    def test_name_pattern_match(self):
        rules = [MonitoringExclusionRule(name_pattern="cl1*", reason="cluster node")]
        exempt, reason = check_monitoring_exclusion("cl1abc123", "active", rules)
        assert exempt is True

    def test_name_pattern_no_match(self):
        rules = [MonitoringExclusionRule(name_pattern="cl1*", reason="cluster node")]
        exempt, reason = check_monitoring_exclusion("web-server", "active", rules)
        assert exempt is False
        assert reason is None

    def test_status_only_match(self):
        rules = [MonitoringExclusionRule(status="stopped", reason="VM is stopped")]
        exempt, reason = check_monitoring_exclusion("any-vm", "stopped", rules)
        assert exempt is True
        assert reason == "VM is stopped"

    def test_status_only_no_match(self):
        rules = [MonitoringExclusionRule(status="stopped", reason="VM is stopped")]
        exempt, reason = check_monitoring_exclusion("any-vm", "active", rules)
        assert exempt is False
        assert reason is None

    def test_both_fields_match(self):
        rules = [
            MonitoringExclusionRule(
                name_pattern="test-*",
                status="stopped",
                reason="stopped test VM",
            )
        ]
        exempt, reason = check_monitoring_exclusion("test-vm1", "stopped", rules)
        assert exempt is True
        assert reason == "stopped test VM"

    def test_both_fields_partial_match_fails(self):
        rules = [
            MonitoringExclusionRule(
                name_pattern="test-*",
                status="stopped",
                reason="stopped test VM",
            )
        ]
        exempt, reason = check_monitoring_exclusion("test-vm1", "active", rules)
        assert exempt is False
        assert reason is None

    def test_case_insensitive_name(self):
        rules = [MonitoringExclusionRule(name_pattern="CL1*", reason="cluster")]
        exempt, reason = check_monitoring_exclusion("cl1abc", "active", rules)
        assert exempt is True

    def test_case_insensitive_status(self):
        rules = [MonitoringExclusionRule(status="STOPPED", reason="stopped")]
        exempt, reason = check_monitoring_exclusion("any-vm", "stopped", rules)
        assert exempt is True

    def test_first_match_wins(self):
        rules = [
            MonitoringExclusionRule(name_pattern="web-*", reason="first rule"),
            MonitoringExclusionRule(name_pattern="web-*", reason="second rule"),
        ]
        exempt, reason = check_monitoring_exclusion("web-server", "active", rules)
        assert exempt is True
        assert reason == "first rule"

    def test_template_pattern(self):
        rules = [MonitoringExclusionRule(name_pattern="*-template", reason="template VM")]
        exempt, reason = check_monitoring_exclusion("alma-template", "active", rules)
        assert exempt is True
        assert reason == "template VM"

    def test_reason_returned(self):
        expected_reason = "Excluded: ephemeral CI runner"
        rules = [
            MonitoringExclusionRule(name_pattern="ci-*", reason=expected_reason)
        ]
        exempt, reason = check_monitoring_exclusion("ci-runner-42", "active", rules)
        assert exempt is True
        assert reason == expected_reason
