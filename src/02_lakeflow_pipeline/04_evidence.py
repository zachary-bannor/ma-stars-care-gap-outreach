# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 2 evidence: Lakeflow pipeline
# MAGIC
# MAGIC Runs after the pipeline (full refresh). Reads the published gold tables and the
# MAGIC pipeline event log, then writes committed text evidence:
# MAGIC
# MAGIC 1. Bronze / silver / gold row counts.
# MAGIC 2. DQ expectation pass/fail from the event log.
# MAGIC 3. **Open-gap counts by measure vs Layer 1's intended 67,202** — the proof the
# MAGIC    layers are connected, not just co-present.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Target catalog")
dbutils.widgets.text("pipeline_id", "", "Pipeline id (for the event log)")
CATALOG = dbutils.widgets.get("catalog")
PIPELINE_ID = dbutils.widgets.get("pipeline_id")

EVIDENCE_PATH = f"/Volumes/{CATALOG}/ops/evidence/02_lakeflow_pipeline"
dbutils.fs.mkdirs(EVIDENCE_PATH)

# Layer 1's intended open gaps (the reproduction target).
INTENDED = {"EED": 9827, "GSD": 5835, "CBP": 25874, "COL": 19313, "MAD": 6353}
INTENDED_TOTAL = sum(INTENDED.values())

# COMMAND ----------

# MAGIC %md ## Row counts

# COMMAND ----------

TABLES = [
    ("bronze", "medical_claims"), ("bronze", "pharmacy_fills"), ("bronze", "member_roster"),
    ("bronze", "lab_results"), ("bronze", "providers"), ("bronze", "outreach_history"),
    ("silver", "members"), ("silver", "pdc"), ("silver", "prior_outreach"),
    ("gold", "care_gaps"), ("gold", "measure_weights"),
]
row_counts = {}
for sch, tbl in TABLES:
    row_counts[f"{sch}.{tbl}"] = spark.table(f"{CATALOG}.{sch}.{tbl}").count()
for k, v in row_counts.items():
    print(f"{k:28s} {v:>12,}")

# COMMAND ----------

# MAGIC %md ## Re-derived open gaps vs Layer 1 target

# COMMAND ----------

gaps_df = spark.sql(f"""
  SELECT measure_id,
         SUM(CASE WHEN gap_status = 'open'   THEN 1 ELSE 0 END) AS open_gaps,
         SUM(CASE WHEN gap_status = 'closed' THEN 1 ELSE 0 END) AS closed_gaps,
         COUNT(*) AS applicable
  FROM {CATALOG}.gold.care_gaps
  GROUP BY measure_id
""")
open_by_measure = {r["measure_id"]: r["open_gaps"] for r in gaps_df.collect()}
derived_total = sum(open_by_measure.values())
gap_detail = {r["measure_id"]: r.asDict() for r in gaps_df.collect()}

# COMMAND ----------

# MAGIC %md ## DQ expectations from the event log (best effort)

# COMMAND ----------

expectations = []
try:
    # Isolate the most recent pipeline update so counts are not summed across runs.
    latest = spark.sql(f"""
        SELECT origin.update_id AS uid
        FROM event_log('{PIPELINE_ID}')
        WHERE origin.update_id IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """).collect()
    latest_uid = latest[0]["uid"] if latest else None

    exp = spark.sql(f"""
        WITH e AS (
          SELECT explode(from_json(
                   details:flow_progress.data_quality.expectations,
                   'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>'
                 )) AS x
          FROM event_log('{PIPELINE_ID}')
          WHERE event_type = 'flow_progress'
            AND details:flow_progress.data_quality IS NOT NULL
            {f"AND origin.update_id = '{latest_uid}'" if latest_uid else ""}
        )
        SELECT x.name AS name, x.dataset AS dataset,
               SUM(x.passed_records) AS passed, SUM(x.failed_records) AS failed
        FROM e GROUP BY x.name, x.dataset ORDER BY dataset, name
    """)
    expectations = [r.asDict() for r in exp.collect()]
    for r in expectations:
        print(f"{r['dataset']:22s} {r['name']:22s} passed={r['passed']:>10,} failed={r['failed']:>8,}")
except Exception as ex:  # event-log shape varies; evidence does not depend on it
    print(f"expectation metrics unavailable: {ex}")

# COMMAND ----------

# MAGIC %md ## Write committed evidence

# COMMAND ----------

import json

reproduction = {
    m: {
        "intended": INTENDED[m],
        "derived": int(open_by_measure.get(m, 0)),
        "delta": int(open_by_measure.get(m, 0)) - INTENDED[m],
    }
    for m in INTENDED
}
summary = {
    "catalog": CATALOG,
    "pipeline_id": PIPELINE_ID,
    "row_counts": row_counts,
    "open_gaps_by_measure": {m: int(open_by_measure.get(m, 0)) for m in INTENDED},
    "derived_open_gaps_total": int(derived_total),
    "intended_open_gaps_total": INTENDED_TOTAL,
    "total_delta": int(derived_total) - INTENDED_TOTAL,
    "reproduction": reproduction,
    "expectations": expectations,
}

lines = [
    "# Layer 2 evidence: Lakeflow care-gap pipeline", "",
    f"Catalog `{CATALOG}`. Pipeline full-refreshed, gold re-derives HEDIS gaps "
    "independently from bronze claims/labs/fills.", "",
    "## Row counts", "",
    "| Table | Rows |", "| --- | --- |",
]
for k, v in row_counts.items():
    lines.append(f"| `{k}` | {v:,} |")

lines += [
    "", "## Re-derived open gaps vs Layer 1 target", "",
    "Layer 2 never receives the gap flags. These counts are re-derived from raw "
    "claims, labs, and fills, so landing on Layer 1's intended totals proves the "
    "layers are connected.", "",
    "| Measure | Intended (Layer 1) | Re-derived (Layer 2) | Delta |",
    "| --- | --- | --- | --- |",
]
for m in ["EED", "GSD", "CBP", "COL", "MAD"]:
    r = reproduction[m]
    lines.append(f"| {m} | {r['intended']:,} | {r['derived']:,} | {r['delta']:+,} |")
lines += [
    f"| **total** | **{INTENDED_TOTAL:,}** | **{derived_total:,}** | "
    f"**{derived_total - INTENDED_TOTAL:+,}** |", "",
]

if expectations:
    lines += [
        "## DQ expectations (most recent update)", "",
        "| Dataset | Expectation | Passed | Failed |",
        "| --- | --- | --- | --- |",
    ]
    for r in expectations:
        lines.append(f"| `{r['dataset']}` | {r['name']} | {r['passed']:,} | {r['failed']:,} |")
    lines.append("")

dbutils.fs.put(f"{EVIDENCE_PATH}/summary.json", json.dumps(summary, indent=2), overwrite=True)
dbutils.fs.put(f"{EVIDENCE_PATH}/run_evidence.md", "\n".join(lines), overwrite=True)

# sample gold rows (synthetic, safe to commit)
gap_sample = spark.sql(f"""
  SELECT * FROM {CATALOG}.gold.care_gaps
  WHERE measure_id IN ('EED','CBP','MAD') ORDER BY member_id LIMIT 15
""").toPandas()
dbutils.fs.put(f"{EVIDENCE_PATH}/sample_care_gaps.csv", gap_sample.to_csv(index=False), overwrite=True)

print("\n".join(lines))
print(f"\nevidence written to {EVIDENCE_PATH}")
