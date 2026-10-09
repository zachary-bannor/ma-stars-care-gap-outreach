"""Tests for the Layer 6 safety-critical pure functions in worklist_sql.

The worklist's lead decision is persisted from the ai_decide VARIANT, so the
parser and the fixed-questions builder are pinned here:

  - parse_decision: turns the raw ai_decide response (a JSON string or a dict)
    into the lead/bundle choice, confidence and probabilities written to the
    worklist. It must be defensive: a malformed or error response yields Nones
    and the error, never an exception.
  - build_questions / questions_json: the FIXED decision schema ai_decide
    requires (a literal). It must always carry all five measures and the two
    bundle options, and serialize to valid JSON.
  - _sql_str / build_select_sql: the literal escaping and the overall SQL shape
    that the build depends on (balanced quotes and parentheses, the fixed
    questions passed as a literal, the fallback and bundle logic present).

Runs with pytest, or directly: `python3 tests/test_worklist_sql.py`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "06_lakebase_worklist"))

import worklist_sql


# --- parse_decision ---------------------------------------------------------

REAL = ('{"error_message":null,"metadata":{"version":"1.0"},"response":{"answers":{'
        '"bundle_second":{"choice":"single","confidence":0.35,'
        '"probabilities":{"bundle":0.32,"single":0.68},"type":"choice"},'
        '"lead_measure":{"choice":"MAD","confidence":0.99,'
        '"probabilities":{"CBP":0,"COL":0,"MAD":1},"type":"choice"}}}}')


def test_parse_real_response():
    p = worklist_sql.parse_decision(REAL)
    assert p["lead_measure"] == "MAD"
    assert p["lead_confidence"] == 0.99
    assert p["lead_probabilities"] == {"CBP": 0, "COL": 0, "MAD": 1}
    assert p["bundle_decision"] == "single"
    assert p["bundle_confidence"] == 0.35
    assert p["error"] is None


def test_parse_accepts_dict():
    p = worklist_sql.parse_decision(json.loads(REAL))
    assert p["lead_measure"] == "MAD" and p["bundle_decision"] == "single"


def test_parse_unparseable_is_safe():
    p = worklist_sql.parse_decision("not json at all")
    assert p["error"] == "unparseable ai_decide response"
    assert p["lead_measure"] is None and p["lead_probabilities"] is None


def test_parse_empty_and_none_are_safe():
    for raw in ("{}", None, "", "[1,2,3]"):
        p = worklist_sql.parse_decision(raw)
        assert p["lead_measure"] is None
        assert p["bundle_decision"] is None


def test_parse_surfaces_error_message():
    p = worklist_sql.parse_decision('{"error_message":"model refused","response":{}}')
    assert p["error"] == "model refused"
    assert p["lead_measure"] is None


# --- build_questions / questions_json ---------------------------------------

def test_questions_fixed_schema():
    q = worklist_sql.build_questions()
    assert set(q) == {"lead_measure", "bundle_second"}
    assert q["lead_measure"]["type"] == "choice"
    assert set(q["lead_measure"]["criteria"]) == {"EED", "GSD", "CBP", "COL", "MAD"}
    assert set(q["bundle_second"]["criteria"]) == {"bundle", "single"}


def test_questions_json_is_valid_and_literal():
    s = worklist_sql.questions_json()
    reparsed = json.loads(s)  # must be valid JSON
    assert reparsed == worklist_sql.build_questions()


def test_mad_criteria_flags_triple_weight():
    # The triple-weighting is the whole reason MAD often leads; it must be told.
    assert "triple" in worklist_sql.MEASURE_CRITERIA["MAD"].lower()


# --- _sql_str / build_select_sql --------------------------------------------

def test_sql_str_escapes_quotes():
    assert worklist_sql._sql_str("a'b") == "'a''b'"
    assert worklist_sql._sql_str("plain") == "'plain'"


def test_build_select_sql_shape():
    sql = worklist_sql.build_select_sql("cat", "H1234", 500)
    assert sql.count("(") == sql.count(")"), "unbalanced parentheses"
    assert sql.count("'") % 2 == 0, "unbalanced string literals"
    # fixed questions passed as a literal (not a column reference)
    assert "ai_decide(d.state," in sql
    assert "cat.gold.gap_scores" in sql and "cat.silver.members" in sql
    assert "WHERE g.contract_id = 'H1234'" in sql
    assert "LIMIT 500" in sql
    # the honesty + fallback + bundle machinery is present
    assert "lead_fallback_applied" in sql and "lead_measure_model" in sql
    assert "MIN_BY(m.measure_id" in sql
    # only coordinator-entitled columns leave the lakehouse: no PHI columns
    for banned in ("birth_date", "clinical", "dual_eligible", ".sex"):
        assert banned not in sql, f"PHI column leaked into worklist: {banned}"


def test_create_table_wrapper():
    ct = worklist_sql.build_create_table_sql("cat", "H1234", 500)
    assert ct.startswith("CREATE OR REPLACE TABLE cat.ops.member_worklist AS")


def test_segment_key_matches_layer5():
    assert worklist_sql.segment_key("MAD", "digital", "longtime") == "MAD|digital|longtime"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
