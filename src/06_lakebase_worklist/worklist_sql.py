"""Layer 6 / Lakebase worklist: the ai_decide() lead-outreach decision SQL.

Pure module (no Spark, no SDK) so the JSON builders and the VARIANT parser can
be unit-tested off-cluster (see tests/test_worklist_sql.py), the same way Layer 5
kept lint_draft/parse_draft testable in prompt_spec.py.

The worklist is MEMBER-grain. It is ranked by `member_ev` = the sum of the
member's open-gap expected Star-weighted values from Layer 4's gold.gap_scores.
That EV ranking is the exec-defensible number and ai_decide never changes it.

On top of that ranking, ai_decide(state, questions) makes a per-member sequencing
judgment the EV number does not make:
  - lead_measure: which single open measure to LEAD the next contact with.
  - bundle_second: whether to add a second ask or keep the contact to one.
Both are BATCH-MATERIALIZED into worklist columns during the build (not scored
on demand), and the confidence + per-option probabilities are persisted as
committed evidence.

ai_decide requires `questions` to be a LITERAL (fixed) string, so the decision
schema is fixed for every member: the lead-measure criteria list all five
measures generically, and each member's actual open gaps, their EV, propensity
and star weight go into the dynamic `state`. The model is instructed to lead only
from the member's open measures; a SQL guard snaps any out-of-set choice back to
the member's top-EV open gap and records that it did (lead_fallback_applied).
"""

# Internal, coordinator-facing measure names (the coordinator is entitled to the
# clinical framing; this is not the member-facing draft copy from Layer 5).
MEASURE_NAME = {
    "EED": "Diabetic retinal eye exam (EED)",
    "GSD": "Diabetes HbA1c blood-sugar lab (GSD)",
    "CBP": "Controlling blood pressure (CBP)",
    "COL": "Colorectal cancer screening (COL)",
    "MAD": "Medication adherence for diabetes (MAD, triple-weighted)",
}

# Fixed criteria for the lead-measure choice (the member's actual open gaps and
# their EV live in the dynamic state; these describe what each measure is).
MEASURE_CRITERIA = {
    "EED": "Diabetic retinal eye exam: a yearly covered eye exam for members with diabetes.",
    "GSD": "Diabetes HbA1c blood-sugar lab: a routine covered blood draw.",
    "CBP": "Controlling blood pressure: a blood-pressure check and any needed follow-up.",
    "COL": "Colorectal cancer screening: a covered screening for age-eligible members.",
    "MAD": ("Medication adherence for diabetes: keeping diabetes prescriptions filled "
            "on time. CMS triple-weighted, so each closure moves Stars about 3x."),
}

LEAD_INSTRUCTIONS = (
    "Pick the single measure to LEAD this member's next outreach contact with. "
    "Choose the lead ONLY from the open measures listed in the member context; "
    "never pick a measure that is not in that list. The expected Star-weighted "
    "value (EV) ranking is already fixed and is not yours to change; you are "
    "sequencing which ASK leads for this member. Favor the open gap most likely "
    "to win a first successful contact: usually the highest-EV open gap, but an "
    "easier or channel-fit ask can lead, and MAD medication adherence is "
    "triple-weighted so it often leads even at slightly lower raw EV."
)

BUNDLE_INSTRUCTIONS = (
    "Decide whether to add a SECOND ask to this same contact or keep it to a "
    "single ask. Weigh the extra retrievable value against member burden and the "
    "channel: a digital touch tolerates a second ask better than a single phone "
    "or mail contact."
)

BUNDLE_CRITERIA = {
    "bundle": "Add the next-highest-value ask to the same contact",
    "single": "Keep to a single ask to reduce member burden",
}


def build_questions():
    """The fixed ai_decide `questions` object (identical for every member)."""
    return {
        "lead_measure": {
            "type": "choice",
            "instructions": LEAD_INSTRUCTIONS,
            "criteria": dict(MEASURE_CRITERIA),
        },
        "bundle_second": {
            "type": "choice",
            "instructions": BUNDLE_INSTRUCTIONS,
            "criteria": dict(BUNDLE_CRITERIA),
        },
    }


def questions_json():
    import json
    return json.dumps(build_questions())


def segment_key(measure_id, channel, tenure):
    """Layer 5 draft segment key: measure|channel|tenure (identical derivation)."""
    return f"{measure_id}|{channel}|{tenure}"


def parse_decision(raw):
    """Parse the ai_decide VARIANT/JSON string into the fields the worklist and
    the evidence keep. Safety-critical and defensive: a malformed or error
    response yields Nones and the error message, never an exception."""
    import json
    try:
        d = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (ValueError, TypeError):
        return {
            "error": "unparseable ai_decide response",
            "lead_measure": None, "lead_confidence": None,
            "lead_probabilities": None, "bundle_decision": None,
            "bundle_confidence": None, "bundle_probabilities": None,
        }
    if not isinstance(d, dict):
        d = {}
    ans = ((d.get("response") or {}).get("answers")) or {}
    lead = ans.get("lead_measure") or {}
    bundle = ans.get("bundle_second") or {}
    return {
        "error": d.get("error_message"),
        "lead_measure": lead.get("choice"),
        "lead_confidence": lead.get("confidence"),
        "lead_probabilities": lead.get("probabilities"),
        "bundle_decision": bundle.get("choice"),
        "bundle_confidence": bundle.get("confidence"),
        "bundle_probabilities": bundle.get("probabilities"),
    }


def _sql_str(s):
    """A safe single-quoted SQL string literal (doubles embedded quotes)."""
    return "'" + str(s).replace("'", "''") + "'"


def _measure_name_case(col):
    """A CASE expression mapping a measure_id column to its display name."""
    whens = "\n      ".join(
        f"WHEN {_sql_str(mid)} THEN {_sql_str(name)}"
        for mid, name in MEASURE_NAME.items()
    )
    return f"CASE {col}\n      {whens}\n      ELSE {col} END"


def build_select_sql(catalog, contract_id, n):
    """The full worklist SELECT: aggregate gold.gap_scores to member grain,
    bound to the top-N members by member_ev on `contract_id`, run ai_decide per
    member (fixed questions literal, per-member state), snap any out-of-set lead
    back to the top-EV open gap, pick the bundle measure, and join the Layer 5
    draft for the lead measure's segment.

    Returns ONLY coordinator-entitled columns (member_id cleartext, EV, measures,
    propensity, channel, tenure, the lead decision, the draft). No birth_date,
    clinical values, dual flag or sex ever leave the lakehouse into this
    projection; that column minimization is this layer's governed posture, the
    operational analog of Layer 3's governed consumption zone.

    The same SELECT serves the 5-row probe (n=5) and the full build (n=500).
    """
    mname_measure = _measure_name_case("f.measure_id")
    mname_lead = _measure_name_case("e.lead_measure")
    mname_bundle = _measure_name_case("bp.bundle_measure")
    questions_literal = _sql_str(questions_json())
    return f"""
WITH feat AS (
  SELECT
    g.member_id, g.contract_id, m.plan_id, g.measure_id, g.measurement_year,
    g.expected_weighted_value AS ev, g.propensity, g.star_weight,
    CASE WHEN m.digital_channel_on_file THEN 'digital' ELSE 'mail_phone' END AS channel,
    CASE
      WHEN m.tenure_months IS NULL THEN 'established'
      WHEN m.tenure_months < 12 THEN 'new'
      WHEN m.tenure_months < 48 THEN 'established'
      ELSE 'longtime'
    END AS tenure_band
  FROM {catalog}.gold.gap_scores g
  JOIN {catalog}.silver.members m USING (member_id)
  WHERE g.contract_id = {_sql_str(contract_id)}
),
ranked AS (
  SELECT member_id, SUM(ev) AS member_ev, COUNT(*) AS open_gap_count
  FROM feat GROUP BY member_id
),
active AS (
  SELECT member_id, member_ev, open_gap_count
  FROM ranked ORDER BY member_ev DESC, member_id LIMIT {int(n)}
),
mrank AS (
  SELECT f.member_id, f.measure_id, f.ev, f.propensity,
    ROW_NUMBER() OVER (PARTITION BY f.member_id ORDER BY f.ev DESC, f.measure_id) AS ev_rank
  FROM feat f JOIN active a USING (member_id)
),
topm AS (
  SELECT member_id, measure_id AS top_measure, ev AS top_ev, propensity AS top_prop
  FROM mrank WHERE ev_rank = 1
),
agg AS (
  SELECT
    f.member_id, a.member_ev, a.open_gap_count,
    ANY_VALUE(f.contract_id) AS contract_id,
    ANY_VALUE(f.plan_id) AS plan_id,
    ANY_VALUE(f.channel) AS channel,
    ANY_VALUE(f.tenure_band) AS tenure_band,
    CONCAT_WS(', ', SORT_ARRAY(COLLECT_LIST(f.measure_id))) AS open_measures,
    TO_JSON(COLLECT_LIST(NAMED_STRUCT(
      'measure', f.measure_id,
      'measure_name', {mname_measure},
      'expected_value', ROUND(f.ev, 4),
      'propensity', ROUND(f.propensity, 4),
      'star_weight', f.star_weight,
      'channel', f.channel,
      'tenure', f.tenure_band))) AS gaps_json
  FROM feat f JOIN active a USING (member_id)
  GROUP BY f.member_id, a.member_ev, a.open_gap_count
),
decided AS (
  SELECT
    agg.*,
    CONCAT('Member has ', CAST(open_gap_count AS STRING),
           ' open Medicare Advantage Star care gaps on contract ', contract_id,
           '. Preferred outreach channel: ', channel, '. Tenure band: ', tenure_band,
           '. Open measures (choose the lead ONLY from these): ', open_measures,
           '. Each open gap with its expected Star-weighted value (EV, the exec-ranked ',
           'dollar proxy), calibrated closure propensity, and CMS star weight, as JSON: ',
           gaps_json) AS state
  FROM agg
),
scored AS (
  SELECT d.*, ai_decide(d.state, {questions_literal}) AS decision FROM decided d
),
parsed AS (
  SELECT
    member_id, contract_id, plan_id, member_ev, open_gap_count, channel, tenure_band,
    decision:response:answers:lead_measure:choice::STRING AS lead_measure_model,
    decision:response:answers:lead_measure:confidence::DOUBLE AS lead_confidence,
    CAST(decision:response:answers:lead_measure:probabilities AS STRING) AS lead_probabilities,
    decision:response:answers:bundle_second:choice::STRING AS bundle_decision,
    decision:response:answers:bundle_second:confidence::DOUBLE AS bundle_confidence,
    CAST(decision:response:answers:bundle_second:probabilities AS STRING) AS bundle_probabilities,
    decision:error_message::STRING AS decide_error
  FROM scored
),
eff AS (
  SELECT
    p.member_id, p.contract_id, p.plan_id, p.member_ev, p.open_gap_count,
    p.channel, p.tenure_band, p.lead_measure_model, p.lead_confidence,
    p.lead_probabilities, p.bundle_decision, p.bundle_confidence,
    p.bundle_probabilities, p.decide_error,
    CASE WHEN ld.measure_id IS NOT NULL THEN p.lead_measure_model ELSE t.top_measure END AS lead_measure,
    (ld.measure_id IS NULL) AS lead_fallback_applied,
    COALESCE(ld.ev, t.top_ev) AS lead_ev,
    COALESCE(ld.propensity, t.top_prop) AS lead_propensity
  FROM parsed p
  LEFT JOIN mrank ld ON ld.member_id = p.member_id AND ld.measure_id = p.lead_measure_model
  LEFT JOIN topm t ON t.member_id = p.member_id
),
bundle_pick AS (
  SELECT e.member_id, MIN_BY(m.measure_id, m.ev_rank) AS bundle_measure
  FROM eff e JOIN mrank m
    ON m.member_id = e.member_id AND m.measure_id <> e.lead_measure
  GROUP BY e.member_id
),
drafts AS (
  SELECT segment_key,
    ANY_VALUE(draft_subject) AS draft_subject,
    ANY_VALUE(draft_body) AS draft_body,
    BOOL_OR(requires_human_review) AS requires_human_review
  FROM {catalog}.gold.outreach_drafts GROUP BY segment_key
)
SELECT
  ROW_NUMBER() OVER (ORDER BY e.member_ev DESC, e.member_id) AS worklist_rank,
  e.member_id, e.contract_id, e.plan_id,
  ROUND(e.member_ev, 4) AS member_ev,
  e.open_gap_count,
  e.lead_measure,
  {mname_lead} AS lead_measure_name,
  e.lead_measure_model,
  e.lead_fallback_applied,
  ROUND(e.lead_ev, 4) AS lead_ev,
  ROUND(e.lead_propensity, 4) AS lead_propensity,
  e.lead_confidence,
  e.lead_probabilities,
  e.bundle_decision,
  e.bundle_confidence,
  e.bundle_probabilities,
  CASE WHEN e.bundle_decision = 'bundle' THEN bp.bundle_measure END AS bundle_measure,
  CASE WHEN e.bundle_decision = 'bundle' THEN {mname_bundle} END AS bundle_measure_name,
  e.channel AS preferred_channel,
  e.tenure_band,
  dr.draft_subject,
  dr.draft_body,
  COALESCE(dr.requires_human_review, TRUE) AS requires_human_review,
  e.decide_error,
  CURRENT_TIMESTAMP() AS built_at
FROM eff e
LEFT JOIN bundle_pick bp ON bp.member_id = e.member_id
LEFT JOIN drafts dr ON dr.segment_key = CONCAT(e.lead_measure, '|', e.channel, '|', e.tenure_band)
""".strip()


def build_create_table_sql(catalog, contract_id, n, table="ops.member_worklist"):
    """Wrap the worklist SELECT in a CREATE OR REPLACE TABLE for the full build."""
    return (f"CREATE OR REPLACE TABLE {catalog}.{table} AS\n"
            + build_select_sql(catalog, contract_id, n))
