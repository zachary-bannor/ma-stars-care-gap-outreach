"""Layer 7 / Genie space specification: the curated semantic content.

A pure module (no Spark, no SDK) so the content is testable off-cluster
(tests/test_space_spec.py), the same way Layer 5 kept the prompt in prompt_spec.py
and Layer 6 kept the decision SQL in worklist_sql.py.

Everything the VP-Stars Genie space needs lives here as data: the governed data
sources, the general instructions (persona, governance posture, the prefer-certified
directive, the domain glossary and synonyms), the sample starter questions, the
curated example question->SQL pairs, the join specs, the reusable measure/filter
snippets, and the benchmark set. 03_create_space.py maps this spec onto the live
serialized_space schema; 04_benchmark.py runs the examples + benchmarks.

The space serves the Layer 3 `zrb_stars_quality_analysts` persona. Genie executes
every query under the caller's Unity Catalog identity, so member_id comes back as a
SHA-256 pseudonym and the contract row filter applies with nothing new to trust.
"""

# ---------------------------------------------------------------------------
# Governed data sources (all in the governance consumption zone, plus the one
# uncertified trap). The space reads the governed star schema only; the trap is
# included deliberately so OntoRank's preference for the certified metric view is
# a real, provable outcome and not a setup where the wrong source was never offered.
# ---------------------------------------------------------------------------

def tables(catalog):
    """Governed tables + the certified metric view the space is built on."""
    g = f"{catalog}.governance"
    return {
        "member_dim": f"{g}.member_dim",            # member entity dimension (PK member_id)
        "measure_weights": f"{g}.measure_weights",  # measure dimension (PK measure_id)
        "gap_scores": f"{g}.gap_scores",            # scored open gaps + EV (fact)
        "worklist": f"{g}.worklist",                # active prioritized queue + ai_decide (fact)
        "care_gaps": f"{g}.care_gaps",              # full gap inventory, all statuses (fact)
        "outreach_drafts": f"{g}.outreach_drafts",  # GenAI drafts, human-review (fact)
    }


def metric_view(catalog):
    return f"{catalog}.governance.star_value_metrics"


def scratch_trap(catalog):
    return f"{catalog}.analytics_sandbox.star_value_rollup"


# ---------------------------------------------------------------------------
# General instructions. Ordered: purpose, governance posture, the prefer-certified
# directive (the OntoRank-aligned steer Zach asked for), domain glossary, synonyms,
# defaults.
# ---------------------------------------------------------------------------

def instructions(catalog):
    mv = metric_view(catalog)
    trap = scratch_trap(catalog)
    return [
        # purpose / persona
        "This space answers Medicare Advantage Star and HEDIS care-gap questions for a "
        "quality manager or VP of Stars. Lead with the business outcome: open care gaps, "
        "the retrievable Star-weighted value they represent, and the active outreach worklist.",

        # governance posture
        "Results are governed. member_id is a stable SHA-256 pseudonym, not a real member "
        "identifier, so you can group and join on it but never claim to identify a person. "
        "Birth dates are generalized to year and raw clinical values are not available to "
        "this persona. Report across all contracts unless the user names one.",

        # the prefer-certified / trusted-source directive
        f"For any question about retrievable Star-weighted value, totals, counts, member "
        f"counts or average closure propensity, use the certified metric view {mv}. It is "
        f"the single authoritative definition of these numbers. Prefer certified, trusted "
        f"sources over ad-hoc tables. Never use {trap} or anything under analytics_sandbox "
        f"for official numbers: it is uncertified and computes Star value incorrectly (it "
        f"flattens the triple-weighted MAD measure and counts closed gaps as retrievable).",

        # metric semantics
        "Retrievable Star-weighted value is the sum of expected_weighted_value over open "
        "scored gaps, where expected_weighted_value = calibrated closure propensity x CMS "
        "Star weight. It is the exec-defensible proxy for the dollars still recoverable this "
        "measurement year. member_ev is a single member's share of that, summed over their "
        "open gaps, and is how the worklist is ranked.",

        # domain glossary
        "Glossary. Star rating: CMS's 1 to 5 quality score for a Medicare Advantage contract; "
        "reaching 4.0 unlocks the Quality Bonus Payment, the dollar cliff that funds this work. "
        "HEDIS: the measure set the Star score is built from. Open gap: an actionable, not-yet-"
        "closed measure for a member this year. star_weight: the CMS weight of a measure; MAD "
        "medication adherence is triple-weighted (3), the others are weight 1. Active worklist: "
        "the top-500 members by member_ev on the active contract. lead_measure: the single "
        "measure the ai_decide model chose to lead a member's next contact with. bundle: whether "
        "to add a second ask to that contact. led_below_top_ev: true when the lead ask was not "
        "the member's single highest-value gap, a deliberate sequencing judgment.",

        # synonyms
        "Synonyms and mappings. 'Diabetes gaps' or 'diabetic members' means the diabetes HEDIS "
        "measures: EED (diabetic eye exam), GSD (HbA1c blood-sugar lab) and MAD (diabetes "
        "medication adherence). 'Blood pressure' or 'hypertension' means CBP. 'Colorectal', "
        "'colon' or 'cancer screening' means COL. 'Adherence' or 'medication' means MAD. "
        "'Retrievable value', 'opportunity', 'upside' or 'the lever' means the sum of "
        "expected_weighted_value. 'The worklist' means the active worklist on contract H1234.",

        # defaults
        "Defaults. Count open gaps unless the user asks about closed or all gaps. When a "
        "question is about the worklist and no contract is named, it refers to the active "
        "contract H1234. Round value figures to whole numbers in the answer.",
    ]


# ---------------------------------------------------------------------------
# Sample starter questions (shown in the space; cover the raw -> governed ->
# scored -> worklist narrative plus the three seed questions).
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS = [
    "What is the total retrievable Star-weighted value across all open care gaps?",
    "Show the retrievable Star-weighted value and open-gap count by measure.",
    "Which members have open diabetes gaps and the highest expected Star-weighted value?",
    "How many open CBP gaps are there on contract H1234?",
    "What is the total retrievable Star-weighted value in the active worklist?",
    "How many members in the active worklist are we leading with medication adherence?",
    "Which members are we leading with a lower-value ask than their highest-value gap, and why might that be?",
    "How many outreach drafts are pending human review, by measure?",
]


# ---------------------------------------------------------------------------
# Curated example question -> SQL pairs. These are the highest-leverage asset:
# the certified answers Genie learns the shape of. Every query reads the governed
# zone or the certified metric view (never the trap). {c} is the catalog.
# ---------------------------------------------------------------------------

def example_sqls(catalog):
    c = catalog
    return [
        {
            "question": "What is the total retrievable Star-weighted value across all open care gaps?",
            "sql": f"SELECT ROUND(MEASURE(retrievable_star_weighted_value)) AS retrievable_value\n"
                   f"FROM {c}.governance.star_value_metrics",
        },
        {
            "question": "Show the retrievable Star-weighted value and open-gap count by measure.",
            "sql": f"SELECT measure_id, measure_name,\n"
                   f"       ROUND(MEASURE(retrievable_star_weighted_value)) AS retrievable_value,\n"
                   f"       MEASURE(open_gap_count) AS open_gaps\n"
                   f"FROM {c}.governance.star_value_metrics\n"
                   f"GROUP BY measure_id, measure_name\n"
                   f"ORDER BY retrievable_value DESC",
        },
        {
            "question": "How many open care gaps are there in total, by measure?",
            "sql": f"SELECT measure_id, MEASURE(open_gap_count) AS open_gaps\n"
                   f"FROM {c}.governance.star_value_metrics\n"
                   f"GROUP BY measure_id ORDER BY open_gaps DESC",
        },
        {
            "question": "Which members have open diabetes gaps and the highest expected Star-weighted value?",
            "sql": f"SELECT member_id, measure_id, measure_name,\n"
                   f"       ROUND(expected_weighted_value, 3) AS expected_value, propensity\n"
                   f"FROM {c}.governance.gap_scores\n"
                   f"WHERE measure_id IN ('EED','GSD','MAD')\n"
                   f"ORDER BY expected_weighted_value DESC\n"
                   f"LIMIT 20",
        },
        {
            "question": "How many open CBP gaps are there on contract H1234?",
            "sql": f"SELECT MEASURE(open_gap_count) AS open_cbp_gaps\n"
                   f"FROM {c}.governance.star_value_metrics\n"
                   f"WHERE measure_id = 'CBP' AND contract_id = 'H1234'",
        },
        {
            "question": "What is the total retrievable Star-weighted value in the active worklist?",
            "sql": f"SELECT ROUND(SUM(member_ev)) AS worklist_retrievable_value, COUNT(*) AS members\n"
                   f"FROM {c}.governance.worklist",
        },
        {
            "question": "How many members in the active worklist are we leading with medication adherence?",
            "sql": f"SELECT lead_measure, lead_measure_name, COUNT(*) AS members\n"
                   f"FROM {c}.governance.worklist\n"
                   f"GROUP BY lead_measure, lead_measure_name\n"
                   f"ORDER BY members DESC",
        },
        {
            "question": "Which members are we leading with a lower-value ask than their highest-value gap?",
            "sql": f"SELECT member_id, lead_measure, lead_measure_name,\n"
                   f"       ROUND(lead_ev, 3) AS lead_value, lead_confidence\n"
                   f"FROM {c}.governance.worklist\n"
                   f"WHERE led_below_top_ev = true\n"
                   f"ORDER BY member_ev DESC",
        },
        {
            "question": "What is the average closure propensity for CBP gaps?",
            "sql": f"SELECT ROUND(MEASURE(avg_close_propensity), 4) AS avg_propensity\n"
                   f"FROM {c}.governance.star_value_metrics\n"
                   f"WHERE measure_id = 'CBP'",
        },
        {
            "question": "How many outreach drafts are pending human review, by measure?",
            "sql": f"SELECT measure_id, COUNT(*) AS drafts_pending_review\n"
                   f"FROM {c}.governance.outreach_drafts\n"
                   f"WHERE requires_human_review = true\n"
                   f"GROUP BY measure_id ORDER BY drafts_pending_review DESC",
        },
        {
            "question": "List the HEDIS measures and their Star weights.",
            "sql": f"SELECT measure_id, measure_name, star_weight\n"
                   f"FROM {c}.governance.measure_weights\n"
                   f"ORDER BY star_weight DESC, measure_id",
        },
        {
            "question": "What would we retrieve if we closed every open MAD medication-adherence gap?",
            "sql": f"SELECT ROUND(MEASURE(retrievable_star_weighted_value)) AS mad_retrievable_value,\n"
                   f"       MEASURE(open_gap_count) AS mad_open_gaps\n"
                   f"FROM {c}.governance.star_value_metrics\n"
                   f"WHERE measure_id = 'MAD'",
        },
    ]


# ---------------------------------------------------------------------------
# Join specs (the PK/FK-backed relationships, stated for Genie as join hints).
# ---------------------------------------------------------------------------

def join_specs(catalog):
    g = f"{catalog}.governance"
    return [
        {"left": f"{g}.gap_scores", "right": f"{g}.member_dim",
         "on": "gap_scores.member_id = member_dim.member_id",
         "note": "Scored gaps to the member entity (FK member_id)."},
        {"left": f"{g}.gap_scores", "right": f"{g}.measure_weights",
         "on": "gap_scores.measure_id = measure_weights.measure_id",
         "note": "Scored gaps to the measure dimension (FK measure_id)."},
        {"left": f"{g}.worklist", "right": f"{g}.member_dim",
         "on": "worklist.member_id = member_dim.member_id",
         "note": "Worklist to the member entity (FK member_id)."},
        {"left": f"{g}.care_gaps", "right": f"{g}.measure_weights",
         "on": "care_gaps.measure_id = measure_weights.measure_id",
         "note": "Gap inventory to the measure dimension (FK measure_id)."},
        {"left": f"{g}.outreach_drafts", "right": f"{g}.member_dim",
         "on": "outreach_drafts.member_id = member_dim.member_id",
         "note": "Drafts to the member entity (FK member_id)."},
    ]


# ---------------------------------------------------------------------------
# Reusable snippets: named measures and filters Genie can compose. These mirror
# the certified metric view's measures and the common slicers.
# ---------------------------------------------------------------------------

def measure_snippets(catalog):
    mv = metric_view(catalog)
    return [
        {"name": "retrievable Star-weighted value",
         "expr": "MEASURE(retrievable_star_weighted_value)", "source": mv,
         "note": "Sum of expected_weighted_value over open scored gaps."},
        {"name": "open gap count", "expr": "MEASURE(open_gap_count)", "source": mv},
        {"name": "member count", "expr": "MEASURE(member_count)", "source": mv},
        {"name": "average closure propensity", "expr": "MEASURE(avg_close_propensity)", "source": mv},
        {"name": "worklist retrievable value",
         "expr": "SUM(member_ev)", "source": f"{catalog}.governance.worklist",
         "note": "Retrievable value represented by the active worklist."},
    ]


FILTER_SNIPPETS = [
    {"name": "open diabetes gaps", "expr": "measure_id IN ('EED','GSD','MAD')"},
    {"name": "blood pressure gaps", "expr": "measure_id = 'CBP'"},
    {"name": "colorectal screening gaps", "expr": "measure_id = 'COL'"},
    {"name": "medication adherence (triple-weighted)", "expr": "measure_id = 'MAD'"},
    {"name": "active contract", "expr": "contract_id = 'H1234'"},
    {"name": "led below top EV", "expr": "led_below_top_ev = true"},
    {"name": "drafts pending human review", "expr": "requires_human_review = true"},
]


# ---------------------------------------------------------------------------
# Benchmarks. Each is a question with a check 04_benchmark.py can verify against
# the governed surfaces. `expect_fixed` carries a known-exact value; `expect` names
# a runtime check the harness computes and asserts equal across the governed path.
# ---------------------------------------------------------------------------

def benchmarks(catalog):
    c = catalog
    return [
        {
            "question": "What is the total number of open care gaps?",
            "sql": f"SELECT MEASURE(open_gap_count) AS n FROM {c}.governance.star_value_metrics",
            "expect_fixed": 67202,
            "note": "Reproduces Layers 1, 2 and 4 exactly (EED 9827 / GSD 5835 / CBP 25874 / COL 19313 / MAD 6353).",
        },
        {
            "question": "Open gaps by measure.",
            "sql": f"SELECT measure_id, MEASURE(open_gap_count) AS n "
                   f"FROM {c}.governance.star_value_metrics GROUP BY measure_id",
            "expect_fixed": {"EED": 9827, "GSD": 5835, "CBP": 25874, "COL": 19313, "MAD": 6353},
        },
        {
            "question": "Total retrievable Star-weighted value (certified).",
            "sql": f"SELECT ROUND(MEASURE(retrievable_star_weighted_value), 2) AS v "
                   f"FROM {c}.governance.star_value_metrics",
            "expect": "certified_total",
            "note": "The certified figure. The scratch trap's figure must differ (contrast test).",
        },
        {
            "question": "member_id must come back pseudonymized for the analyst persona.",
            "sql": f"SELECT member_id FROM {c}.governance.gap_scores LIMIT 1",
            "expect": "sha256_hex",
            "note": "64-char hex under the analyst SP, cleartext under break-glass. Governed-posture proof.",
        },
        {
            "question": "The active worklist is bounded to the top members on the active contract.",
            "sql": f"SELECT COUNT(*) AS n, COUNT(DISTINCT contract_id) AS contracts "
                   f"FROM {c}.governance.worklist",
            "expect": "worklist_bounds",
            "note": "<=500 members, exactly one contract (H1234).",
        },
        {
            "question": "ai_decide led some members with a lower-value ask than their top gap.",
            "sql": f"SELECT COUNT(*) AS n FROM {c}.governance.worklist WHERE led_below_top_ev = true",
            "expect": "positive",
            "note": "The sequencing judgment the pure EV ranking does not make.",
        },
    ]


# ---------------------------------------------------------------------------
# Short per-table descriptions and the low-cardinality columns worth a value
# dictionary (so Genie resolves "diabetes" / "MAD" / "H1234" to the right codes).
# ---------------------------------------------------------------------------

def table_descriptions(catalog):
    g = f"{catalog}.governance"
    return {
        f"{g}.member_dim": "Member entity dimension: one governed row per member. member_id is a pseudonym.",
        f"{g}.measure_weights": "Measure dimension: the five HEDIS Star measures, names and CMS Star weights (MAD triple-weighted).",
        f"{g}.gap_scores": "Scored open gaps: per member x open measure, closure propensity and expected Star-weighted value (EV). Certified source of retrievable value.",
        f"{g}.worklist": "Active prioritized worklist (top-500 by member_ev on contract H1234) with the ai_decide lead-outreach decision.",
        f"{g}.care_gaps": "Full care-gap inventory, all statuses (open / closed / excluded), one row per member x measure.",
        f"{g}.outreach_drafts": "Human-review GenAI outreach drafts for top-priority gaps. No PHI sent to the model.",
    }


VALUE_DICT_COLUMNS = {
    "member_dim": ["contract_id", "sex", "preferred_channel", "tenure_band"],
    "measure_weights": ["measure_id"],
    "gap_scores": ["measure_id", "contract_id"],
    "worklist": ["lead_measure", "contract_id", "preferred_channel", "tenure_band"],
    "care_gaps": ["measure_id", "gap_status", "contract_id"],
    "outreach_drafts": ["measure_id", "review_status"],
}


# ---------------------------------------------------------------------------
# Assemble the serialized_space v2 payload (shape confirmed empirically against
# genie.create_space). Text-ish fields are arrays of strings; every element id is
# a stable 32-hex uuid (uuid5 over a logical key, so re-runs produce the same ids
# and update_space diffs cleanly). join_specs and native benchmarks are omitted:
# joins are carried by the UC foreign-key graph, the example SQL and a join-hints
# instruction; benchmarks run through 04_benchmark.py. title / description /
# warehouse_id are create_space arguments, not part of serialized_space.
# ---------------------------------------------------------------------------

import uuid as _uuid

# stable namespace for this space's element ids (any fixed UUID works)
_NS = _uuid.uuid5(_uuid.NAMESPACE_DNS, "ma-stars-care-gap-outreach.genie.layer7")


def _id(key):
    return _uuid.uuid5(_NS, key).hex


def _tables_block(catalog):
    descs = table_descriptions(catalog)
    short = {v: k for k, v in tables(catalog).items()}  # fqn -> short name
    out = []
    for fqn in tables(catalog).values():
        entry = {"identifier": fqn}
        if fqn in descs:
            entry["description"] = [descs[fqn]]
        cols = VALUE_DICT_COLUMNS.get(short.get(fqn, ""), [])
        if cols:
            # v2 column_configs take only column_name (sorted; the get_example_values /
            # build_value_dictionary booleans are v1 fields the v2 validator rejects).
            # Naming the low-cardinality columns is what asks Genie to build their value
            # dictionaries so it resolves "diabetes" / "MAD" / "H1234" to the right codes.
            entry["column_configs"] = [{"column_name": c} for c in sorted(cols)]
        out.append(entry)
    # the certified metric view, and the uncertified trap (reachable so OntoRank's
    # preference for the certified source is a real, provable outcome)
    out.append({"identifier": metric_view(catalog),
                "description": ["Certified metric view: the authoritative retrievable Star-weighted value, counts and propensity. Prefer this for value/total/count questions."]})
    out.append({"identifier": scratch_trap(catalog),
                "description": ["UNCERTIFIED legacy scratch rollup. Computes Star value incorrectly (flattens the MAD triple weight, counts closed gaps). Do not use for official numbers."]})
    # The serialized_space validator requires data_sources.tables sorted by identifier.
    out.sort(key=lambda e: e["identifier"])
    return out


def _join_hint_instruction(catalog):
    lines = ["How the tables join (declared as Unity Catalog foreign keys):"]
    for j in join_specs(catalog):
        lines.append(f"{j['on']}  ({j['note']})")
    return lines


def _by_id(items):
    """The serialized_space validator requires every id-keyed collection sorted by id
    (same rule as data_sources.tables being sorted by identifier). Ids are uuid5 hex, so
    the logical build order is not the required order; sort here, at the one choke point."""
    return sorted(items, key=lambda e: e["id"])


def serialized_space(catalog):
    """The serialized_space JSON object for genie.create_space / update_space."""
    # text_instructions accepts at most one item; its `content` is an array of strings,
    # so every instruction line plus the join hints go into a single entry's content.
    content_lines = list(instructions(catalog)) + _join_hint_instruction(catalog)
    return {
        "version": 2,
        "config": {
            "sample_questions": _by_id([
                {"id": _id(f"sq-{i}"), "question": [q]}
                for i, q in enumerate(SAMPLE_QUESTIONS)
            ]),
        },
        "data_sources": {"tables": _tables_block(catalog)},
        "instructions": {
            "text_instructions": [
                {"id": _id("ti-0"), "content": content_lines}
            ],
            "example_question_sqls": _by_id([
                {"id": _id(f"ex-{i}"), "question": [ex["question"]], "sql": [ex["sql"]]}
                for i, ex in enumerate(example_sqls(catalog))
            ]),
            "sql_snippets": {
                "measures": _by_id([
                    {"id": _id(f"m-{i}"), "display_name": m["name"], "sql": [m["expr"]]}
                    for i, m in enumerate(measure_snippets(catalog))
                ]),
                "filters": _by_id([
                    {"id": _id(f"f-{i}"), "display_name": f["name"], "sql": [f["expr"]]}
                    for i, f in enumerate(FILTER_SNIPPETS)
                ]),
            },
        },
    }
