"""Unit tests for the Layer 7 Genie space spec (pure, off-cluster).

Pin the governed, certified-first posture of the space content: the prefer-certified
directive is present, the trap is named as off-limits, no curated query reads the
scratch trap, the five measures and the diabetes synonym are covered, and the
benchmark fixed values match the Layer 1/2/4 reproduction target.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "07_genie_space"))
import space_spec as s

CAT = "zrb_fe_bar_uhc_stars_catalog"
MEASURES = {"EED", "GSD", "CBP", "COL", "MAD"}


def test_tables_are_all_governed():
    for fqn in s.tables(CAT).values():
        assert fqn.startswith(f"{CAT}.governance."), fqn


def test_metric_view_and_trap_locations():
    assert s.metric_view(CAT) == f"{CAT}.governance.star_value_metrics"
    assert s.scratch_trap(CAT).startswith(f"{CAT}.analytics_sandbox.")


def test_instructions_prefer_certified_and_name_the_trap():
    text = " ".join(s.instructions(CAT)).lower()
    assert "certified" in text
    assert "prefer certified" in text
    assert "analytics_sandbox" in text  # trap named as off-limits
    assert "star_value_metrics" in text  # authoritative source named


def test_instructions_cover_governance_posture():
    text = " ".join(s.instructions(CAT)).lower()
    assert "sha-256" in text or "pseudonym" in text
    assert "triple-weighted" in text


def test_example_sqls_never_read_the_trap():
    for ex in s.example_sqls(CAT):
        assert "analytics_sandbox" not in ex["sql"], ex["question"]


def test_example_sqls_cover_the_seed_questions():
    qs = " ".join(e["question"].lower() for e in s.example_sqls(CAT))
    assert "diabetes" in qs
    assert "cbp" in qs and "h1234" in qs
    assert "worklist" in qs


def test_diabetes_synonym_is_eed_gsd_mad():
    f = {x["name"]: x["expr"] for x in s.FILTER_SNIPPETS}
    assert f["open diabetes gaps"] == "measure_id IN ('EED','GSD','MAD')"


def test_filter_snippets_cover_all_measures():
    exprs = " ".join(x["expr"] for x in s.FILTER_SNIPPETS)
    for m in MEASURES:
        assert m in exprs, m


def test_measure_snippets_use_the_metric_view():
    mv = s.metric_view(CAT)
    srcs = {m["source"] for m in s.measure_snippets(CAT)}
    assert mv in srcs


def test_join_specs_reference_the_dimensions():
    joins = s.join_specs(CAT)
    rights = " ".join(j["right"] for j in joins)
    assert "member_dim" in rights
    assert "measure_weights" in rights


def test_benchmark_reproduction_target():
    bms = s.benchmarks(CAT)
    total = next(b for b in bms if b.get("expect_fixed") == 67202)
    assert "open_gap_count" in total["sql"] or "open" in total["sql"].lower()
    by_measure = next(b for b in bms if isinstance(b.get("expect_fixed"), dict))
    assert by_measure["expect_fixed"] == {"EED": 9827, "GSD": 5835, "CBP": 25874,
                                          "COL": 19313, "MAD": 6353}
    assert sum(by_measure["expect_fixed"].values()) == 67202


def test_benchmarks_include_masking_and_contrast_checks():
    kinds = {b.get("expect") for b in s.benchmarks(CAT)}
    assert "sha256_hex" in kinds       # masking proof
    assert "certified_total" in kinds  # trap-contrast anchor


def test_serialized_space_shape():
    p = s.serialized_space(CAT)
    assert p["version"] == 2
    # confirmed v2 shape: sample questions under config, each {id, question:[...]}
    sq = p["config"]["sample_questions"]
    assert len(sq) >= 5
    for q in sq:
        assert len(q["id"]) == 32 and q["id"].islower()
        assert isinstance(q["question"], list) and q["question"]
    # data sources include every governed table + metric view + the trap, by identifier
    idents = [t["identifier"] for t in p["data_sources"]["tables"]]
    for fqn in s.tables(CAT).values():
        assert fqn in idents
    assert s.metric_view(CAT) in idents
    assert s.scratch_trap(CAT) in idents


def test_serialized_space_instructions_are_arrays():
    instr = s.serialized_space(CAT)["instructions"]
    for ti in instr["text_instructions"]:
        assert len(ti["id"]) == 32
        assert isinstance(ti["content"], list) and all(isinstance(x, str) for x in ti["content"])
    for ex in instr["example_question_sqls"]:
        assert isinstance(ex["question"], list) and isinstance(ex["sql"], list)
    for grp in ("measures", "filters"):
        for sn in instr["sql_snippets"][grp]:
            assert isinstance(sn["display_name"], str)
            assert isinstance(sn["sql"], list)


def test_serialized_space_ids_are_unique():
    p = s.serialized_space(CAT)
    ids = [q["id"] for q in p["config"]["sample_questions"]]
    instr = p["instructions"]
    ids += [x["id"] for x in instr["text_instructions"]]
    ids += [x["id"] for x in instr["example_question_sqls"]]
    ids += [x["id"] for x in instr["sql_snippets"]["measures"]]
    ids += [x["id"] for x in instr["sql_snippets"]["filters"]]
    assert len(ids) == len(set(ids)), "element ids must be unique across the space"


def test_join_hint_instruction_present():
    # joins are carried into instructions as a text block (typed join_specs omitted)
    texts = [" ".join(ti["content"]) for ti in s.serialized_space(CAT)["instructions"]["text_instructions"]]
    assert any("foreign keys" in t.lower() or "join" in t.lower() for t in texts)
