# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 6 / Lakebase worklist: build the ranked member worklist
# MAGIC
# MAGIC Builds `ops.member_worklist`, the member-grain coordinator worklist that is
# MAGIC synced to Lakebase (02) and written back to transactionally (03).
# MAGIC
# MAGIC ## Ranking vs sequencing
# MAGIC The worklist is ranked by `member_ev` = the sum of the member's open-gap
# MAGIC expected Star-weighted values from Layer 4 `gold.gap_scores`. That EV ranking is
# MAGIC the exec-defensible number and is never changed here.
# MAGIC
# MAGIC On top of the ranking, `ai_decide(state, questions)` makes a per-member
# MAGIC sequencing judgment the EV number does not make, BATCH-MATERIALIZED into
# MAGIC columns (not scored on demand):
# MAGIC   - `lead_measure`: which single open measure to LEAD the next contact with.
# MAGIC   - `bundle_second`: whether to add a second ask or keep the contact to one.
# MAGIC The chosen lead, its confidence, and the full per-option probabilities are
# MAGIC persisted (and committed as evidence).
# MAGIC
# MAGIC ## Scope and governance
# MAGIC ai_decide is materialized over the ACTIVE worklist: the top-N members by
# MAGIC member_ev on the coordinator's contract. The full 67,202-gap EV ranking in
# MAGIC `gold.gap_scores` is untouched underneath. The output carries only
# MAGIC coordinator-entitled columns (member_id cleartext, EV, measures, propensity,
# MAGIC channel, tenure, lead decision, draft): no birth_date, clinical values, dual
# MAGIC flag or sex. That column minimization is the operational analog of Layer 3's
# MAGIC governed consumption zone, so PHI never leaves the lakehouse into Lakebase.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("coord_contract", "H1234", "Coordinator contract scope")
dbutils.widgets.text("top_n", "500", "Active worklist size (members)")

CATALOG = dbutils.widgets.get("catalog")
CONTRACT = dbutils.widgets.get("coord_contract")
TOP_N = int(dbutils.widgets.get("top_n"))

# COMMAND ----------

import os
import sys

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nbdir = "/Workspace" + os.path.dirname(_ctx.notebookPath().get())
if _nbdir not in sys.path:
    sys.path.insert(0, _nbdir)

import worklist_sql  # noqa: E402

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Probe: 5 members through ai_decide
# MAGIC Validates the ai_decide call shape and the VARIANT parse on a cheap slice
# MAGIC before the full build. Asserts the lead decision parses and no decision error.

# COMMAND ----------

probe = spark.sql(worklist_sql.build_select_sql(CATALOG, CONTRACT, 5))
probe_rows = probe.select(
    "worklist_rank", "member_id", "member_ev", "open_gap_count",
    "lead_measure", "lead_confidence", "lead_probabilities",
    "bundle_decision", "bundle_confidence", "decide_error").collect()

for r in probe_rows:
    print(f"#{r.worklist_rank} {r.member_id} ev={r.member_ev} gaps={r.open_gap_count} "
          f"lead={r.lead_measure}@{r.lead_confidence} "
          f"bundle={r.bundle_decision}@{r.bundle_confidence} probs={r.lead_probabilities}")

assert all(r.decide_error is None for r in probe_rows), "ai_decide returned an error_message"
assert all(r.lead_measure for r in probe_rows), "lead_measure failed to parse"
assert all(0.0 <= (r.lead_confidence or -1) <= 1.0 for r in probe_rows), "confidence out of range"
print("\nprobe OK: ai_decide call shape and VARIANT parse validated")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Full build: top-N active worklist

# COMMAND ----------

spark.sql(worklist_sql.build_create_table_sql(CATALOG, CONTRACT, TOP_N))
print(f"built {CATALOG}.ops.member_worklist (top {TOP_N} members on {CONTRACT})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Build stats (lead-decision distribution, confidence, bundle rate)

# COMMAND ----------

stats = spark.sql(f"""
  SELECT COUNT(*) AS members,
         SUM(open_gap_count) AS open_gaps_in_worklist,
         ROUND(AVG(lead_confidence), 3) AS mean_lead_confidence,
         ROUND(AVG(CASE WHEN bundle_decision = 'bundle' THEN 1 ELSE 0 END), 3) AS bundle_rate,
         ROUND(AVG(CASE WHEN lead_measure = (
             SELECT measure_id FROM {CATALOG}.gold.gap_scores s
             WHERE s.member_id = w.member_id
             ORDER BY expected_weighted_value DESC LIMIT 1) THEN 1 ELSE 0 END), 3)
             AS lead_equals_top_ev_rate,
         SUM(CASE WHEN draft_subject IS NULL THEN 1 ELSE 0 END) AS members_without_draft,
         SUM(CASE WHEN decide_error IS NOT NULL THEN 1 ELSE 0 END) AS decide_errors
  FROM {CATALOG}.ops.member_worklist w
""").collect()[0]
print(stats)

dist = spark.sql(f"""
  SELECT lead_measure, COUNT(*) AS members, ROUND(AVG(lead_confidence), 3) AS mean_conf
  FROM {CATALOG}.ops.member_worklist GROUP BY lead_measure ORDER BY members DESC
""").collect()
print("\nlead_measure distribution:")
for d in dist:
    print(f"  {d.lead_measure}: {d.members} members (mean conf {d.mean_conf})")

assert stats.decide_errors == 0, "worklist contains ai_decide errors"
print("\nLayer 6 worklist build complete")
