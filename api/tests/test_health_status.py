"""
The server state: one rule for the dashboard and the alert screen.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.health_status import (
    Readings,
    health_headline,
    health_state,
    installed_services,
)

CALM = Readings(cpu=10.0, memory=40.0, disk=50.0)


class TestHealthState:
    def test_calm_server_is_ok(self):
        assert health_state("online", CALM, False, []) == "ok"

    def test_no_metrics_on_a_live_server_is_no_data_not_critical(self):
        assert health_state("online", Readings(None, None, None), False, []) == "quiet"

    def test_offline_server_is_critical(self):
        assert health_state("offline", Readings(None, None, None), False, []) == "critical"

    @pytest.mark.parametrize(
        "readings",
        [Readings(80.0, 40.0, 50.0), Readings(10.0, 90.0, 50.0), Readings(10.0, 40.0, 95.0)],
    )
    def test_critical_limits(self, readings):
        assert health_state("online", readings, False, []) == "critical"

    @pytest.mark.parametrize(
        "readings",
        [Readings(68.0, 40.0, 50.0), Readings(10.0, 76.0, 50.0), Readings(10.0, 40.0, 80.0)],
    )
    def test_attention_limits(self, readings):
        assert health_state("online", readings, False, []) == "attention"

    def test_a_missing_metric_does_not_hide_the_others(self):
        assert health_state("online", Readings(None, None, 96.0), False, []) == "critical"

    def test_a_critical_rule_firing_makes_a_calm_server_critical(self):
        assert health_state("online", CALM, False, ["critical"]) == "critical"

    def test_a_warning_rule_firing_makes_a_calm_server_attention(self):
        assert health_state("online", CALM, False, ["warning"]) == "attention"

    def test_memory_trending_to_the_limit_is_attention(self):
        assert health_state("online", CALM, True, []) == "attention"

    def test_limits_come_from_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "health_cpu_critical_percent", 50.0)

        assert health_state("online", Readings(55.0, 40.0, 50.0), False, []) == "critical"


class TestHeadline:
    def test_offline_wins(self):
        assert health_headline("offline", CALM, None, None, 0).code == "offline"

    def test_no_data(self):
        assert health_headline("online", Readings(None, None, None), None, None, 0).code == "no_data"

    def test_critical_metric_carries_its_rounded_value(self):
        headline = health_headline("online", Readings(83.67, 40.0, 50.0), None, None, 0)

        assert headline.code == "cpu_critical"
        assert headline.params == {"value": 83.7}

    def test_firing_rules_explain_a_calm_looking_server(self):
        headline = health_headline("online", CALM, None, None, 2)

        assert headline.code == "alerts_firing"
        assert headline.params == {"count": 2}

    def test_memory_projection(self):
        headline = health_headline("online", CALM, None, 3, 0)

        assert headline.code == "memory_rising"
        assert headline.params == {"threshold": 90, "hours": 3}

    def test_small_rise_over_the_average_is_not_news(self):
        assert health_headline("online", Readings(12.0, 40.0, 50.0), 10.0, None, 0).code == "within_expected"

    def test_big_rise_over_the_average(self):
        headline = health_headline("online", Readings(40.0, 40.0, 50.0), 10.0, None, 0)

        assert headline.code == "cpu_above_average"
        assert headline.params == {"delta": 30}


class TestInstalledServices:
    def test_lists_only_what_the_agent_can_vouch_for(self):
        inventory = [
            {"name": "OS", "version": "Debian 13", "status": "n/a"},
            {"name": "PHP", "version": "8.4.27", "status": "n/a"},
            {"name": "Nginx", "version": "not found", "status": "n/a"},
            {"name": "PostgreSQL", "version": "16.10", "status": "inactive"},
            {"name": "Apache", "version": "2.4.69", "status": "active"},
            {"name": "Redis", "version": "7.0", "status": "failed"},
        ]

        assert installed_services(inventory) == [
            {"name": "Apache", "ok": True},
            {"name": "Redis", "ok": False},
        ]
