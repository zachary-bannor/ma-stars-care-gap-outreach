# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 7 / The uncertified scratch trap
# MAGIC
# MAGIC A deliberately planted anti-pattern: the kind of popular-but-wrong rollup that
# MAGIC floats around every payer analytics org. `analytics_sandbox.star_value_rollup`
# MAGIC reads straight off the raw `gold.care_gaps` (bypassing the governed zone) and
# MAGIC computes "Star value" WRONG in two business-meaningful ways:
# MAGIC
# MAGIC   1. It treats every measure as Star weight 1, so it misses that MAD medication
# MAGIC      adherence is CMS triple-weighted (the single biggest retrievable lever).
# MAGIC   2. It counts closed and excluded gaps as retrievable, not just open gaps.
# MAGIC
# MAGIC An exec who trusts this rollup under-invests in the triple-weighted adherence
# MAGIC lever and overstates how much value is still retrievable. It is UNCERTIFIED and
# MAGIC tagged deprecated.
# MAGIC
# MAGIC It is aggregate-only (no member grain, no identifiers), so it leaks nothing: it is
# MAGIC a pure semantic trap, not a governance hole. Its only purpose is to prove that
# MAGIC Genie Ontology / OntoRank prefers the certified `governance.star_value_metrics`
# MAGIC over an uncertified source when both could answer the same question.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("analyst_principal", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337",
                     "Quality-analyst SP application_id")
CATALOG = dbutils.widgets.get("catalog")
ANALYST_SP = dbutils.widgets.get("analyst_principal")
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

spark.sql("CREATE SCHEMA IF NOT EXISTS analytics_sandbox "
          "COMMENT 'Ungoverned analyst scratch area. Not certified. Do not use for official reporting.'")

# A plausible, authoritative-sounding name and comment make it a realistic trap: it
# reads straight off raw gold, counts all gap statuses, and flattens the Star weight.
spark.sql(f"""
CREATE OR REPLACE VIEW analytics_sandbox.star_value_rollup
COMMENT 'Star value rollup by measure (legacy quality-dashboard source). Totals gaps and Star value across the book.'
AS
SELECT
  g.measure_id,
  w.measure_name,
  COUNT(*)                              AS total_gaps,
  CAST(COUNT(*) AS DOUBLE)              AS star_value   -- WRONG: flat weight 1, all statuses
FROM {CATALOG}.gold.care_gaps g
LEFT JOIN {CATALOG}.gold.measure_weights w USING (measure_id)
GROUP BY g.measure_id, w.measure_name
""")
print("created analytics_sandbox.star_value_rollup (uncertified trap)")

# COMMAND ----------

# Mark it uncertified/deprecated so the authority contrast with the certified metric
# view is explicit in the catalog metadata OntoRank reads.
try:
    spark.sql("ALTER VIEW analytics_sandbox.star_value_rollup "
              "SET TAGS ('system.certification_status' = 'deprecated', 'care_gap_data_class' = 'uncertified_scratch')")
except Exception as e:
    print("tag note:", str(e).splitlines()[0][:100])

# Reachable by the analyst persona, so it is a genuine competing source Genie could
# pick. Ownership chaining lets the analyst read the aggregate without raw gold access;
# no member grain leaves the view.
spark.sql(f"GRANT SELECT ON VIEW analytics_sandbox.star_value_rollup TO `{ANALYST_SP}`")
print("granted SELECT to analyst SP")

# COMMAND ----------

display(spark.sql("SELECT * FROM analytics_sandbox.star_value_rollup ORDER BY star_value DESC"))
