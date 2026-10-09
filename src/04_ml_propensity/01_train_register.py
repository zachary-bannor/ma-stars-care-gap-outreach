# Databricks notebook source
# MAGIC %md
# MAGIC # Layer 4 / ML propensity: train and register
# MAGIC
# MAGIC Trains a gradient-boosted classifier for the probability a member closes a
# MAGIC given open gap **if contacted**, calibrates it, tracks it in MLflow, and
# MAGIC registers it to Unity Catalog.
# MAGIC
# MAGIC The label is last year's outreach outcome (`outcome = 'closed'`). The honest
# MAGIC part of the design lives in `feature_spec.py`: the latent propensity Layer 1
# MAGIC used to draw those labels is never persisted, so the model recovers the signal
# MAGIC from observable features, and the prior-closure-rate feature is built
# MAGIC leave-one-out and split by member so a row's own outcome never leaks into its
# MAGIC own feature or across the train/test boundary. Feature importance should come
# MAGIC back concentrated on the four signals Layer 1 actually used, which is the
# MAGIC recovered-not-cheated proof.
# MAGIC
# MAGIC Runs as the pipeline / engineer service principal, which owns the medallion
# MAGIC writes. Serverless; xgboost is the only library not already on the base image.

# COMMAND ----------

# MAGIC %pip install xgboost==2.1.4

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "zrb_fe_bar_uhc_stars_catalog", "Catalog")
dbutils.widgets.text("model_schema", "gold", "Registered-model schema")
dbutils.widgets.text("model_name", "gap_closure_propensity", "Registered-model name")

CATALOG = dbutils.widgets.get("catalog")
MODEL_SCHEMA = dbutils.widgets.get("model_schema")
MODEL_FQN = f"{CATALOG}.{MODEL_SCHEMA}.{dbutils.widgets.get('model_name')}"

# COMMAND ----------

# The bundle syncs feature_spec.py / model_def.py next to this notebook; put that
# folder on the path so the shared feature and model code imports cleanly.
import os
import sys

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nbdir = "/Workspace" + os.path.dirname(_ctx.notebookPath().get())
if _nbdir not in sys.path:
    sys.path.insert(0, _nbdir)

import numpy as np
import pandas as pd
import mlflow
from mlflow.models.signature import infer_signature
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from xgboost import XGBClassifier

import feature_spec
from feature_spec import FEATURE_COLUMNS
from model_def import GapPropensityModel

SEED = 42

# COMMAND ----------

# MAGIC %md ## Build the training frame
# MAGIC
# MAGIC One row per prior-year outreach attempt, with leave-one-out prior-closure-rate
# MAGIC features. Small enough (~90k rows) to train in the driver.

# COMMAND ----------

pdf = feature_spec.build_training_frame(spark, CATALOG).toPandas()
print(f"training rows: {len(pdf):,}   members: {pdf.member_id.nunique():,}")
print(f"closure base rate: {pdf.label.mean():.4f}")

# COMMAND ----------

# MAGIC %md ## Split by member, not by row
# MAGIC
# MAGIC A member can appear in up to five rows (one per measure outreached). Splitting
# MAGIC by member keeps all of a member's rows on one side so the per-member prior
# MAGIC rate cannot leak a test outcome into training. 60 / 20 / 20. Validation fits
# MAGIC the calibrator; test is fully held out and supplies the reported metrics.

# COMMAND ----------

members = pdf["member_id"].drop_duplicates().to_numpy()
np.random.default_rng(SEED).shuffle(members)
n = len(members)
train_m = set(members[: int(0.6 * n)])
val_m = set(members[int(0.6 * n) : int(0.8 * n)])
test_m = set(members[int(0.8 * n) :])

tr = pdf[pdf.member_id.isin(train_m)]
va = pdf[pdf.member_id.isin(val_m)]
te = pdf[pdf.member_id.isin(test_m)]

# Coerce to float: Spark decimals arrive as object dtype through toPandas, which
# the gradient-boosted library rejects.
X_tr, y_tr = tr[FEATURE_COLUMNS].astype("float64"), tr["label"].to_numpy()
X_va, y_va = va[FEATURE_COLUMNS].astype("float64"), va["label"].to_numpy()
X_te, y_te = te[FEATURE_COLUMNS].astype("float64"), te["label"].to_numpy()
print(f"train {len(tr):,} rows / {len(train_m):,} members | "
      f"val {len(va):,} / {len(val_m):,} | test {len(te):,} / {len(test_m):,}")

# COMMAND ----------

# MAGIC %md ## Fit the gradient-boosted model, then calibrate
# MAGIC
# MAGIC Shallow, regularized trees with a fixed seed for a deterministic rebuild.
# MAGIC Isotonic calibration is fit on the validation split so the probability the
# MAGIC expected-value math multiplies is honest, not just well-ranked.

# COMMAND ----------

HPARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_lambda=1.0,
    objective="binary:logistic",
    eval_metric="logloss",
    tree_method="hist",
    random_state=SEED,
    n_jobs=-1,
)
clf = XGBClassifier(**HPARAMS)
clf.fit(X_tr, y_tr)

iso = IsotonicRegression(out_of_bounds="clip")
iso.fit(clf.predict_proba(X_va)[:, 1], y_va)

# COMMAND ----------

# MAGIC %md ## Evaluate on the held-out test split

# COMMAND ----------

raw_te = clf.predict_proba(X_te)[:, 1]
cal_te = iso.predict(raw_te)

metrics = {
    "test_roc_auc": float(roc_auc_score(y_te, cal_te)),
    "test_pr_auc": float(average_precision_score(y_te, cal_te)),
    "test_log_loss": float(log_loss(y_te, cal_te)),
    "test_brier_raw": float(brier_score_loss(y_te, raw_te)),
    "test_brier_calibrated": float(brier_score_loss(y_te, cal_te)),
    "test_base_rate": float(y_te.mean()),
    "n_train_rows": float(len(tr)),
    "n_val_rows": float(len(va)),
    "n_test_rows": float(len(te)),
    "n_train_members": float(len(train_m)),
    "n_test_members": float(len(test_m)),
}
for k, v in metrics.items():
    print(f"{k:24s} {v:.4f}")

# COMMAND ----------

# MAGIC %md ## Feature importance, two ways
# MAGIC
# MAGIC XGBoost gain can over-credit high-cardinality features, so it is cross-checked
# MAGIC with permutation importance (test-set AUC drop when a feature is shuffled). If
# MAGIC the two agree that tenure / digital channel / distance / dual status / prior
# MAGIC rate carry the signal and age / conditions do not, the model recovered Layer
# MAGIC 1's true structure rather than cheating.

# COMMAND ----------

gain = clf.get_booster().get_score(importance_type="gain")
gain_total = sum(gain.values()) or 1.0
gain_norm = {f: gain.get(f, 0.0) / gain_total for f in FEATURE_COLUMNS}

base_auc = roc_auc_score(y_te, cal_te)
perm_rng = np.random.default_rng(7)
perm = {}
for f in FEATURE_COLUMNS:
    drops = []
    for _ in range(3):
        xp = X_te.copy()
        xp[f] = perm_rng.permutation(xp[f].to_numpy())
        drops.append(base_auc - roc_auc_score(y_te, iso.predict(clf.predict_proba(xp)[:, 1])))
    perm[f] = float(np.mean(drops))

imp = (
    pd.DataFrame({"feature": FEATURE_COLUMNS})
    .assign(gain=lambda d: d.feature.map(gain_norm), permutation_importance=lambda d: d.feature.map(perm))
    .sort_values("permutation_importance", ascending=False)
    .reset_index(drop=True)
)
print(imp.to_string(index=False))

# COMMAND ----------

# MAGIC %md ## Reliability (calibration) bins

# COMMAND ----------

cal_df = pd.DataFrame({"p": cal_te, "y": y_te})
cal_df["bin"] = pd.qcut(cal_df.p, 10, labels=False, duplicates="drop")
calibration = (
    cal_df.groupby("bin")
    .agg(mean_pred=("p", "mean"), frac_pos=("y", "mean"), n=("y", "size"))
    .reset_index()
)
print(calibration.to_string(index=False))

# COMMAND ----------

# MAGIC %md ## Track in MLflow and register to Unity Catalog
# MAGIC
# MAGIC The registered model is the calibrated wrapper (XGBoost + isotonic), so the
# MAGIC scoring job gets the calibrated probability straight from `models:/...@champion`.

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
model = GapPropensityModel(clf=clf, iso=iso, feature_columns=FEATURE_COLUMNS)
signature = infer_signature(X_te, cal_te)

with mlflow.start_run(run_name="gap_closure_propensity") as run:
    mlflow.log_params(HPARAMS)
    mlflow.log_param("features", ",".join(FEATURE_COLUMNS))
    mlflow.log_param("label", "outreach_history.outcome == 'closed'")
    mlflow.log_param("prior_rate", "leave-one-out, beta shrink alpha=%g" % feature_spec.ALPHA)
    mlflow.log_param("split", "by member_id 60/20/20")
    mlflow.log_param("calibration", "isotonic on validation split")
    mlflow.log_metrics(metrics)
    mlflow.log_dict(imp.to_dict(orient="records"), "feature_importance.json")

    info = mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=model,
        code_paths=[os.path.join(_nbdir, "model_def.py"), os.path.join(_nbdir, "feature_spec.py")],
        signature=signature,
        input_example=X_te.head(5),
        pip_requirements=["xgboost==2.1.4", "scikit-learn", "pandas"],
        registered_model_name=MODEL_FQN,
    )

version = info.registered_model_version
mlflow.tracking.MlflowClient().set_registered_model_alias(MODEL_FQN, "champion", version)
print(f"registered {MODEL_FQN} version {version} as @champion  (run {run.info.run_id})")

# COMMAND ----------

# MAGIC %md ## Stage evidence to gold
# MAGIC
# MAGIC The local evidence step reads these back through the warehouse (same pattern
# MAGIC as Layer 3) and writes the committed text evidence. These are model outputs,
# MAGIC so they live in the engineer-owned gold schema alongside gap_scores.

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

metrics_pdf = pd.DataFrame({"metric": list(metrics), "value": [float(v) for v in metrics.values()]})
metrics_pdf["model_version"] = str(version)
spark.createDataFrame(metrics_pdf).write.mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable("gold.gap_scores_metrics")

spark.createDataFrame(imp).write.mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable("gold.gap_scores_feature_importance")

spark.createDataFrame(calibration).write.mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable("gold.gap_scores_calibration")

print("staged gap_scores_metrics / gap_scores_feature_importance / gap_scores_calibration")
