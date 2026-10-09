# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 4 / ML propensity: batch-score open gaps
# MAGIC
# MAGIC Loads the champion model from Unity Catalog, scores every open care gap, and
# MAGIC writes `gold.gap_scores`: one row per member x open measure with the calibrated
# MAGIC closure propensity and the expected Star-weighted value (propensity x the
# MAGIC measure's Star weight), the number coordinators rank outreach by.
# MAGIC
# MAGIC Scoring reuses `feature_spec.build_scoring_frame`, so the features match
# MAGIC training exactly. The model is applied as an `mlflow.pyfunc.spark_udf`, the
# MAGIC distributed-serving pattern, even though the volume here is small. Runs as the
# MAGIC pipeline / engineer service principal and writes a managed Delta table into the
# MAGIC engineer-owned gold schema, so it inherits the Layer 3 posture (business
# MAGIC personas have no direct gold access; they consume downstream).

# COMMAND ----------

# MAGIC %pip install xgboost==2.1.4

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("model_schema", "gold", "Registered-model schema")
dbutils.widgets.text("model_name", "gap_closure_propensity", "Registered-model name")
dbutils.widgets.text("output_table", "gold.gap_scores", "Output table (schema.table)")

CATALOG = dbutils.widgets.get("catalog")
MODEL_FQN = f"{CATALOG}.{dbutils.widgets.get('model_schema')}.{dbutils.widgets.get('model_name')}"
OUTPUT_TABLE = dbutils.widgets.get("output_table")

# COMMAND ----------

import os
import sys

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nbdir = "/Workspace" + os.path.dirname(_ctx.notebookPath().get())
if _nbdir not in sys.path:
    sys.path.insert(0, _nbdir)

import mlflow
from pyspark.sql import functions as F

import feature_spec
from feature_spec import FEATURE_COLUMNS

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md ## Resolve the champion version and load it as a UDF

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
version = mlflow.tracking.MlflowClient().get_model_version_by_alias(MODEL_FQN, "champion").version
model_uri = f"models:/{MODEL_FQN}@champion"
print(f"scoring with {MODEL_FQN} version {version}")

propensity_udf = mlflow.pyfunc.spark_udf(spark, model_uri, result_type="double", env_manager="local")

# COMMAND ----------

# MAGIC %md ## Score the open gaps and compute expected Star-weighted value

# COMMAND ----------

features = feature_spec.build_scoring_frame(spark, CATALOG)
weights = spark.table("gold.measure_weights").select("measure_id", "star_weight")

scored = (
    features
    # The model signature is all double (training coerced features to float);
    # cast the struct columns to match so MLflow's strict schema enforcement,
    # which will not widen int to float on its own, accepts the input.
    .withColumn("propensity",
                propensity_udf(F.struct(*[F.col(c).cast("double").alias(c) for c in FEATURE_COLUMNS])))
    .join(weights, "measure_id", "left")
    .withColumn("expected_weighted_value", F.col("propensity") * F.col("star_weight"))
    .withColumn("model_name", F.lit(MODEL_FQN))
    .withColumn("model_version", F.lit(str(version)))
    .withColumn("scored_at", F.current_timestamp())
    .select(
        "member_id",
        "contract_id",
        "measure_id",
        "measurement_year",
        "propensity",
        "star_weight",
        "expected_weighted_value",
        "model_name",
        "model_version",
        "scored_at",
    )
)

# COMMAND ----------

# MAGIC %md ## Write gold.gap_scores

# COMMAND ----------

(
    scored.write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
)
spark.sql(
    f"ALTER TABLE {OUTPUT_TABLE} SET TBLPROPERTIES "
    "('comment' = 'Per-member x open-measure closure propensity and expected Star-weighted value. "
    "Scored by the UC-registered gap_closure_propensity model; engineer-owned, Layer 3 gold posture.')"
)

n = spark.table(OUTPUT_TABLE).count()
print(f"wrote {OUTPUT_TABLE}: {n:,} scored open gaps")
spark.sql(f"""
  SELECT measure_id, COUNT(*) AS gaps,
         ROUND(AVG(propensity), 4) AS avg_propensity,
         ROUND(AVG(expected_weighted_value), 4) AS avg_expected_value
  FROM {OUTPUT_TABLE} GROUP BY measure_id ORDER BY measure_id
""").show()
