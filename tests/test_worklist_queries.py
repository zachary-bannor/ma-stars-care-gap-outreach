"""Unit tests for the coordinator worklist query/mapping helpers (Layer 8).

Pure-function tests, no network: they lock the SQL shape and the outcome -> status
mapping that both the app and the evidence script depend on. Run with:
    /opt/homebrew/bin/python3 -m pytest tests/test_worklist_queries.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "08_app"))

import worklist_queries as q  # noqa: E402


def test_worklist_select_joins_status_and_orders_by_rank():
    sql = q.worklist_select_sql()
    assert "ops.worklist w" in sql
    assert "LEFT JOIN ops.worklist_status s USING (member_id)" in sql
    assert "ORDER BY w.worklist_rank" in sql
    # no LIMIT by default: the serving table is already bounded upstream
    assert "LIMIT" not in sql
    # the list view selects only the light columns, never the heavy draft text
    for col in q.LIST_COLUMNS:
        assert f"w.{col}" in sql
    assert "w.draft_body" not in sql
    assert "w.lead_probabilities" not in sql


def test_worklist_select_limit_is_int_coerced():
    # a numeric string is coerced to a bare integer in the SQL
    assert "LIMIT 5" in q.worklist_select_sql(limit="5")
    # a malicious limit cannot inject: int() rejects it outright
    import pytest

    with pytest.raises(ValueError):
        q.worklist_select_sql(limit="5; DROP TABLE ops.worklist")


def test_member_detail_selects_full_columns_including_draft():
    sql = q.member_detail_sql()
    for col in q.WORKLIST_COLUMNS:
        assert col in sql
    assert "draft_body" in sql  # detail panel needs the draft the list view omits


def test_member_detail_is_parameterized():
    sql = q.member_detail_sql()
    assert "WHERE member_id = %s" in sql
    assert "ops.worklist" in sql


def test_insert_action_columns_and_params():
    sql = q.insert_action_sql()
    assert "INSERT INTO ops.coordinator_action" in sql
    for col in ("member_id", "measure", "action", "channel", "outcome", "notes", "acted_by"):
        assert col in sql
    assert sql.count("%s") == 7  # all seven values bound, nothing interpolated


def test_upsert_status_is_idempotent_on_member_id():
    sql = q.upsert_status_sql()
    assert "INSERT INTO ops.worklist_status" in sql
    assert "ON CONFLICT (member_id) DO UPDATE SET" in sql
    assert "status = EXCLUDED.status" in sql
    assert "updated_at = EXCLUDED.updated_at" in sql
    # updated_at is written server-side via now(), not bound as a parameter
    assert sql.count("%s") == 5


def test_derive_status_known_outcomes():
    assert q.derive_status("reached") == ("contacted", 7)
    assert q.derive_status("left_voicemail") == ("contacted", 3)
    assert q.derive_status("no_answer") == ("attempted", 2)
    assert q.derive_status("scheduled_appointment") == ("scheduled", None)
    assert q.derive_status("declined") == ("declined", None)
    assert q.derive_status("completed") == ("closed", None)


def test_derive_status_unknown_outcome_is_safe():
    status, days = q.derive_status("something_new")
    assert status == "contacted"
    assert days == 3


def test_every_outcome_has_a_mapping():
    for outcome in q.OUTCOMES:
        status, days = q.derive_status(outcome)
        assert isinstance(status, str) and status
        assert days is None or isinstance(days, int)


def test_default_channel_from_preferred():
    assert q.default_channel("digital") == "digital"
    assert q.default_channel("mail_phone") == "phone"
    assert q.default_channel(None) == "phone"  # safe fallback


def test_action_and_channel_vocabularies_nonempty():
    assert q.ACTIONS and all(isinstance(a, str) for a in q.ACTIONS)
    assert q.CHANNELS and all(isinstance(c, str) for c in q.CHANNELS)
