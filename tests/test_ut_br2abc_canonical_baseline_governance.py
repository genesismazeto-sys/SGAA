"""UT-BR2-ABC: discriminating probes for the consolidated baseline owner.

``tests/canonical_baseline_support.py`` replaced 46 frozen per-suite scalars
(message catalog 556/526, route inventory 127/128/20171 bytes/stale SHA, CSRF
77/78 rows) with one canonical ownership model.  Consolidation is only
legitimate if the single control is at least as discriminating as the copies it
retired, so every delegation used by the extraction suites is mutation-probed
here:

* one unauthorized catalog addition / removal / same-size rename,
* one deleted route / added route / changed rule-endpoint pairing,
* one removed CSRF row / added row / silently re-owned row.

All probes mutate in-memory copies only.  No production source, no artifact and
no operational data is touched.
"""
from __future__ import annotations

import copy

import pytest

from tests import canonical_baseline_support as governance


# ---------------------------------------------------------------------------
# Ledger arithmetic: the canonical totals are derived, never typed
# ---------------------------------------------------------------------------


def test_catalog_ledger_arithmetic_is_the_only_source_of_the_canonical_count():
    """The canonical total is the sum of named product deltas."""
    terms = dict(
        (term, delta) for term, delta in governance.CATALOG_LEDGER
    )
    assert len(terms) == len(governance.CATALOG_LEDGER), "ledger terms must be unique"
    assert governance.PARENT_CATALOG_COUNT == 548, (
        "UT-MX3's exact parent state is the ledger up to the UT-MX3 term"
    )
    assert governance.CANONICAL_CATALOG_COUNT == 582
    assert governance.CATALOG_LEDGER[governance.MX3_LEDGER_INDEX][1] == 6, (
        "the UT-MX3 StudentMatrixError ownership delta is exactly +6"
    )
    assert governance.CATALOG_LEDGER[-8][1] == 1, (
        "the TMA1 Turma-Matrix authority delta is exactly +1"
    )
    assert governance.CATALOG_LEDGER[-7][1] == 3 == len(
        governance.CR1_CLOUD_CREDENTIAL_RECOVERY_KEYS
    ), (
        "the CR1 cloud-credential recovery delta is exactly +3, one term per "
        "declared key"
    )
    assert governance.CATALOG_LEDGER[-6][1] == 22 == len(
        governance.REN1_REQUEST_EMAIL_KEYS
    ), (
        "the REN1 request e-mail notification delta is exactly +22, one term "
        "per declared key"
    )
    assert governance.CATALOG_LEDGER[-5][1] == (
        len(governance.PASSWORD_FOUNDATION_ADDED_KEYS)
        - len(governance.PASSWORD_FOUNDATION_RETIRED_KEYS)
    ) == 0
    assert governance.CATALOG_LEDGER[-4][1] == (
        len(governance.AR1_ACCESS_REPAIR_KEYS)
        - len(governance.AR1_ACCESS_REPAIR_RETIRED_KEYS)
    ) == 2, (
        "the AR1 Acesso repair delta is exactly +2: three additions against the "
        "retired raw-SQLite delete flash"
    )
    assert governance.CATALOG_LEDGER[-3][1] == (
        len(governance.RA1_ROOT_ADMIN_KEYS)
        - len(governance.RA1_ROOT_ADMIN_RETIRED_KEYS)
    ) == 5, (
        "the RA1 root-administrator delta is exactly +5: six additions "
        "against the retired single-purpose delete confirmation. The "
        "break-glass path itself is invisible in the product, so it "
        "contributes no catalogued message"
    )
    assert governance.CATALOG_LEDGER[-2][1] == (
        len(governance.CP1_CREDENTIAL_PENDING_KEYS)
        - len(governance.CP1_CREDENTIAL_PENDING_RETIRED_KEYS)
    ) == -4, (
        "the CP1 credential-pending delta is exactly -4: the retired global "
        "default-password switch takes its refusal flash and the three "
        "blank-password help texts that promised the shared default with it"
    )
    assert governance.CATALOG_LEDGER[-1][1] == (
        len(governance.UIB19_PHOTO_LABEL_KEYS)
        - len(governance.UIB19_PHOTO_LABEL_RETIRED_KEYS)
    ) == -1, (
        "the UI-B19 photo-label delta is exactly -1: the add-student 'Foto' "
        "row label was that literal's only consumer"
    )
    # Parent + every term from UT-MX3 onward reconstructs the canonical total.
    assert (
        governance.PARENT_CATALOG_COUNT
        + sum(
            delta
            for _t, delta in governance.CATALOG_LEDGER[governance.MX3_LEDGER_INDEX :]
        )
        == governance.CANONICAL_CATALOG_COUNT
    )


def test_derived_projections_agree_with_the_versioned_artifacts():
    """Every count the suites now delegate is read off the canonical artifacts."""
    assert governance.CANONICAL_ROUTE_ENTRY_COUNT == 131
    assert governance.CANONICAL_ROUTE_ENDPOINT_COUNT == 130
    assert governance.CANONICAL_ROUTE_RULE_COUNT == 130
    assert governance.CANONICAL_CSRF_ROW_COUNT == 78
    assert governance.CANONICAL_CSRF_PAGE_STATUS_COUNT == 68
    assert sum(governance.CANONICAL_CSRF_OWNER_PARTITIONS.values()) == 78

    # Both shadow snapshots are the same canonical inventory.
    off_rows = governance.load_csrf_snapshot(governance.CSRF_OFF_ARTIFACT)["rows"]
    on_rows = governance.load_csrf_snapshot(governance.CSRF_ON_ARTIFACT)["rows"]
    assert governance.csrf_row_identities(off_rows) == governance.csrf_row_identities(
        on_rows
    )


# ---------------------------------------------------------------------------
# A. Message catalog probes
# ---------------------------------------------------------------------------


def test_canonical_catalog_control_accepts_the_live_catalog():
    catalog = governance.canonical_message_catalog()
    governance.assert_catalog_matches_canonical_baseline(catalog, context="live")
    assert len(catalog) == governance.CANONICAL_CATALOG_COUNT


def test_catalog_control_rejects_one_unauthorized_addition():
    catalog = dict(governance.canonical_message_catalog())
    catalog["msg_ut_br2abc_unauthorized"] = {
        "default_text": "probe",
        "usages": [],
    }
    with pytest.raises(AssertionError) as captured:
        governance.assert_catalog_matches_canonical_baseline(catalog)
    assert f"got {governance.CANONICAL_CATALOG_COUNT + 1}" in str(captured.value)


def test_catalog_control_rejects_one_unauthorized_removal():
    catalog = dict(governance.canonical_message_catalog())
    victim = sorted(catalog)[0]
    del catalog[victim]
    with pytest.raises(AssertionError) as captured:
        governance.assert_catalog_matches_canonical_baseline(catalog)
    assert f"got {governance.CANONICAL_CATALOG_COUNT - 1}" in str(captured.value)


def test_catalog_control_rejects_a_same_size_key_rename():
    """The retired scalar counts could not see this; the key digest can."""
    catalog = dict(governance.canonical_message_catalog())
    victim = sorted(catalog)[0]
    catalog["msg_ut_br2abc_renamed"] = catalog.pop(victim)
    assert len(catalog) == governance.CANONICAL_CATALOG_COUNT
    with pytest.raises(AssertionError, match="renamed or swapped"):
        governance.assert_catalog_matches_canonical_baseline(catalog)


def test_catalog_parent_digest_still_governs_the_mx3_parent_state():
    catalog = governance.canonical_message_catalog()
    from tests.test_ut_mx3_matrix_validation_debt_closure import NEW_STUDENT_MATRIX_KEYS

    # Every post-MX3 addition has to come back off, not just MX3's own keys,
    # or the reconstructed "parent" would drift forward with each later term.
    parent_keys = (
governance.catalog_keys_before_password_foundation(
            governance.catalog_keys_before_access_repair(
                governance.catalog_keys_before_root_admin(
                    governance.catalog_keys_before_credential_pending(
                        governance.catalog_keys_before_photo_label(catalog)
                    )
                )
            )
        )
        - set(NEW_STUDENT_MATRIX_KEYS)
        - set(governance.TMA1_MATRIX_AUTHORITY_KEYS)
        - set(governance.CR1_CLOUD_CREDENTIAL_RECOVERY_KEYS)
        - set(governance.REN1_REQUEST_EMAIL_KEYS)
    )
    assert len(parent_keys) == governance.PARENT_CATALOG_COUNT
    assert (
        governance.catalog_keys_digest(parent_keys)
        == governance.PARENT_CATALOG_KEYS_SHA256
    )


# ---------------------------------------------------------------------------
# B. Route inventory probes
# ---------------------------------------------------------------------------


def test_route_control_accepts_the_live_url_map():
    rules = governance.assert_live_route_surface_matches_canonical_baseline(
        context="live"
    )
    assert len(rules) == governance.CANONICAL_ROUTE_ENTRY_COUNT


def test_route_control_rejects_a_deleted_business_route():
    data = copy.deepcopy(governance.load_route_inventory_baseline())
    victim = next(
        entry for entry in data["routes"] if entry["endpoint"] != "static"
    )
    data["routes"] = [entry for entry in data["routes"] if entry is not victim]
    with pytest.raises(AssertionError) as captured:
        governance.assert_route_inventory_artifact_is_canonical(data)
    assert f"got {governance.CANONICAL_ROUTE_ENTRY_COUNT - 1}" in str(captured.value)


def test_route_control_rejects_an_unauthorized_added_route():
    data = copy.deepcopy(governance.load_route_inventory_baseline())
    data["routes"].append(
        {
            "rule": "/admin/ut-br2abc-probe",
            "endpoint": "admin_ut_br2abc_probe",
            "methods": ["GET", "POST"],
        }
    )
    with pytest.raises(AssertionError) as captured:
        governance.assert_route_inventory_artifact_is_canonical(data)
    assert f"got {governance.CANONICAL_ROUTE_ENTRY_COUNT + 1}" in str(captured.value)


def test_route_control_rejects_a_changed_rule_endpoint_pairing():
    """Same route count, one re-pointed endpoint: the digest discriminates it."""
    data = copy.deepcopy(governance.load_route_inventory_baseline())
    victim = next(entry for entry in data["routes"] if entry["endpoint"] != "static")
    victim["endpoint"] = f"{victim['endpoint']}_reowned"
    assert len(data["routes"]) == governance.CANONICAL_ROUTE_ENTRY_COUNT
    with pytest.raises(AssertionError, match="canonical URL contract"):
        governance.assert_route_inventory_artifact_is_canonical(data)


def test_route_control_rejects_a_changed_method_pairing():
    data = copy.deepcopy(governance.load_route_inventory_baseline())
    victim = next(
        entry
        for entry in data["routes"]
        if entry["endpoint"] != "static" and entry["methods"] == ["GET"]
    )
    victim["methods"] = ["GET", "POST"]
    with pytest.raises(AssertionError, match="canonical URL contract"):
        governance.assert_route_inventory_artifact_is_canonical(data)


# ---------------------------------------------------------------------------
# C. CSRF snapshot probes
# ---------------------------------------------------------------------------


def _canonical_snapshot() -> dict:
    return copy.deepcopy(governance.load_csrf_snapshot(governance.CSRF_OFF_ARTIFACT))


def test_csrf_control_accepts_both_canonical_snapshots():
    for artifact in governance.CANONICAL_CSRF_ARTIFACTS:
        snapshot = governance.load_csrf_snapshot(artifact)
        rows = governance.assert_csrf_snapshot_matches_canonical_baseline(
            snapshot, context=artifact.name
        )
        governance.assert_csrf_owner_partitions_reconstruct_canonical(
            rows, context=artifact.name
        )


def test_csrf_control_rejects_one_removed_protected_row():
    snapshot = _canonical_snapshot()
    victim = snapshot["rows"].pop(0)
    assert victim["route"]
    with pytest.raises(AssertionError) as captured:
        governance.assert_csrf_snapshot_matches_canonical_baseline(snapshot)
    assert f"got {governance.CANONICAL_CSRF_ROW_COUNT - 1}" in str(captured.value)


def test_csrf_control_rejects_one_undeclared_added_row():
    snapshot = _canonical_snapshot()
    template = copy.deepcopy(snapshot["rows"][0])
    template["route"] = "/admin/ut-br2abc-probe"
    template["view_function"] = "main.admin_ut_br2abc_probe"
    snapshot["rows"].append(template)
    with pytest.raises(AssertionError) as captured:
        governance.assert_csrf_snapshot_matches_canonical_baseline(snapshot)
    assert f"got {governance.CANONICAL_CSRF_ROW_COUNT + 1}" in str(captured.value)


def test_csrf_control_rejects_a_silently_reowned_row():
    """Row count unchanged, owner moved: the identity digest discriminates it."""
    snapshot = _canonical_snapshot()
    snapshot["rows"][0]["view_function"] = "main.smuggled_owner"
    assert len(snapshot["rows"]) == governance.CANONICAL_CSRF_ROW_COUNT
    with pytest.raises(AssertionError, match="canonical snapshot"):
        governance.assert_csrf_snapshot_matches_canonical_baseline(snapshot)


def test_csrf_control_rejects_a_dropped_page_status():
    snapshot = _canonical_snapshot()
    snapshot["summary"]["page_statuses"].pop()
    with pytest.raises(AssertionError, match="page statuses"):
        governance.assert_csrf_snapshot_matches_canonical_baseline(snapshot)


def test_csrf_owner_partition_control_rejects_a_cross_owner_move():
    """Moving one row between named owners breaks the partition ledger."""
    snapshot = _canonical_snapshot()
    victim = next(
        row
        for row in snapshot["rows"]
        if row["view_function"].startswith("app.views.admin.arquivos.")
    )
    victim["view_function"] = "main." + victim["view_function"].rsplit(".", 1)[1]
    with pytest.raises(AssertionError, match="owner partition sizes diverged"):
        governance.assert_csrf_owner_partitions_reconstruct_canonical(snapshot["rows"])


def test_csrf_owner_partitions_stay_disjoint_and_reconstruct_the_snapshot():
    rows = governance.load_csrf_snapshot(governance.CSRF_OFF_ARTIFACT)["rows"]
    partitions = governance.assert_csrf_owner_partitions_reconstruct_canonical(rows)
    assert set(partitions) == set(governance.CANONICAL_CSRF_OWNER_PARTITIONS)
    seen: set = set()
    for members in partitions.values():
        assert not (seen & members)
        seen |= members
    assert seen == governance.CANONICAL_CSRF_ROW_IDENTITIES
    assert len(seen) == governance.CANONICAL_CSRF_ROW_COUNT


def test_canonical_csrf_rows_remain_a_subset_of_the_live_mutating_surface():
    """No canonical protected row may vanish from the live URL map."""
    import main

    live = {
        (rule.rule, method)
        for rule in main.app.url_map.iter_rules()
        for method in (set(rule.methods or ()) & governance.MUTATING_METHODS)
    }
    snapshot = {
        (route, method)
        for route, method, _owner in governance.CANONICAL_CSRF_ROW_IDENTITIES
    }
    assert snapshot <= live, (
        "every canonical CSRF row must still be a live mutating route; "
        f"missing={sorted(snapshot - live)}"
    )
