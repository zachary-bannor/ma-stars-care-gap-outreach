# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 7 / Certified metric view: star_value_metrics
# MAGIC
# MAGIC The authoritative, governed definition of the exec numbers the VP-Stars persona
# MAGIC asks for: retrievable Star-weighted value, open-gap counts, member counts, average
# MAGIC closure propensity, defined ONCE over the certified `governance.gap_scores` fact
# MAGIC and sliced by the measure / contract / weight dimensions.
# MAGIC
# MAGIC This is the semantic core of the Genie Ontology for this space. OntoRank favors
# MAGIC certified sources, so this metric view is what Genie should reach for when a
# MAGIC question touches "retrievable value", in preference to any ad-hoc rollup. The
# MAGIC uncertified `analytics_sandbox.star_value_rollup` trap (built in 02) exists to
# MAGIC prove that preference.
# MAGIC
# MAGIC Metric views resolve their source under the caller's identity, so the Layer 3
# MAGIC masks and the contract row filter on `governance.gap_scores` still apply when the
# MAGIC analyst queries this view.

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("analyst_principal", "9490fdb4-1a5e-42eb-b5a6-4ecab7d48337",
                     "Quality-analyst SP application_id")
CATALOG = dbutils.widgets.get("catalog")
ANALYST_SP = dbutils.widgets.get("analyst_principal")
spark.sql(f"USE CATALOG {CATALOG}")


def try_sql(sql, label):
    try:
        spark.sql(sql)
        print("ok:", label)
        return True
    except Exception as e:
        print(f"skip ({label}): {str(e).splitlines()[0][:100]}")
        return False


# COMMAND ----------

# MAGIC %md ## Metric view definition (YAML)

# COMMAND ----------

# gold.gap_scores holds only open gaps, so governance.gap_scores is already the open
# population; the retrievable-value measures aggregate it directly.
spark.sql(f"""
CREATE OR REPLACE VIEW governance.star_value_metrics
WITH METRICS
LANGUAGE YAML
COMMENT 'Certified Star-value metric view: the authoritative retrievable Star-weighted value, open-gap and member counts, and average closure propensity over scored open gaps, by measure / contract / Star weight. Prefer this over any ad-hoc rollup.'
AS $$
version: 0.1
source: {CATALOG}.governance.gap_scores
dimensions:
  - name: measure_id
    expr: measure_id
  - name: measure_name
    expr: measure_name
  - name: contract_id
    expr: contract_id
  - name: star_weight
    expr: star_weight
measures:
  - name: retrievable_star_weighted_value
    expr: SUM(expected_weighted_value)
  - name: open_gap_count
    expr: COUNT(1)
  - name: member_count
    expr: COUNT(DISTINCT member_id)
  - name: avg_close_propensity
    expr: AVG(propensity)
$$
""")
print("created governance.star_value_metrics")

# COMMAND ----------

# MAGIC %md ## Certify + grant

# COMMAND ----------

# Certification is the OntoRank authority signal. The tag verb differs across runtimes
# for a METRIC_VIEW; try the view form, then the table form.
if not try_sql("ALTER VIEW governance.star_value_metrics SET TAGS ('system.certification_status' = 'certified')",
               "certify (ALTER VIEW)"):
    try_sql("ALTER TABLE governance.star_value_metrics SET TAGS ('system.certification_status' = 'certified')",
            "certify (ALTER TABLE)")

spark.sql(f"GRANT SELECT ON VIEW governance.star_value_metrics TO `{ANALYST_SP}`")
print("granted SELECT to analyst SP")

# COMMAND ----------

# MAGIC %md ## Smoke test

# COMMAND ----------

display(spark.sql("""
  SELECT measure_id, measure_name,
         MEASURE(retrievable_star_weighted_value) AS retrievable_value,
         MEASURE(open_gap_count) AS open_gaps,
         MEASURE(member_count) AS members
  FROM governance.star_value_metrics
  GROUP BY measure_id, measure_name
  ORDER BY retrievable_value DESC
"""))
