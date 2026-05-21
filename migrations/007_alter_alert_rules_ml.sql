-- Migration: 007_alter_alert_rules_ml
-- Description: Add ML alerting fields to alert_rules table (Phase 3, issue #23).
--
-- alert_mode controls which evaluation strategy fires the alert:
--   'static' — existing threshold-based evaluation only (default, backwards-compatible)
--   'ml'     — fires when anomaly score > ml_score_threshold; falls back to static if no model
--   'both'   — either static OR ml breach fires the alert
--
-- ml_score_threshold is only used when alert_mode is 'ml' or 'both'.
-- Default 0.7 means the model must be 70% confident the point is anomalous.

ALTER TABLE maestro.alert_rules ADD COLUMN IF NOT EXISTS alert_mode LowCardinality(String) DEFAULT 'static';
ALTER TABLE maestro.alert_rules ADD COLUMN IF NOT EXISTS ml_score_threshold Float64 DEFAULT 0.7;
