# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 5 / GenAI outreach drafting
# MAGIC
# MAGIC Drafts a personalized, measure-appropriate, human-review outreach message for
# MAGIC the highest-priority open care gaps, routed through the governed Unity AI
# MAGIC Gateway endpoint `zrb-stars-outreach-gateway` (guardrails, a rate limit, usage
# MAGIC tracking, payload logging), which fronts Claude Sonnet 5.5.
# MAGIC
# MAGIC Priority is `gold.gap_scores.expected_weighted_value` (Layer 4): calibrated
# MAGIC closure propensity times the measure's Star weight. We draft the top N gaps per
# MAGIC measure so the worklist and the committed evidence span all five measures, and
# MAGIC triple-weighted MAD rightly dominates the very top.
# MAGIC
# MAGIC ## Honesty and safety
# MAGIC The model never sees PHI. The prompt (see `prompt_spec.py`) carries only
# MAGIC non-identifying segment features: the covered service, the member's preferred
# MAGIC channel, and a coarse tenure band. Names, ids, dates, contracts, diagnoses and
# MAGIC clinical values are never sent, so the model cannot leak or invent them.
# MAGIC Everything personal is a `[FIRST_NAME]` / `[PLAN_NAME]` / `[CLINIC_PHONE]` merge
# MAGIC placeholder a human coordinator fills before sending. Because the prompt depends
# MAGIC only on the segment, we generate one draft per distinct (measure, channel,
# MAGIC tenure) segment and assign it to every member x measure in that segment: no
# MAGIC redundant identical calls, and the gateway's governance applies to every call.
# MAGIC Every row is a `pending_review` draft and is never auto-sent.
# MAGIC
# MAGIC Runs as the engineer / pipeline identity and writes `gold.outreach_drafts` into
# MAGIC the engineer-owned gold schema (Layer 3 posture), then projects a masked,
# MAGIC contract-filtered `governance.outreach_drafts` into the governed consumption
# MAGIC zone for coordinators.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("endpoint_name", "zrb-stars-outreach-gateway", "Gateway endpoint")
dbutils.widgets.text("model_label", "databricks-claude-sonnet-5-5", "Model behind the gateway")
dbutils.widgets.text("top_n_per_measure", "50", "Top N gaps per measure to draft")
dbutils.widgets.text("output_table", "gold.outreach_drafts", "Output table (schema.table)")
dbutils.widgets.text("coord_principal", "07369d4b-134b-42bb-b2aa-25c57456404d",
                     "Care-coordinator SP application_id")
dbutils.widgets.text("analyst_principal", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337",
                     "Quality-analyst SP application_id")

CATALOG = dbutils.widgets.get("catalog")
ENDPOINT = dbutils.widgets.get("endpoint_name")
MODEL_LABEL = dbutils.widgets.get("model_label")
TOP_N = int(dbutils.widgets.get("top_n_per_measure"))
OUTPUT_TABLE = dbutils.widgets.get("output_table")
COORD_SP = dbutils.widgets.get("coord_principal")
ANALYST_SP = dbutils.widgets.get("analyst_principal")

# COMMAND ----------

import os
import sys

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nbdir = "/Workspace" + os.path.dirname(_ctx.notebookPath().get())
if _nbdir not in sys.path:
    sys.path.insert(0, _nbdir)

import datetime as _dt

from pyspark.sql import functions as F, Window
from pyspark.sql import types as T

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

import prompt_spec

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md ## Priority worklist: top N open gaps per measure, with segment features

# COMMAND ----------

# gap_scores holds the ranking; silver.members carries the two non-identifying
# segment features (digital-contact flag, tenure). The join and selection run as
# the engineer identity, which can read both.
scores = spark.table("gold.gap_scores")
members = spark.table("silver.members").select(
    "member_id", "digital_channel_on_file", "tenure_months")

rank_w = Window.partitionBy("measure_id").orderBy(F.col("expected_weighted_value").desc())
worklist = (
    scores.join(members, "member_id", "left")
    .withColumn("rk", F.row_number().over(rank_w))
    .filter(F.col("rk") <= TOP_N)
    .drop("rk")
)
rows = worklist.collect()
print(f"selected {len(rows)} gaps ({TOP_N} per measure) to draft")

# COMMAND ----------

# MAGIC %md ## Resolve each gap to a non-PHI segment

# COMMAND ----------

def row_segment(r):
    channel = prompt_spec.channel_of(bool(r["digital_channel_on_file"]))
    tenure = prompt_spec.tenure_band(r["tenure_months"])
    return channel, tenure, prompt_spec.segment_key(r["measure_id"], channel, tenure)

segments = {}  # segment_key -> (measure_id, channel, tenure)
for r in rows:
    channel, tenure, key = row_segment(r)
    segments.setdefault(key, (r["measure_id"], channel, tenure))
print(f"{len(segments)} distinct non-PHI segments to generate")

# COMMAND ----------

# MAGIC %md ## Draft each segment through the governed gateway

# COMMAND ----------

w = WorkspaceClient()


def draft_segment(measure_id, channel, tenure):
    system, user = prompt_spec.build_messages(measure_id, channel, tenure)
    try:
        resp = w.serving_endpoints.query(
            name=ENDPOINT,
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
                ChatMessage(role=ChatMessageRole.USER, content=user),
            ],
            # Sonnet 5.5 is a reasoning model and spends completion tokens thinking
            # before the message, so the budget must comfortably cover both. The
            # drafts themselves are a few sentences; the headroom is for reasoning.
            max_tokens=2000,
        )
        content = resp.choices[0].message.content if resp.choices else ""
        parsed = prompt_spec.parse_draft(content)
        flags = prompt_spec.lint_draft(parsed["body"])
        return {"subject": parsed["subject"], "body": parsed["body"],
                "lint_flags": ",".join(flags), "status": "pending_review"}
    except Exception as e:
        # The gateway may block a call (guardrails) or error transiently. Keep the
        # batch resilient and record it; the row still lands as a non-sendable,
        # review-required draft rather than silently vanishing.
        msg = str(e).splitlines()[0][:160]
        return {"subject": "", "body": "", "lint_flags": f"generation_error:{msg}",
                "status": "generation_failed"}


drafts = {}  # segment_key -> draft dict
for key, (measure_id, channel, tenure) in segments.items():
    drafts[key] = draft_segment(measure_id, channel, tenure)
    print(f"· {key}: {drafts[key]['status']}"
          + (f" [{drafts[key]['lint_flags']}]" if drafts[key]["lint_flags"] else ""))

ok = sum(1 for d in drafts.values() if d["status"] == "pending_review")
print(f"\ngenerated {ok}/{len(drafts)} segment drafts cleanly")

# COMMAND ----------

# MAGIC %md ## Assemble gold.outreach_drafts (one row per prioritized member x measure)

# COMMAND ----------

generated_at = _dt.datetime.utcnow()
out_rows = []
for r in rows:
    channel, tenure, key = row_segment(r)
    d = drafts[key]
    out_rows.append((
        r["member_id"], r["contract_id"], r["measure_id"], int(r["measurement_year"]),
        channel, tenure, key,
        d["subject"], d["body"], d["lint_flags"],
        d["status"], True,
        ENDPOINT, MODEL_LABEL,
        float(r["expected_weighted_value"]), generated_at,
    ))

schema = T.StructType([
    T.StructField("member_id", T.StringType()),
    T.StructField("contract_id", T.StringType()),
    T.StructField("measure_id", T.StringType()),
    T.StructField("measurement_year", T.IntegerType()),
    T.StructField("channel", T.StringType()),
    T.StructField("tenure_band", T.StringType()),
    T.StructField("segment_key", T.StringType()),
    T.StructField("draft_subject", T.StringType()),
    T.StructField("draft_body", T.StringType()),
    T.StructField("lint_flags", T.StringType()),
    T.StructField("review_status", T.StringType()),
    T.StructField("requires_human_review", T.BooleanType()),
    T.StructField("model_endpoint", T.StringType()),
    T.StructField("model_name", T.StringType()),
    T.StructField("expected_weighted_value", T.DoubleType()),
    T.StructField("generated_at", T.TimestampType()),
])
out_df = spark.createDataFrame(out_rows, schema)

(
    out_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(OUTPUT_TABLE)
)
spark.sql(
    f"ALTER TABLE {OUTPUT_TABLE} SET TBLPROPERTIES "
    "('comment' = 'Human-review GenAI outreach drafts for the top-priority open gaps. "
    "Routed through the governed Unity AI Gateway (zrb-stars-outreach-gateway / Claude Sonnet 5.5); "
    "no PHI sent to the model; identifiers are merge placeholders. Never auto-sent. Engineer-owned gold posture.')"
)
print(f"wrote {OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count():,} drafts")
spark.sql(f"""
  SELECT measure_id, COUNT(*) AS drafts,
         SUM(CASE WHEN review_status='pending_review' THEN 1 ELSE 0 END) AS clean,
         ROUND(AVG(expected_weighted_value), 4) AS avg_expected_value
  FROM {OUTPUT_TABLE} GROUP BY measure_id ORDER BY measure_id
""").show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Governed consumption projection: governance.outreach_drafts
# MAGIC Coordinator-facing managed Delta table. member_id masked by the Layer 3 policy
# MAGIC function; row-filtered to the coordinator's assigned contracts. Reuses the
# MAGIC existing `fn_mask_member_id` and `fn_rls_contract` so the drafts carry the same
# MAGIC posture as `governance.care_gaps`.

# COMMAND ----------

import time


def run(sql):
    # SET MASK / SET ROW FILTER race on the table etag; retry the transient.
    for attempt in range(6):
        try:
            spark.sql(sql)
            return
        except Exception as e:
            if ("UC_ETAG_MISMATCH" in str(e) or "has been modified" in str(e)) and attempt < 5:
                time.sleep(2 + attempt)
                continue
            raise


run(f"""
CREATE OR REPLACE TABLE governance.outreach_drafts
COMMENT 'Governed outreach drafts worklist. member_id masked by policy; row-filtered by contract. Human-review only.'
AS
SELECT member_id, contract_id, measure_id, measurement_year, channel,
       draft_subject, draft_body, review_status, requires_human_review,
       expected_weighted_value, generated_at
FROM {OUTPUT_TABLE}
""")
run("ALTER TABLE governance.outreach_drafts ALTER COLUMN member_id SET MASK governance.fn_mask_member_id")
run("ALTER TABLE governance.outreach_drafts SET ROW FILTER governance.fn_rls_contract ON (contract_id)")

# Classification tags, consistent with the Layer 3 consumption zone.
run("ALTER TABLE governance.outreach_drafts ALTER COLUMN member_id "
    "SET TAGS ('sensitivity' = 'pii', 'care_gap_data_class' = 'direct_identifier')")
run("ALTER TABLE governance.outreach_drafts SET TAGS ('system.certification_status' = 'certified')")

# Coordinators + analysts read it (break-glass + admin read as owner).
for p in (COORD_SP, ANALYST_SP):
    run(f"GRANT SELECT ON TABLE governance.outreach_drafts TO `{p}`")

print("governance.outreach_drafts projected (masked member_id + contract RLS, granted to coordinator + analyst SPs)")
