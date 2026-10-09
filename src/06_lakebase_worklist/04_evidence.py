#!/usr/bin/env python3
"""Layer 6 / Lakebase worklist: assemble committed, text-readable run evidence.

Runs locally against the SQL warehouse (same pattern as Layers 2-5 evidence):

    python3 src/06_lakebase_worklist/04_evidence.py

Writes to evidence/06_lakebase_worklist/:
  - summary.json          layer config + worklist/ai_decide statistics
  - sample_worklist.csv   top worklist rows with the materialized lead decision
  - sample_ai_decide.csv  per-member lead/bundle choice, confidence, probabilities
  - sequencing_divergence.csv  members whose ai_decide lead differs from pure top-EV
  - run_evidence.md       the narrative

The write-back proof (committed action, rollback, least-privilege denial, governed
round-trip) is captured separately by 03_coordinator_writeback.py into
writeback_proof.md and writeback_actions.csv; this script re-reads the write-back
through Unity Catalog to confirm it is present.
"""
import csv
import json
import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = "fe-vm-zrb-fe-bar-uhc-stars"
CATALOG = "zrb_fe_bar_uhc_stars_catalog"
WAREHOUSE = "3c261b5b5dfe9c21"
INSTANCE = "zrb-stars-worklist"
WORKLIST = f"{CATALOG}.ops.member_worklist"
SYNCED = f"{CATALOG}.ops.worklist"

EVID = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "06_lakebase_worklist")
os.makedirs(EVID, exist_ok=True)

w = WorkspaceClient(profile=PROFILE)


def q(sql):
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE, statement=sql, catalog=CATALOG, wait_timeout="50s")
    if r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if r.status.error else f"state={r.status.state}"
        raise RuntimeError(f"{msg}\n  SQL: {sql}")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
    rows = r.result.data_array if (r.result and r.result.data_array) else []
    return cols, rows


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        wr.writerows([["" if v is None else v for v in row] for row in rows])


# --- summary stats -----------------------------------------------------------
_, s = q(f"""
  SELECT COUNT(*), SUM(open_gap_count), ROUND(AVG(lead_confidence), 3),
         SUM(CAST(lead_fallback_applied AS INT)),
         ROUND(AVG(CASE WHEN bundle_decision = 'bundle' THEN 1 ELSE 0 END), 3),
         SUM(CASE WHEN draft_subject IS NOT NULL THEN 1 ELSE 0 END),
         SUM(CASE WHEN decide_error IS NOT NULL THEN 1 ELSE 0 END),
         ROUND(MAX(member_ev), 4), ROUND(MIN(member_ev), 4)
  FROM {WORKLIST}""")
(members, open_gaps, mean_conf, fallbacks, bundle_rate, with_draft, errors,
 max_ev, min_ev) = s[0]

_, dist = q(f"SELECT lead_measure, COUNT(*) c, ROUND(AVG(lead_confidence),3) mc "
            f"FROM {WORKLIST} GROUP BY lead_measure ORDER BY c DESC")
lead_dist = {r[0]: {"members": int(r[1]), "mean_confidence": float(r[2])} for r in dist}

# members whose ai_decide lead differs from the pure top-EV gap (the judgment EV
# does not make): join to the per-member highest-EV measure.
div_sql = f"""
  WITH topev AS (
    SELECT member_id, measure_id AS top_ev_measure FROM (
      SELECT member_id, measure_id,
             ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY expected_weighted_value DESC) rn
      FROM {CATALOG}.gold.gap_scores) WHERE rn = 1)
  SELECT w.worklist_rank, w.member_id, w.lead_measure, t.top_ev_measure,
         w.lead_confidence, w.lead_probabilities
  FROM {WORKLIST} w JOIN topev t USING (member_id)
  WHERE w.lead_measure <> t.top_ev_measure
  ORDER BY w.worklist_rank"""
div_cols, div_rows = q(div_sql)

# --- sample tables -----------------------------------------------------------
sw_cols, sw_rows = q(f"""
  SELECT worklist_rank, member_id, member_ev, open_gap_count, lead_measure,
         lead_measure_name, lead_ev, lead_propensity, lead_confidence,
         bundle_decision, bundle_measure, preferred_channel, tenure_band,
         (draft_subject IS NOT NULL) AS has_draft
  FROM {WORKLIST} ORDER BY worklist_rank LIMIT 25""")
write_csv(os.path.join(EVID, "sample_worklist.csv"), sw_cols, sw_rows)

ad_cols, ad_rows = q(f"""
  SELECT member_id, open_gap_count, lead_measure, lead_measure_model,
         lead_fallback_applied, lead_confidence, lead_probabilities,
         bundle_decision, bundle_confidence, bundle_probabilities
  FROM {WORKLIST} ORDER BY worklist_rank LIMIT 15""")
write_csv(os.path.join(EVID, "sample_ai_decide.csv"), ad_cols, ad_rows)

write_csv(os.path.join(EVID, "sequencing_divergence.csv"), div_cols, div_rows)

# --- governed round-trip confirmation ---------------------------------------
_, rt = q(f"SELECT COUNT(*) FROM {CATALOG}.ops.coordinator_action")
_, st = q(f"SELECT COUNT(*) FROM {CATALOG}.ops.worklist_status WHERE status <> 'new'")
writeback_actions, writeback_statuses = int(rt[0][0]), int(st[0][0])

inst = w.database.get_database_instance(name=INSTANCE)
synced = w.database.get_synced_database_table(name=SYNCED)
synced_state = (synced.data_synchronization_status.detailed_state.value
                if synced.data_synchronization_status else None)

summary = {
    "layer": "06_lakebase_worklist",
    "instance": {"name": INSTANCE, "capacity": inst.capacity,
                 "pg_version": inst.pg_version, "state": inst.state.value},
    "catalog": CATALOG, "schema": "ops",
    "source_table": WORKLIST, "synced_table": SYNCED, "synced_state": synced_state,
    "writeback_tables": ["ops.worklist_status", "ops.coordinator_action"],
    "contract_scope": "H1234",
    "worklist": {
        "members": int(members), "open_gaps_covered": int(open_gaps),
        "member_ev_max": float(max_ev), "member_ev_min": float(min_ev),
    },
    "ai_decide": {
        "mean_lead_confidence": float(mean_conf),
        "out_of_set_fallbacks": int(fallbacks),
        "decide_errors": int(errors),
        "bundle_rate": float(bundle_rate),
        "lead_measure_distribution": lead_dist,
        "sequencing_divergence_vs_top_ev": len(div_rows),
    },
    "drafts_attached": int(with_draft),
    "writeback_roundtrip": {"actions_in_uc": writeback_actions,
                            "statuses_advanced": writeback_statuses},
}
with open(os.path.join(EVID, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

# --- narrative ---------------------------------------------------------------
md = os.path.join(EVID, "run_evidence.md")
with open(md, "w") as f:
    f.write("# Layer 6 / Lakebase worklist run evidence\n\n")
    f.write(f"Lakebase instance `{INSTANCE}` ({inst.capacity}, {inst.pg_version}, "
            f"{inst.state.value}) serves the ranked care-coordinator worklist with "
            "transactional outreach write-back. The worklist is built in the lakehouse "
            f"(`{WORKLIST}`), synced into Postgres as `{SYNCED}` ({synced_state}), and "
            "written back to through two native Postgres tables registered in Unity "
            "Catalog.\n\n")
    f.write("## Ranking vs sequencing\n\n")
    f.write(f"The worklist holds the top {members} members by `member_ev` (sum of their "
            "open-gap expected Star-weighted values from Layer 4). That EV ranking is the "
            "exec-defensible number and is never changed. On top of it, `ai_decide` chose, "
            "per member, which measure to LEAD the next contact with and whether to bundle "
            "a second ask, batch-materialized into worklist columns with confidence and "
            "per-option probabilities.\n\n")
    f.write("| metric | value |\n|---|---|\n")
    f.write(f"| members in worklist | {members} |\n")
    f.write(f"| open gaps covered | {open_gaps} |\n")
    f.write(f"| mean lead confidence | {mean_conf} |\n")
    f.write(f"| bundle rate | {bundle_rate} |\n")
    f.write(f"| out-of-set fallbacks | {fallbacks} |\n")
    f.write(f"| ai_decide errors | {errors} |\n")
    f.write(f"| lead differs from pure top-EV | {len(div_rows)} members |\n")
    f.write(f"| drafts attached (Layer 5 segments) | {with_draft} / {members} |\n\n")
    f.write("Lead-measure distribution: ")
    f.write(", ".join(f"{k} {v['members']}" for k, v in lead_dist.items()) + ".\n")
    f.write("MAD leads the top of the worklist because the highest-EV members carry the "
            "triple-weighted adherence gap; the sequencing diverges from pure EV where an "
            "easier or channel-fit ask is the better first contact "
            f"({len(div_rows)} members, see sequencing_divergence.csv).\n\n")
    f.write("## Governed posture\n\n")
    f.write("The worklist projection is column-minimized to coordinator-entitled fields "
            "(member_id cleartext, EV, measures, propensity, channel, tenure, lead decision, "
            "draft). No birth_date, clinical values, dual flag or sex leave the lakehouse "
            "into Postgres. Postgres persona roles mirror the Layer 3 UC grants: the "
            "coordinator reads the worklist and writes the log, the analyst is read-only.\n\n")
    f.write("## Transactional write-back\n\n")
    f.write("See writeback_proof.md and writeback_actions.csv. Connected as the "
            "care-coordinator service principal, a single transaction appended an outreach "
            "action and advanced the status to `contacted`; a rolled-back update left the "
            "status intact; an ungranted DELETE was denied; and the committed write-back is "
            f"readable through Unity Catalog ({writeback_actions} action row(s), "
            f"{writeback_statuses} status(es) advanced), reaching the governed lakehouse and "
            "Genie with no reverse ETL.\n")

print(json.dumps(summary, indent=2))
print(f"\nevidence written to {os.path.relpath(EVID)}")
