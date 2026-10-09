"""Shared feature construction for the gap-closure propensity model.

Both the training notebook (01_train_register) and the scoring notebook
(02_score_gaps) import this module so the feature frame is built one way, with
no train/serve skew. The feature set is deliberately limited to the signals that
are recoverable from observable member attributes and prior behavior; the latent
closure propensity that Layer 1 used to draw the prior-year labels is never
persisted to any table, so the model cannot read it and must recover the signal.

The one leakage risk is the prior closure rate. It is a per-member average of the
same `outcome` column that supplies the training label, so a training row's own
outcome must not sit inside its own feature. Training therefore uses a
leave-one-out rate (member totals minus the current attempt); scoring uses the
member's full prior-year rate, since at scoring time there is no current attempt
to exclude. Both sides shrink toward the global base rate so members with little
or no history get a sensible prior instead of a degenerate 0/1. The shrinkage and
one-hot encoding are identical on both sides; only the leave-one-out subtraction
differs, which is correct, not skew.
"""

# Measures, in a fixed order so the one-hot columns are stable across train/score.
MEASURES = ["EED", "GSD", "CBP", "COL", "MAD"]

# Beta-binomial shrinkage strength for the prior closure rate: a member needs
# roughly this many attempts before their observed rate outweighs the base rate.
ALPHA = 20.0

# Numeric / binary features, in fixed order. The first five are the signals Layer
# 1 actually used to drive closure (tenure, digital channel, distance, dual
# status) plus the behavioral proxy. age / condition flags are available and
# honest to include but were never closure drivers, so their importance should
# come back near zero: that is the recovered-not-cheated proof, not noise to hide.
NUMERIC_FEATURES = [
    "tenure_months",
    "digital_channel_on_file",
    "distance_to_provider_miles",
    "dual_eligible",
    "prior_closure_rate_smoothed",
    "prior_attempts",
    "age",
    "is_diabetic",
    "is_hypertensive",
]

# Canonical model input order. Train selects these columns; scoring feeds exactly
# these, in this order, into the model UDF.
FEATURE_COLUMNS = NUMERIC_FEATURES + [f"measure_{m}" for m in MEASURES]


def _measure_onehot(col):
    return ",\n  ".join(
        f"CASE WHEN {col} = '{m}' THEN 1 ELSE 0 END AS measure_{m}" for m in MEASURES
    )


# Global prior-year closure base rate. Computed from the same table on both sides,
# so the shrinkage prior is identical for training and scoring.
def _p0_cte(catalog):
    return (
        f"base AS (SELECT AVG(CASE WHEN outcome = 'closed' THEN 1.0 ELSE 0.0 END) AS p0 "
        f"FROM {catalog}.bronze.outreach_history)"
    )


def build_training_frame(spark, catalog):
    """One row per prior-year outreach attempt: label + leave-one-out features.

    label = 1 when the attempt closed the gap. prior_closure_rate_smoothed and
    prior_attempts exclude the current attempt (leave-one-out) to keep the
    attempt's own outcome out of its own feature.
    """
    sql = f"""
    WITH {_p0_cte(catalog)},
    mem AS (
      SELECT member_id,
             COUNT(*)                                            AS tot_attempts,
             SUM(CASE WHEN outcome = 'closed' THEN 1 ELSE 0 END) AS tot_closures
      FROM {catalog}.bronze.outreach_history
      GROUP BY member_id
    ),
    oh AS (
      SELECT o.member_id,
             o.measure_id,
             CASE WHEN o.outcome = 'closed' THEN 1 ELSE 0 END AS label,
             mem.tot_attempts,
             mem.tot_closures
      FROM {catalog}.bronze.outreach_history o
      JOIN mem USING (member_id)
    )
    SELECT
      oh.member_id,
      oh.label,
      m.tenure_months,
      CAST(m.digital_channel_on_file AS INT)   AS digital_channel_on_file,
      m.distance_to_provider_miles,
      CAST(m.dual_eligible AS INT)             AS dual_eligible,
      -- leave-one-out: subtract this attempt from the member's totals, then shrink.
      (oh.tot_attempts - 1)                    AS prior_attempts,
      CAST(((oh.tot_closures - oh.label) + {ALPHA} * base.p0)
        / ((oh.tot_attempts - 1) + {ALPHA}) AS DOUBLE) AS prior_closure_rate_smoothed,
      m.age,
      m.is_diabetic,
      m.is_hypertensive,
      {_measure_onehot("oh.measure_id")}
    FROM oh
    JOIN {catalog}.silver.members m ON oh.member_id = m.member_id
    CROSS JOIN base
    """
    return spark.sql(sql)


def build_scoring_frame(spark, catalog):
    """One row per OPEN care gap (member x measure), with the same features.

    prior_closure_rate_smoothed / prior_attempts use the member's full prior-year
    history (nothing to leave out at scoring), shrunk the same way. Members with no
    prior outreach fall back to the base rate. Carries member_id, contract_id,
    measure_id and measurement_year so the scored table can be scoped and joined.
    """
    sql = f"""
    WITH {_p0_cte(catalog)},
    mem AS (
      SELECT member_id,
             COUNT(*)                                            AS tot_attempts,
             SUM(CASE WHEN outcome = 'closed' THEN 1 ELSE 0 END) AS tot_closures
      FROM {catalog}.bronze.outreach_history
      GROUP BY member_id
    )
    SELECT
      g.member_id,
      m.contract_id,
      g.measure_id,
      g.measurement_year,
      m.tenure_months,
      CAST(m.digital_channel_on_file AS INT)   AS digital_channel_on_file,
      m.distance_to_provider_miles,
      CAST(m.dual_eligible AS INT)             AS dual_eligible,
      COALESCE(mem.tot_attempts, 0)            AS prior_attempts,
      CAST((COALESCE(mem.tot_closures, 0) + {ALPHA} * base.p0)
        / (COALESCE(mem.tot_attempts, 0) + {ALPHA}) AS DOUBLE) AS prior_closure_rate_smoothed,
      m.age,
      m.is_diabetic,
      m.is_hypertensive,
      {_measure_onehot("g.measure_id")}
    FROM {catalog}.gold.care_gaps g
    JOIN {catalog}.silver.members m ON g.member_id = m.member_id
    LEFT JOIN mem ON g.member_id = mem.member_id
    CROSS JOIN base
    WHERE g.gap_status = 'open'
    """
    return spark.sql(sql)
