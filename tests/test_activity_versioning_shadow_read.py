"""Replacement contract for the retired executable shadow-read path."""

import importlib


shadow_reads = importlib.import_module("app.versioning.shadow_reads")


def test_shadow_read_module_is_historical_log_reader_only():
    assert hasattr(shadow_reads, "_read_versioned_shadow_read_events")
    assert not hasattr(shadow_reads, "maybe_run_versioned_resolver_shadow_read")
    assert not hasattr(shadow_reads, "is_versioned_resolver_shadow_read_enabled")
